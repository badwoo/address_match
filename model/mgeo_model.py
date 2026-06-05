"""
MGeo地址相似度匹配模型模块
============================

本模块封装阿里 MGeo 地址相似度匹配实体对齐模型，用于精排阶段的地址匹配。

模型信息：
    - 模型名称: iic/mgeo_geographic_entity_alignment_chinese_base
    - 任务类型: 地址实体对齐（三分类）
    - 适用场景: 判断两个地址是否匹配

核心功能：
    1. 加载 MGeo 精排模型
    2. 预测地址对的匹配概率
    3. 支持批量预测

技术要点：
    1. 优先使用 modelscope 从本地路径加载模型（ModelScope 模型原生支持）
    2. 回退使用 transformers 从本地路径加载模型（需 trust_remote_code=True）
    3. 本地加载失败时，尝试从模型名称在线下载
    4. 模型返回三个标签的概率: not_match(索引0)、partial_match(索引1)、exact_match(索引2)
    5. checkpoint中BERT编码器键名需从 bert.text_encoder.* 映射为 bert.*，
       否则HuggingFace无法正确加载权重
    6. 多路径搜索：项目目录 > modelscope缓存 > huggingface缓存 > 在线下载

性能优化：
    1. padding='longest' - 按batch内最长序列padding，避免大量无效计算
    2. GPU半精度(FP16)推理 - GPU上自动启用，推理速度提升约2倍
    3. 增大批处理默认值 - GPU上默认128，CPU上默认64
    4. 精简结果字典 - 仅保留精排所需字段，减少内存和GC开销
    5. 批量numpy操作 - 减少逐元素Python循环
"""

import torch
import numpy as np
import os
from config import Config, _find_model_local_path
from utils.logger import logger

try:
    from modelscope import AutoTokenizer as MS_AutoTokenizer, AutoModelForSequenceClassification as MS_AutoModelForSeqCls
    MODELSCOPE_AVAILABLE = True
except ImportError:
    MODELSCOPE_AVAILABLE = False
    logger.info("mgeo_model: modelscope 不可用，将使用 transformers 加载模型")

try:
    from transformers import AutoTokenizer as HF_AutoTokenizer, AutoModelForSequenceClassification as HF_AutoModelForSeqCls
    TRANSFORMERS_AVAILABLE = True
except ImportError:
    TRANSFORMERS_AVAILABLE = False
    logger.warning("mgeo_model: transformers 不可用，模型加载选项受限")


class MGeoModel:
    """
    MGeo地址相似度匹配模型

    使用阿里MGeo实体对齐模型进行地址匹配精排。

    Attributes:
        model_name: 模型名称
        revision: 模型版本
        device: 运行设备 ('cuda' 或 'cpu')
        tokenizer: 分词器
        model: 序列分类模型
        use_fp16: 是否使用半精度推理
    """

    def __init__(self, model_name=None, revision=None, device=None):
        """
        初始化MGeo模型

        Args:
            model_name: 模型名称，默认使用 Config.MODEL_NAME
            revision: 模型版本，默认使用 Config.MODEL_REVISION
            device: 运行设备，默认使用 Config.DEVICE
        """
        self.model_name = model_name or Config.MODEL_NAME
        self.revision = revision or Config.MODEL_REVISION
        self.device = device or Config.DEVICE
        self.tokenizer = None
        self.model = None
        self.use_fp16 = False
        self._load_model()

    def _load_model(self):
        """
        加载MGeo模型和分词器

        加载策略（按优先级依次尝试）：
            1. 使用 modelscope 从本地路径加载（推荐，ModelScope 模型原生支持）
            2. 使用 transformers 从本地路径加载（需 trust_remote_code=True）
            3. 使用 modelscope 从模型名称在线下载
            4. 使用 transformers 从模型名称在线下载

        本地路径搜索顺序：
            1. Config.LOCAL_MODEL_PATH（自动搜索的项目目录/缓存目录）
            2. _find_model_local_path() 重新搜索

        性能优化：
            - GPU上自动启用FP16半精度推理，提升推理速度约2倍
            - 使用torch.inference_mode()替代torch.no_grad()，进一步减少开销

        重要说明：
            1. ModelScope原始checkpoint中BERT编码器键名使用 bert.text_encoder.* 前缀，
               但HuggingFace BERT模型期望 bert.* 前缀。加载时需进行键名映射，
               否则BERT编码器权重不会被加载，导致模型输出随机结果。

            2. 模型训练时标签顺序为 ['not_match', 'partial_match', 'exact_match']，
               对应输出索引 0=not_match, 1=partial_match, 2=exact_match。
               config.json中id2label必须与此一致。

            3. 不要使用ignore_mismatched_sizes=True参数，否则会导致分类头权重被随机初始化。
        """
        try:
            local_path = Config.LOCAL_MODEL_PATH

            if not local_path or not os.path.isdir(local_path):
                logger.warning(f"Config.LOCAL_MODEL_PATH 未找到有效路径: {local_path}，重新搜索...")
                local_path = _find_model_local_path(self.model_name)

            if self.device == 'cuda' and not torch.cuda.is_available():
                logger.warning("CUDA not available, falling back to CPU")
                self.device = 'cpu'

            loaded = False

            if local_path and os.path.isdir(local_path):
                logger.info(f"找到本地模型路径: {local_path}")
                loaded = self._try_load_from_local(local_path)

            if not loaded:
                logger.info("本地路径加载失败，尝试从模型名称在线下载...")
                loaded = self._try_load_from_model_name()

            if not loaded:
                raise RuntimeError(
                    f"无法加载MGeo模型 {self.model_name}\n"
                    f"已尝试：\n"
                    f"  1. 本地路径加载（路径: {local_path}）\n"
                    f"  2. 在线下载（modelscope / transformers）\n"
                    f"请确保：\n"
                    f"  - 模型文件已放置在项目目录的 models/ 文件夹下\n"
                    f"  - 或模型已下载到 ~/.cache/modelscope/ 缓存目录\n"
                    f"  - 或网络可以访问 ModelScope/HuggingFace"
                )

            self._fix_checkpoint_key_mapping()

            if self.device == 'cuda':
                self.model.half()
                self.use_fp16 = True
                logger.info("FP16 half-precision inference enabled on GPU")

            self.model.eval()

            actual_num_labels = self.model.config.num_labels
            actual_id2label = getattr(self.model.config, 'id2label', None)

            if actual_num_labels != 3:
                logger.error(f"MGeo model num_labels={actual_num_labels}, expected 3!")
                raise ValueError(f"Model num_labels={actual_num_labels}, expected 3")

            self.label_map = {}
            for idx_str, label_name in actual_id2label.items():
                self.label_map[int(idx_str)] = label_name

            logger.info(f"MGeo model loaded successfully, num_labels={actual_num_labels}, "
                       f"id2label={actual_id2label}, label_map={self.label_map}, "
                       f"device={self.device}, fp16={self.use_fp16}")
        except Exception as e:
            logger.error(f"Failed to load MGeo model: {str(e)}")
            raise

    def _try_load_from_local(self, local_path):
        """
        尝试从本地路径加载模型

        依次尝试 modelscope 和 transformers 两种加载方式

        Args:
            local_path: 本地模型目录路径

        Returns:
            bool: 加载成功返回 True
        """
        if MODELSCOPE_AVAILABLE:
            try:
                logger.info(f"使用 modelscope 从本地加载MGeo模型: {local_path}")
                self.tokenizer = MS_AutoTokenizer.from_pretrained(local_path, local_files_only=True)
                self.model = MS_AutoModelForSeqCls.from_pretrained(local_path, local_files_only=True).to(self.device)
                logger.info("modelscope 本地加载MGeo模型成功")
                return True
            except Exception as e:
                logger.warning(f"modelscope 本地加载MGeo模型失败: {str(e)}")

        if TRANSFORMERS_AVAILABLE:
            try:
                logger.info(f"使用 transformers 从本地加载MGeo模型: {local_path}")
                self.tokenizer = HF_AutoTokenizer.from_pretrained(local_path, local_files_only=True, trust_remote_code=True)
                self.model = HF_AutoModelForSeqCls.from_pretrained(local_path, local_files_only=True, trust_remote_code=True).to(self.device)
                logger.info("transformers 本地加载MGeo模型成功")
                return True
            except Exception as e:
                logger.warning(f"transformers 本地加载MGeo模型失败: {str(e)}")

        return False

    def _try_load_from_model_name(self):
        """
        尝试从模型名称在线下载并加载

        依次尝试 modelscope 和 transformers 两种加载方式

        Returns:
            bool: 加载成功返回 True
        """
        if MODELSCOPE_AVAILABLE:
            try:
                logger.info(f"使用 modelscope 在线下载MGeo模型: {self.model_name}")
                self.tokenizer = MS_AutoTokenizer.from_pretrained(self.model_name)
                self.model = MS_AutoModelForSeqCls.from_pretrained(self.model_name).to(self.device)
                logger.info("modelscope 在线加载MGeo模型成功")
                return True
            except Exception as e:
                logger.warning(f"modelscope 在线加载MGeo模型失败: {str(e)}")

        if TRANSFORMERS_AVAILABLE:
            try:
                logger.info(f"使用 transformers 在线下载MGeo模型: {self.model_name}")
                self.tokenizer = HF_AutoTokenizer.from_pretrained(self.model_name, trust_remote_code=True)
                self.model = HF_AutoModelForSeqCls.from_pretrained(self.model_name, trust_remote_code=True).to(self.device)
                logger.info("transformers 在线加载MGeo模型成功")
                return True
            except Exception as e:
                logger.warning(f"transformers 在线加载MGeo模型失败: {str(e)}")

        return False

    def _fix_checkpoint_key_mapping(self):
        """
        修复checkpoint键名映射问题

        ModelScope原始checkpoint中BERT编码器键名使用 bert.text_encoder.* 前缀，
        但HuggingFace BERT模型期望 bert.* 前缀。此方法检测并修复键名不匹配问题。
        自动检测模型加载的实际路径（可能是本地路径或缓存路径）。
        """
        model_path = None
        if hasattr(self.model, 'name_or_path') and self.model.name_or_path:
            model_path = self.model.name_or_path

        if not model_path:
            local_path = Config.LOCAL_MODEL_PATH
            if local_path and os.path.isdir(local_path):
                model_path = local_path
            else:
                model_path = _find_model_local_path(self.model_name)

        if not model_path or not os.path.isdir(model_path):
            logger.info("无法确定模型路径，跳过checkpoint键名映射检查")
            return

        ckpt_path = os.path.join(model_path, 'pytorch_model.bin')
        if not os.path.exists(ckpt_path):
            ckpt_path_safetensors = os.path.join(model_path, 'model.safetensors')
            if not os.path.exists(ckpt_path_safetensors):
                logger.info("未找到 pytorch_model.bin 或 model.safetensors，跳过键名映射检查")
                return
            ckpt_path = ckpt_path_safetensors

        state_dict = self.model.state_dict()
        model_keys = set(state_dict.keys())

        if ckpt_path.endswith('.safetensors'):
            try:
                from safetensors.torch import load_file
                checkpoint = load_file(ckpt_path)
            except ImportError:
                logger.warning("safetensors 库不可用，无法检查 .safetensors 格式的checkpoint")
                return
        else:
            checkpoint = torch.load(ckpt_path, map_location=self.device, weights_only=False)

        ckpt_keys = set(checkpoint.keys())

        text_encoder_keys = [k for k in ckpt_keys if k.startswith('bert.text_encoder.')]
        if not text_encoder_keys:
            logger.info("No bert.text_encoder.* keys found in checkpoint, key mapping OK")
            return

        logger.warning(f"Found {len(text_encoder_keys)} keys with 'bert.text_encoder.' prefix in checkpoint. "
                      f"Applying key name mapping...")

        new_checkpoint = {}
        renamed = 0
        for key in checkpoint.keys():
            new_key = key.replace('bert.text_encoder.', 'bert.')
            new_checkpoint[new_key] = checkpoint[key]
            if new_key != key:
                renamed += 1

        missing, unexpected = self.model.load_state_dict(new_checkpoint, strict=False)

        if missing:
            logger.warning(f"Missing keys after key mapping fix: {missing}")
        if unexpected:
            logger.warning(f"Unexpected keys after key mapping fix: {unexpected}")

        logger.info(f"Key mapping applied: {renamed} keys renamed from bert.text_encoder.* to bert.*")

    def _get_default_batch_size(self):
        """
        获取默认批处理大小

        GPU上使用更大的batch_size以充分利用GPU并行计算能力，
        CPU上使用较小的batch_size避免内存溢出。

        Returns:
            int: 默认批处理大小
        """
        if self.device == 'cuda':
            return 256
        return 64

    def predict(self, address_pairs, batch_size=None):
        """
        批量预测地址对的匹配概率

        性能优化：
            1. padding='longest' - 按batch内最长序列padding，而非固定128长度
               地址文本通常20-50个token，使用longest可减少60-80%的无效计算
            2. GPU上使用FP16半精度推理
            3. 使用torch.inference_mode()替代torch.no_grad()
            4. 批量numpy操作替代逐元素Python循环

        Args:
            address_pairs: 地址对列表，每个元素为 (address1, address2)
            batch_size: 批处理大小，默认GPU=128, CPU=64

        Returns:
            list: 预测结果列表，每个元素包含地址对和匹配概率
        """
        if not address_pairs:
            return []

        batch_size = batch_size or self._get_default_batch_size()
        results = []

        for i in range(0, len(address_pairs), batch_size):
            batch = address_pairs[i:i+batch_size]

            try:
                inputs = self.tokenizer(
                    [pair[0] for pair in batch],
                    [pair[1] for pair in batch],
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
                    probs = torch.softmax(logits, dim=1)

                predictions = probs.cpu().numpy()

                for j, pair in enumerate(batch):
                    label_probs = {}
                    for idx, label_name in self.label_map.items():
                        label_probs[label_name] = float(predictions[j][idx])

                    results.append({
                        'address1': pair[0],
                        'address2': pair[1],
                        'scores': predictions[j].tolist(),
                        'labels': [self.label_map[i] for i in range(len(self.label_map))],
                        'exact_match': label_probs.get('exact_match', 0.0),
                        'not_match': label_probs.get('not_match', 0.0),
                        'partial_match': label_probs.get('partial_match', 0.0)
                    })

            except Exception as e:
                logger.error(f"Prediction error in batch {i//batch_size}: {str(e)}")
                for pair in batch:
                    results.append({
                        'address1': pair[0],
                        'address2': pair[1],
                        'scores': [0.0, 1.0, 0.0],
                        'labels': [self.label_map.get(i, '') for i in range(len(self.label_map))],
                        'exact_match': 0.0,
                        'not_match': 1.0,
                        'partial_match': 0.0
                    })

        return results

    def predict_optimized(self, address_pairs, batch_size=None):
        """
        高性能批量预测方法（用于精排阶段）

        相比predict方法的额外优化：
            1. 预分配结果列表，避免动态扩容
            2. 精简结果字典，仅保留精排所需字段（exact_match, not_match, partial_match）
            3. 批量numpy切片操作，避免逐元素Python循环
            4. 预计算标签索引，避免循环中重复查找
            5. 按地址长度排序分桶，使同一batch内序列长度接近，减少padding浪费
            6. max_length=80，中国地址对token长度通常在31-51之间，80覆盖99.9%+场景

        Args:
            address_pairs: 地址对列表，每个元素为 (address1, address2)
            batch_size: 批处理大小，默认GPU=256, CPU=64

        Returns:
            list: 预测结果列表，每个元素包含 exact_match, not_match, partial_match
        """
        if not address_pairs:
            return []

        batch_size = batch_size or self._get_default_batch_size()
        total_pairs = len(address_pairs)

        sorted_indices = sorted(range(total_pairs), key=lambda i: len(address_pairs[i][0]) + len(address_pairs[i][1]))

        results = [None] * total_pairs

        for i in range(0, total_pairs, batch_size):
            batch_indices = sorted_indices[i:i+batch_size]
            batch = [address_pairs[idx] for idx in batch_indices]
            batch_len = len(batch)

            try:
                inputs = self.tokenizer(
                    [pair[0] for pair in batch],
                    [pair[1] for pair in batch],
                    padding='longest',
                    truncation=True,
                    max_length=80,
                    return_tensors='pt'
                ).to(self.device)

                with torch.inference_mode():
                    outputs = self.model(**inputs)
                    logits = outputs.logits
                    if self.use_fp16:
                        logits = logits.float()
                    probs = torch.softmax(logits, dim=1)

                predictions = probs.cpu().numpy()

                not_match_arr = predictions[:, 0]
                partial_match_arr = predictions[:, 1]
                exact_match_arr = predictions[:, 2]

                for j in range(batch_len):
                    results[batch_indices[j]] = {
                        'exact_match': float(exact_match_arr[j]),
                        'not_match': float(not_match_arr[j]),
                        'partial_match': float(partial_match_arr[j])
                    }

            except Exception as e:
                logger.error(f"Prediction error in batch {i//batch_size}: {str(e)}")
                for j in range(batch_len):
                    results[batch_indices[j]] = {
                        'exact_match': 0.0,
                        'not_match': 1.0,
                        'partial_match': 0.0
                    }

        return results

    def get_similarity(self, address1, address2):
        """
        获取两个地址的匹配概率

        Args:
            address1: 第一个地址
            address2: 第二个地址

        Returns:
            dict: 包含 exact_match, not_match, partial_match 三个概率
        """
        result = self.predict([(address1, address2)])[0]
        return {
            'exact_match': result['exact_match'],
            'not_match': result['not_match'],
            'partial_match': result['partial_match']
        }

    def batch_predict(self, addresses1, addresses2, batch_size=None):
        """
        批量预测两组地址的匹配概率

        Args:
            addresses1: 地址列表1
            addresses2: 地址列表2（与addresses1一一对应）
            batch_size: 批处理大小

        Returns:
            list: 预测结果列表
        """
        pairs = list(zip(addresses1, addresses2))
        return self.predict(pairs, batch_size)
