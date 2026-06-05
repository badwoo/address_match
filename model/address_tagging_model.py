"""
MGeo门址地址结构化要素解析模型模块
====================================

本模块封装阿里 MGeo 门址地址结构化要素解析模型，用于地址分词和要素提取。

模型信息：
    - 模型名称: iic/mgeo_geographic_elements_tagging_chinese_base
    - 任务类型: token-classification（命名实体识别/NER）
    - 适用场景: 将地址文本拆分为结构化要素

核心功能：
    1. 加载 MGeo 地址要素解析模型
    2. 对地址文本进行NER分词
    3. 将BIO标签解析为12级结构化输出
    4. 支持批量推理

12级结构化输出：
    province  - 省
    city     - 城市
    district - 区划
    street   - 街道
    community- 社区
    road     - 街路巷名、道、路
    roadno   - 门楼牌、门牌号、路号
    area     - 片区、地物名、居民小区名、自然村名、专属区域名
    bldg     - 建筑物名、楼栋
    unit     - 单元
    floor    - 楼层名
    house    - 户室号、房间

模型NER标签到12级输出的映射（多个标签可能合并到同一输出字段）：
    prov            → province（省）
    city            → city（城市）
    district        → district（区/县）
    town            → street（乡镇/街道）
    community       → community（社区/村）
    road            → road（道路名）
    roadno          → roadno（门牌号/路号）
    poi, devzone, village_group → area（片区/小区/村组）
    subpoi          → bldg（建筑物/楼栋）
    cellno          → unit（单元）
    floorno         → floor（楼层）
    houseno         → house（户室号/房间）
    assist, distance, intersection → 忽略（不输出到12级结构）
"""

import torch
import numpy as np
import os
from config import Config, _find_model_local_path
from utils.logger import logger

TAGGING_MODEL_NAME = 'iic/mgeo_geographic_elements_tagging_chinese_base'

NER_TO_OUTPUT_MAP = {
    'prov': 'province',
    'city': 'city',
    'district': 'district',
    'town': 'street',
    'community': 'community',
    'road': 'road',
    'roadno': 'roadno',
    'poi': 'area',
    'devzone': 'area',
    'village_group': 'area',
    'subpoi': 'bldg',
    'cellno': 'unit',
    'floorno': 'floor',
    'houseno': 'house',
}

OUTPUT_FIELDS = [
    'province', 'city', 'district', 'street', 'community',
    'road', 'roadno', 'area', 'bldg', 'unit', 'floor', 'house'
]

OUTPUT_FIELD_LABELS = {
    'province': '省',
    'city': '城市',
    'district': '区划',
    'street': '街道',
    'community': '社区',
    'road': '街路巷名、道、路',
    'roadno': '门楼牌、门牌号、路号',
    'area': '片区、地物名、居民小区名、自然村名、专属区域名',
    'bldg': '建筑物名、楼栋',
    'unit': '单元',
    'floor': '楼层名',
    'house': '户室号、房间',
}

# 17级输出字段（MGeo模型原始NER标签，不做合并映射）
OUTPUT_FIELDS_17 = [
    'prov', 'city', 'district', 'town', 'road', 'roadno', 'intersection',
    'poi', 'subpoi', 'houseno', 'cellno', 'floorno', 'community',
    'assist', 'distance', 'devzone', 'village_group'
]

OUTPUT_FIELD_LABELS_17 = {
    'prov': '省',
    'city': '城市',
    'district': '区/县',
    'town': '乡镇/街道',
    'road': '道路名',
    'roadno': '路号',
    'intersection': '路口',
    'poi': '兴趣点',
    'subpoi': '子兴趣点',
    'houseno': '门牌号/楼栋号',
    'cellno': '单元号',
    'floorno': '楼层号',
    'community': '社区/村庄',
    'assist': '辅助信息/补充说明',
    'distance': '距离信息',
    'devzone': '开发区',
    'village_group': '村组',
}

# 17级双字段输出（每个NER标签对应2个字段：主字段 + _2后缀字段）
# 第一个匹配值写入主字段，后续同类型值拼接到 _2 字段
_BASE_17_FIELDS = OUTPUT_FIELDS_17
OUTPUT_FIELDS_17_2 = []
for _f in _BASE_17_FIELDS:
    OUTPUT_FIELDS_17_2.append(_f)
    OUTPUT_FIELDS_17_2.append(f'{_f}_2')

OUTPUT_FIELD_LABELS_17_2 = {}
for _f in _BASE_17_FIELDS:
    _label = OUTPUT_FIELD_LABELS_17.get(_f, _f)
    OUTPUT_FIELD_LABELS_17_2[_f] = _label
    OUTPUT_FIELD_LABELS_17_2[f'{_f}_2'] = f'{_label}(副)'

try:
    from modelscope import AutoTokenizer as MS_AutoTokenizer, AutoModelForTokenClassification as MS_AutoModelForTokenCls
    MODELSCOPE_AVAILABLE = True
except ImportError:
    MODELSCOPE_AVAILABLE = False
    logger.info("address_tagging_model: modelscope 不可用，将使用 transformers 加载模型")

try:
    from transformers import AutoTokenizer as HF_AutoTokenizer, AutoModelForTokenClassification as HF_AutoModelForTokenCls
    TRANSFORMERS_AVAILABLE = True
except ImportError:
    TRANSFORMERS_AVAILABLE = False
    logger.warning("address_tagging_model: transformers 不可用，模型加载选项受限")


class AddressTaggingModel:
    """
    MGeo门址地址结构化要素解析模型

    使用阿里MGeo地址要素解析模型对地址文本进行NER分词，
    并将BIO标签解析为12级结构化输出。

    Attributes:
        model_name: 模型名称
        device: 运行设备 ('cuda' 或 'cpu')
        tokenizer: 分词器
        model: token分类模型
        use_fp16: 是否使用半精度推理
        id2label: 标签ID到标签名的映射
    """

    def __init__(self, model_name=None, device=None):
        self.model_name = model_name or TAGGING_MODEL_NAME
        self.device = device or Config.DEVICE
        self.tokenizer = None
        self.model = None
        self.use_fp16 = False
        self.id2label = {}
        self._load_model()

    def _load_model(self):
        """
        加载MGeo地址要素解析模型和分词器

        加载策略（按优先级依次尝试）：
            1. 使用 modelscope 从本地路径加载
            2. 使用 transformers 从本地路径加载
            3. 使用 modelscope 从模型名称在线下载
            4. 使用 transformers 从模型名称在线下载
        """
        try:
            local_path = _find_model_local_path(self.model_name)

            if self.device == 'cuda' and not torch.cuda.is_available():
                logger.warning("CUDA not available, falling back to CPU")
                self.device = 'cpu'

            loaded = False

            if local_path and os.path.isdir(local_path):
                logger.info(f"找到本地地址要素解析模型路径: {local_path}")
                loaded = self._try_load_from_local(local_path)

            if not loaded:
                logger.info("本地路径加载失败，尝试从模型名称在线下载...")
                loaded = self._try_load_from_model_name()

            if not loaded:
                raise RuntimeError(
                    f"无法加载地址要素解析模型 {self.model_name}\n"
                    f"已尝试：\n"
                    f"  1. 本地路径加载\n"
                    f"  2. 在线下载（modelscope / transformers）\n"
                    f"请确保模型文件已放置在项目目录的 models/ 文件夹下"
                )

            self._fix_checkpoint_key_mapping()

            if self.device == 'cuda':
                self.model.half()
                self.use_fp16 = True
                logger.info("地址要素解析模型 FP16 half-precision inference enabled on GPU")

            self.model.eval()

            self.id2label = {}
            if hasattr(self.model.config, 'id2label'):
                for idx_str, label_name in self.model.config.id2label.items():
                    self.id2label[int(idx_str)] = label_name

            if not self.id2label or all(k.startswith('LABEL_') for k in self.id2label.values()):
                logger.info("模型config中id2label为空或为默认LABEL格式，尝试从configuration.json读取")
                self._load_id2label_from_configuration(local_path)

            logger.info(f"地址要素解析模型加载成功, id2label数量={len(self.id2label)}, "
                       f"device={self.device}, fp16={self.use_fp16}")
        except Exception as e:
            logger.error(f"加载地址要素解析模型失败: {str(e)}")
            raise

    def _load_id2label_from_configuration(self, model_path):
        """从 configuration.json 加载 id2label 映射"""
        import json
        config_path = os.path.join(model_path, 'configuration.json')
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    model_config = config.get('model', {})
                    id2label = model_config.get('id2label', {})
                    if id2label:
                        self.id2label = {int(k): v for k, v in id2label.items()}
                        logger.info(f"从configuration.json成功加载id2label: {len(self.id2label)}个标签")
            except Exception as e:
                logger.warning(f"从configuration.json加载id2label失败: {str(e)}")

    def _get_num_labels_from_config(self, local_path):
        """从 configuration.json 读取 num_labels"""
        import json
        config_path = os.path.join(local_path, 'configuration.json')
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    return config.get('model', {}).get('num_labels', 57)
            except Exception as e:
                logger.warning(f"读取 configuration.json 失败: {str(e)}")
        return 57

    def _try_load_from_local(self, local_path):
        num_labels = self._get_num_labels_from_config(local_path)
        
        if MODELSCOPE_AVAILABLE:
            try:
                logger.info(f"使用 modelscope 从本地加载地址要素解析模型: {local_path}")
                self.tokenizer = MS_AutoTokenizer.from_pretrained(local_path, local_files_only=True)
                self.model = MS_AutoModelForTokenCls.from_pretrained(
                    local_path, local_files_only=True, num_labels=num_labels
                ).to(self.device)
                logger.info("modelscope 本地加载地址要素解析模型成功")
                return True
            except Exception as e:
                logger.warning(f"modelscope 本地加载地址要素解析模型失败: {str(e)}")

        if TRANSFORMERS_AVAILABLE:
            try:
                logger.info(f"使用 transformers 从本地加载地址要素解析模型: {local_path}")
                self.tokenizer = HF_AutoTokenizer.from_pretrained(local_path, local_files_only=True, trust_remote_code=True)
                self.model = HF_AutoModelForTokenCls.from_pretrained(
                    local_path, local_files_only=True, trust_remote_code=True, num_labels=num_labels
                ).to(self.device)
                logger.info("transformers 本地加载地址要素解析模型成功")
                return True
            except Exception as e:
                logger.warning(f"transformers 本地加载地址要素解析模型失败: {str(e)}")

        return False

    def _try_load_from_model_name(self):
        if MODELSCOPE_AVAILABLE:
            try:
                logger.info(f"使用 modelscope 在线下载地址要素解析模型: {self.model_name}")
                self.tokenizer = MS_AutoTokenizer.from_pretrained(self.model_name)
                self.model = MS_AutoModelForTokenCls.from_pretrained(
                    self.model_name, ignore_mismatched_sizes=True
                ).to(self.device)
                logger.info("modelscope 在线加载地址要素解析模型成功")
                return True
            except Exception as e:
                logger.warning(f"modelscope 在线加载地址要素解析模型失败: {str(e)}")

        if TRANSFORMERS_AVAILABLE:
            try:
                logger.info(f"使用 transformers 在线下载地址要素解析模型: {self.model_name}")
                self.tokenizer = HF_AutoTokenizer.from_pretrained(self.model_name, trust_remote_code=True)
                self.model = HF_AutoModelForTokenCls.from_pretrained(
                    self.model_name, trust_remote_code=True, ignore_mismatched_sizes=True
                ).to(self.device)
                logger.info("transformers 在线加载地址要素解析模型成功")
                return True
            except Exception as e:
                logger.warning(f"transformers 在线加载地址要素解析模型失败: {str(e)}")

        return False

    def _fix_checkpoint_key_mapping(self):
        """
        修复checkpoint键名映射问题

        ModelScope原始checkpoint中BERT编码器键名使用 bert.text_encoder.* 前缀，
        但HuggingFace BERT模型期望 bert.* 前缀。此方法检测并修复键名不匹配问题。
        """
        import os
        model_path = None
        if hasattr(self.model, 'name_or_path') and self.model.name_or_path:
            model_path = self.model.name_or_path

        if not model_path:
            model_path = _find_model_local_path(self.model_name)

        if not model_path or not os.path.isdir(model_path):
            logger.info("[地址要素解析] 无法确定模型路径，跳过checkpoint键名映射检查")
            return

        ckpt_path = os.path.join(model_path, 'pytorch_model.bin')
        if not os.path.exists(ckpt_path):
            ckpt_path_safetensors = os.path.join(model_path, 'model.safetensors')
            if not os.path.exists(ckpt_path_safetensors):
                logger.info("[地址要素解析] 未找到 pytorch_model.bin 或 model.safetensors，跳过键名映射检查")
                return
            ckpt_path = ckpt_path_safetensors

        if ckpt_path.endswith('.safetensors'):
            try:
                from safetensors.torch import load_file
                checkpoint = load_file(ckpt_path)
            except ImportError:
                logger.warning("[地址要素解析] safetensors 库不可用，无法检查 .safetensors 格式的checkpoint")
                return
        else:
            checkpoint = torch.load(ckpt_path, map_location=self.device, weights_only=False)

        ckpt_keys = set(checkpoint.keys())
        text_encoder_keys = [k for k in ckpt_keys if k.startswith('bert.text_encoder.')]
        if not text_encoder_keys:
            logger.info("[地址要素解析] checkpoint中未找到 bert.text_encoder.* 键名，键名映射OK")
            return

        logger.warning(f"[地址要素解析] 发现 {len(text_encoder_keys)} 个 bert.text_encoder.* 前缀键名，应用键名映射...")

        new_checkpoint = {}
        renamed = 0
        for key in checkpoint.keys():
            new_key = key.replace('bert.text_encoder.', 'bert.')
            new_checkpoint[new_key] = checkpoint[key]
            if new_key != key:
                renamed += 1

        missing, unexpected = self.model.load_state_dict(new_checkpoint, strict=False)

        if missing:
            logger.warning(f"[地址要素解析] 键名映射后仍缺失的键: {len(missing)}个")
        if unexpected:
            logger.warning(f"[地址要素解析] 键名映射后多余的键: {len(unexpected)}个")

        logger.info(f"[地址要素解析] 键名映射完成: {renamed}个键从 bert.text_encoder.* 重命名为 bert.*")

    def _get_default_batch_size(self):
        if self.device == 'cuda':
            return 128
        return 64

    def _parse_bio_tags(self, tokens, label_ids):
        """
        解析BIO标签序列，提取命名实体（保持顺序）

        BIO标注规则：
            B-xxx: 实体开始
            I-xxx: 实体内部
            E-xxx: 实体结束
            S-xxx: 单字实体
            O: 非实体

        Args:
            tokens: 分词后的token列表
            label_ids: 对应的标签ID列表

        Returns:
            list of (tag, text): 按地址中出现顺序排列的NER实体列表
        """
        entities = []
        current_entity_type = None
        current_entity_tokens = []

        def _flush():
            nonlocal current_entity_type, current_entity_tokens
            if current_entity_type and current_entity_tokens:
                entity_text = ''.join(current_entity_tokens)
                entities.append((current_entity_type, entity_text))
                current_entity_type = None
                current_entity_tokens = []

        for token, label_id in zip(tokens, label_ids):
            label = self.id2label.get(label_id, 'O')

            if label == 'O':
                _flush()
                continue

            if label.startswith('B-') or label.startswith('S-'):
                _flush()
                entity_type = label[2:]
                current_entity_type = entity_type
                current_entity_tokens = [token]

                if label.startswith('S-'):
                    _flush()

            elif label.startswith('I-') or label.startswith('E-'):
                entity_type = label[2:]
                if current_entity_type == entity_type:
                    current_entity_tokens.append(token)
                else:
                    _flush()
                    current_entity_type = entity_type
                    current_entity_tokens = [token]

                if label.startswith('E-'):
                    _flush()
            else:
                _flush()

        _flush()
        return entities

    # 建筑标识符后缀
    _BLDG_SUFFIXES = ('栋', '幢', '座', '号楼', '栋楼', '号楼栋')
    # 户室标识符后缀
    _HOUSE_SUFFIXES = ('室', '房', '号房')
    # 片区/小区名称常见后缀（用于判断 subpoi 是否实际为 area）
    _AREA_SUFFIXES = ('花园', '花苑', '家园', '小区', '公寓', '大厦', '中心',
                      '商城', '广场', '市场', '商城', '商场', '鑫苑', '名苑',
                      '绿洲', '雅苑', '华庭', '豪庭', '名庭', '嘉园', '华府')

    @staticmethod
    def _find_in_address(address, text, start=0):
        """在地址中查找文本，返回位置，找不到返回 -1"""
        pos = address.find(text, start)
        return pos

    def _is_bldg_entity(self, text):
        """判断实体文本是否为建筑物名/楼栋"""
        return any(text.endswith(s) for s in self._BLDG_SUFFIXES)

    def _is_house_entity(self, text):
        """判断实体文本是否为户室号/房间"""
        return any(text.endswith(s) for s in self._HOUSE_SUFFIXES)

    def _post_process_entities(self, entity_list, original_address):
        """
        对NER实体列表进行后处理修正

        修正规则：
        1. houseno 以建筑标识符结尾 → subpoi（bldg）
        2. subpoi 以片区/小区名称后缀结尾 → poi（area）
        3. subpoi 以户室标识符结尾且非建筑标识符 → houseno
        4. 孤立的短数字/字母 subpoi/bldg → 合并到 houseno
        5. 提取地址末尾未标记的内容作为 houseno
        6. 从 houseno 中提取隐含的楼层号
        7. floorno "首" → "首层"

        Args:
            entity_list: [(ner_tag, text), ...] 有序实体列表
            original_address: 原始地址文本

        Returns:
            list of (ner_tag, text): 修正后的有序实体列表
        """
        import re

        fixed = []

        for ner_tag, text in entity_list:
            new_tag = ner_tag

            if ner_tag == 'houseno':
                if self._is_bldg_entity(text):
                    new_tag = 'subpoi'

            elif ner_tag == 'subpoi':
                if self._is_house_entity(text) and not self._is_bldg_entity(text):
                    new_tag = 'houseno'
                elif any(text.endswith(s) for s in self._AREA_SUFFIXES):
                    new_tag = 'poi'

            fixed.append((new_tag, text))

        # ---- Step A: 孤立的短数字/字母 subpoi/bldg → 合并到 houseno ----
        # 如果 bldg 是短数字或字母组合（如 "8", "60", "s40"），且不是真正建筑，转为 houseno
        for i, (ner_tag, text) in enumerate(fixed):
            if ner_tag == 'subpoi':
                # 纯数字（1-3位）或 字母+数字 组合且不包含建筑后缀
                is_orphan = (re.match(r'^[a-zA-Z]?\d{1,3}$', text)
                          and not self._is_bldg_entity(text)
                          and not self._is_house_entity(text))
                if is_orphan:
                    # 转为 houseno
                    fixed[i] = ('houseno', text)

        # ---- Step B: 将连续的 houseno 合并 ----
        merged = []
        for ner_tag, text in fixed:
            if ner_tag == 'houseno' and merged and merged[-1][0] == 'houseno':
                merged[-1] = ('houseno', merged[-1][1] + text)
            else:
                merged.append((ner_tag, text))
        fixed = merged

        # ---- Step C: 提取地址末尾未标记的内容作为 houseno ----
        last_end = 0
        for ner_tag, text in fixed:
            pos = self._find_in_address(original_address, text, last_end)
            if pos != -1:
                last_end = max(last_end, pos + len(text))

        if last_end < len(original_address):
            tail = original_address[last_end:].strip()
            # 匹配尾部内容（数字、字母+数字、或数字+室/号/房）
            tail_match = re.search(r'([a-zA-Z]?\s*\d{2,4}\s*(室|房|号)?)\s*$', tail)
            if not tail_match:
                # 备选: 数字+常见后缀
                tail_match = re.search(r'(\d{1,4}\s*(室|房|号|铺))\s*$', tail)
            if not tail_match:
                # 备选: 纯数字
                tail_match = re.search(r'(\d{2,4})\s*$', tail)
            if tail_match:
                house_text = tail_match.group(0).strip()
                has_house = any(t == 'houseno' for t, _ in fixed)
                if not has_house:
                    fixed.append(('houseno', house_text))
                else:
                    for i, (t, txt) in enumerate(fixed):
                        if t == 'houseno':
                            fixed[i] = (t, txt + house_text)
                            break

        # ---- Step D: 从 houseno 中提取隐含的楼层号 ----
        for i, (ner_tag, text) in enumerate(fixed):
            if ner_tag == 'houseno':
                has_floorno = any(t == 'floorno' for t, _ in fixed)
                if not has_floorno:
                    num_match = re.match(r'^(\d{3,4})', text)
                    if num_match:
                        num_str = num_match.group(1)
                        floor_num = num_str[0] if len(num_str) == 3 else num_str[:2]
                        fixed.insert(i + 1, ('floorno', floor_num))

        # ---- Step E: floorno 展开 "首" → "首层" ----
        for i, (ner_tag, text) in enumerate(fixed):
            if ner_tag == 'floorno' and text.strip() == '首':
                fixed[i] = ('floorno', '首层')

        # ---- Step F: 边界扩展 - 用原始地址修正实体边界 ----
        fixed = self._expand_entity_boundaries(fixed, original_address)

        return fixed

    def _expand_entity_boundaries(self, entity_list, original_address):
        """
        利用原始地址文本扩展实体边界，吸收相邻的未标记数字/字母

        场景：
        1. houseno "8" → 前向吸收 "140" → "1408"
        2. houseno "室" → 前向吸收 "B" → "B室"
        3. roadno "号" → 前向吸收 "S40" → "S40号"
        """
        import re

        # 计算每个实体在地址中的大致位置
        entity_positions = []
        search_start = 0
        for ner_tag, text in entity_list:
            pos = self._find_in_address(original_address, text, search_start)
            if pos >= 0:
                entity_positions.append((pos, pos + len(text), ner_tag, text))
                search_start = pos + len(text)
            else:
                entity_positions.append((search_start, search_start, ner_tag, text))

        if not entity_positions:
            return entity_list

        # 收集实体间的未标记区域
        expanded = []
        addr_len = len(original_address)

        for idx, (start, end, ner_tag, text) in enumerate(entity_positions):
            # 检查与前一个实体的间隙
            if idx == 0 and start > 0:
                # 地址开头有未标记内容
                gap = original_address[0:start]
            elif idx > 0:
                prev_end = entity_positions[idx - 1][1]
                gap = original_address[prev_end:start] if start > prev_end else ''

            # 对 houseno 实体，尝试向前吸收数字/字母
            if ner_tag == 'houseno' and idx > 0 and start > entity_positions[idx - 1][1]:
                prev_end = entity_positions[idx - 1][1]
                gap = original_address[prev_end:start]
                # 如果 gap 包含数字或字母，吸收到 houseno
                gap_clean = gap.strip()
                if gap_clean and re.match(r'^[a-zA-Z0-9]+$', gap_clean):
                    text = gap_clean + text
                    start = prev_end

            # 对 roadno 实体，如果只是 "号"，向前吸收数字
            if ner_tag == 'roadno' and re.match(r'^号$', text) and idx > 0:
                prev_end = entity_positions[idx - 1][1]
                gap = original_address[prev_end:start] if start > prev_end else ''
                gap_clean = gap.strip()
                if gap_clean and re.match(r'^[a-zA-Z0-9]+$', gap_clean):
                    text = gap_clean + text

            expanded.append((ner_tag, text))

        # 检查尾部未标记区域
        last_end = entity_positions[-1][1] if entity_positions else 0
        if last_end < addr_len:
            tail = original_address[last_end:].strip()
            if tail:
                # 尝试匹配尾部内容到最后一个实体或添加新实体
                last_tag, last_text = expanded[-1]
                if last_tag == 'houseno':
                    # 尾部数字追加到 houseno
                    tail_match = re.search(r'^([a-zA-Z]?\s*\d{1,4}\s*(室|房|号|铺)?)', tail)
                    if tail_match:
                        expanded[-1] = (last_tag, last_text + tail_match.group(0).strip())
                elif re.match(r'^[a-zA-Z]?\s*\d{2,4}\s*(室|房|号)?\s*$', tail):
                    expanded.append(('houseno', tail.strip()))

        return expanded

    def _ner_to_structured(self, entity_list):
        """
        将NER实体列表映射为12级结构化输出

        Args:
            entity_list: [(ner_tag, text), ...] 有序实体列表

        Returns:
            dict: 12级结构化输出
        """
        result = {field: '' for field in OUTPUT_FIELDS}

        for ner_tag, text in entity_list:
            output_field = NER_TO_OUTPUT_MAP.get(ner_tag)
            if output_field:
                if result[output_field]:
                    result[output_field] += text
                else:
                    result[output_field] = text

        return result

    def _ner_to_structured_17(self, entity_list):
        """
        将NER实体列表直接映射为17级结构化输出（不做合并映射，保留原始标签）

        与12级版本的区别：
        - 每个NER标签直接作为输出字段（1:1映射）
        - 相同类型多个实体时拼接值
        - 不做 post-processing 修正

        Args:
            entity_list: [(ner_tag, text), ...] 有序实体列表

        Returns:
            dict: 17级结构化输出
        """
        result = {field: '' for field in OUTPUT_FIELDS_17}

        for ner_tag, text in entity_list:
            if ner_tag in result:
                if result[ner_tag]:
                    result[ner_tag] += text
                else:
                    result[ner_tag] = text

        return result

    def _ner_to_structured_17_2(self, entity_list):
        """
        将NER实体列表映射为17级双字段结构化输出

        规则：
        - 第一个匹配值写入主字段（如 poi）
        - 第二个及后续同类型值拼接到 _2 后缀字段（如 poi_2）
        - 不做 post-processing 修正

        Args:
            entity_list: [(ner_tag, text), ...] 有序实体列表

        Returns:
            dict: 17级双字段结构化输出（34个字段）
        """
        result = {field: '' for field in OUTPUT_FIELDS_17_2}

        for ner_tag, text in entity_list:
            if ner_tag not in OUTPUT_FIELDS_17:
                continue
            if not result[ner_tag]:
                result[ner_tag] = text
            else:
                field_2 = f'{ner_tag}_2'
                if result[field_2]:
                    result[field_2] += text
                else:
                    result[field_2] = text

        return result

    def _build_dom_json(self, entity_list):
        """
        构建解析后的实体JSON字符串

        将NER解析后的实体列表序列化为JSON数组，
        每个元素为 [NER标签, 实体文本] 对。

        Args:
            entity_list: [(ner_tag, text), ...] 有序实体列表

        Returns:
            str: JSON字符串，格式如 [["prov","广东省"],["city","深圳市"],...]
        """
        import json
        return json.dumps(entity_list, ensure_ascii=False)

    def predict(self, addresses, batch_size=None):
        """
        批量预测地址的结构化要素（12级输出）

        Args:
            addresses: 地址文本列表
            batch_size: 批处理大小，默认GPU=128, CPU=64

        Returns:
            list: 结构化解析结果列表，每个元素包含原始地址和12级结构化字段
        """
        if not addresses:
            return []

        batch_size = batch_size or self._get_default_batch_size()
        results = [None] * len(addresses)

        valid_indices = []
        valid_addresses = []
        for idx, addr in enumerate(addresses):
            if addr and addr.strip():
                valid_indices.append(idx)
                valid_addresses.append(addr.strip())
            else:
                results[idx] = {'original_address': addr, **{field: '' for field in OUTPUT_FIELDS}}

        if not valid_addresses:
            return results

        for i in range(0, len(valid_addresses), batch_size):
            batch_addrs = valid_addresses[i:i + batch_size]
            batch_indices = valid_indices[i:i + batch_size]

            try:
                inputs = self.tokenizer(
                    batch_addrs,
                    padding='longest',
                    truncation=True,
                    max_length=128,
                    return_tensors='pt'
                ).to(self.device)

                with torch.inference_mode():
                    outputs = self.model(**inputs)
                    logits = outputs.logits
                    if self.use_fp16:
                        logits = logits.float()
                    predictions = torch.argmax(logits, dim=2)

                pred_ids = predictions.cpu().numpy()

                for j, (addr, result_idx) in enumerate(zip(batch_addrs, batch_indices)):
                    input_ids = inputs['input_ids'][j].cpu().numpy()
                    tokens = self.tokenizer.convert_ids_to_tokens(input_ids)

                    attention_mask = inputs['attention_mask'][j].cpu().numpy()
                    active_tokens = []
                    active_labels = []
                    for k, mask_val in enumerate(attention_mask):
                        if mask_val == 1 and tokens[k] not in ('[CLS]', '[SEP]', '<s>', '</s>'):
                            active_tokens.append(tokens[k].lstrip('#').lstrip('Ġ'))
                            active_labels.append(int(pred_ids[j][k]))

                    entity_list = self._parse_bio_tags(active_tokens, active_labels)
                    entity_list = self._post_process_entities(entity_list, addr)
                    structured = self._ner_to_structured(entity_list)
                    results[result_idx] = {'original_address': addr, **structured}

            except Exception as e:
                logger.error(f"地址要素解析批量预测错误 batch {i // batch_size}: {str(e)}")
                for result_idx in batch_indices:
                    results[result_idx] = {
                        'original_address': addresses[result_idx],
                        **{field: '' for field in OUTPUT_FIELDS}
                    }

        return results

    def predict_17(self, addresses, batch_size=None):
        """
        批量预测地址的17级结构化要素（MGeo模型原始输出）

        与 predict() 的区别：
        - 输出17个原始NER标签字段，不做标签合并映射
        - 跳过 post_process_entities 和 expand_entity_boundaries
        - 相同类型的多个实体直接拼接

        Args:
            addresses: 地址文本列表
            batch_size: 批处理大小，默认GPU=128, CPU=64

        Returns:
            list: 结构化解析结果列表，每个元素包含原始地址和17级结构化字段
        """
        if not addresses:
            return []

        batch_size = batch_size or self._get_default_batch_size()
        results = [None] * len(addresses)

        valid_indices = []
        valid_addresses = []
        for idx, addr in enumerate(addresses):
            if addr and addr.strip():
                valid_indices.append(idx)
                valid_addresses.append(addr.strip())
            else:
                results[idx] = {
                    'original_address': addr, 'dom_json': '[]',
                    **{field: '' for field in OUTPUT_FIELDS_17}
                }

        if not valid_addresses:
            return results

        for i in range(0, len(valid_addresses), batch_size):
            batch_addrs = valid_addresses[i:i + batch_size]
            batch_indices = valid_indices[i:i + batch_size]

            try:
                inputs = self.tokenizer(
                    batch_addrs,
                    padding='longest',
                    truncation=True,
                    max_length=128,
                    return_tensors='pt'
                ).to(self.device)

                with torch.inference_mode():
                    outputs = self.model(**inputs)
                    logits = outputs.logits
                    if self.use_fp16:
                        logits = logits.float()
                    predictions = torch.argmax(logits, dim=2)

                pred_ids = predictions.cpu().numpy()

                for j, (addr, result_idx) in enumerate(zip(batch_addrs, batch_indices)):
                    input_ids = inputs['input_ids'][j].cpu().numpy()
                    tokens = self.tokenizer.convert_ids_to_tokens(input_ids)

                    attention_mask = inputs['attention_mask'][j].cpu().numpy()
                    active_tokens = []
                    active_labels = []
                    for k, mask_val in enumerate(attention_mask):
                        if mask_val == 1 and tokens[k] not in ('[CLS]', '[SEP]', '<s>', '</s>'):
                            active_tokens.append(tokens[k].lstrip('#').lstrip('Ġ'))
                            active_labels.append(int(pred_ids[j][k]))

                    entity_list = self._parse_bio_tags(active_tokens, active_labels)
                    structured = self._ner_to_structured_17(entity_list)
                    dom_json = self._build_dom_json(entity_list)
                    results[result_idx] = {
                        'original_address': addr, 'dom_json': dom_json, **structured
                    }

            except Exception as e:
                logger.error(f"地址要素解析(17级)批量预测错误 batch {i // batch_size}: {str(e)}")
                for result_idx in batch_indices:
                    results[result_idx] = {
                        'original_address': addresses[result_idx], 'dom_json': '[]',
                        **{field: '' for field in OUTPUT_FIELDS_17}
                    }

        return results

    def predict_17_2(self, addresses, batch_size=None):
        """
        批量预测地址的17级双字段结构化要素

        与 predict_17 的区别：
        - 每个NER标签对应2个字段（主字段 + _2后缀字段）
        - 第一个匹配值写入主字段，后续同类型值拼接到 _2 字段
        - 返回 dom_json：原始NER解析结果的JSON字符串

        Args:
            addresses: 地址文本列表
            batch_size: 批处理大小

        Returns:
            list: 每个元素包含 original_address、dom_json 和 34 个双字段
        """
        if not addresses:
            return []

        batch_size = batch_size or self._get_default_batch_size()
        results = [None] * len(addresses)

        valid_indices = []
        valid_addresses = []
        for idx, addr in enumerate(addresses):
            if addr and addr.strip():
                valid_indices.append(idx)
                valid_addresses.append(addr.strip())
            else:
                results[idx] = {
                    'original_address': addr, 'dom_json': '[]',
                    **{field: '' for field in OUTPUT_FIELDS_17_2}
                }

        if not valid_addresses:
            return results

        for i in range(0, len(valid_addresses), batch_size):
            batch_addrs = valid_addresses[i:i + batch_size]
            batch_indices = valid_indices[i:i + batch_size]

            try:
                inputs = self.tokenizer(
                    batch_addrs, padding='longest', truncation=True,
                    max_length=128, return_tensors='pt'
                ).to(self.device)

                with torch.inference_mode():
                    outputs = self.model(**inputs)
                    logits = outputs.logits
                    if self.use_fp16:
                        logits = logits.float()
                    predictions = torch.argmax(logits, dim=2)

                pred_ids = predictions.cpu().numpy()

                for j, (addr, result_idx) in enumerate(zip(batch_addrs, batch_indices)):
                    input_ids = inputs['input_ids'][j].cpu().numpy()
                    tokens = self.tokenizer.convert_ids_to_tokens(input_ids)

                    attention_mask = inputs['attention_mask'][j].cpu().numpy()
                    active_tokens = []
                    active_labels = []
                    for k, mask_val in enumerate(attention_mask):
                        if mask_val == 1 and tokens[k] not in ('[CLS]', '[SEP]', '<s>', '</s>'):
                            active_tokens.append(tokens[k].lstrip('#').lstrip('Ġ'))
                            active_labels.append(int(pred_ids[j][k]))

                    entity_list = self._parse_bio_tags(active_tokens, active_labels)
                    structured = self._ner_to_structured_17_2(entity_list)
                    dom_json = self._build_dom_json(entity_list)
                    results[result_idx] = {
                        'original_address': addr, 'dom_json': dom_json, **structured
                    }

            except Exception as e:
                logger.error(f"地址要素解析(17_2)批量预测错误 batch {i // batch_size}: {str(e)}")
                for result_idx in batch_indices:
                    results[result_idx] = {
                        'original_address': addresses[result_idx], 'dom_json': '[]',
                        **{field: '' for field in OUTPUT_FIELDS_17_2}
                    }

        return results
