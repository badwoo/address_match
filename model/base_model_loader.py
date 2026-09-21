"""
模型加载基类
============

提供通用的模型加载逻辑，消除三个模型类（embedding/mgeo/tagging）中的重复代码。

核心功能：
    1. 统一的模型加载策略（本地优先 → 在线下载）
    2. modelscope / transformers 双通道 fallback
    3. checkpoint 键名映射修复（bert.text_encoder.* → bert.*）
    4. 随机种子设置
    5. CUDA 可用性检测与自动降级

子类只需实现：
    - _get_model_classes(): 返回 (MS_ModelClass, HF_ModelClass) 元组
    - _get_model_label(): 返回模型标签（用于日志）
    - _get_extra_load_kwargs(): 返回额外的模型加载参数（可选）
"""

import torch
import os
from config import Config, _find_model_local_path
from utils.logger import logger

try:
    from modelscope import AutoTokenizer as MS_AutoTokenizer
    MODELSCOPE_AVAILABLE = True
except ImportError:
    MODELSCOPE_AVAILABLE = False

try:
    from transformers import AutoTokenizer as HF_AutoTokenizer
    TRANSFORMERS_AVAILABLE = True
except ImportError:
    TRANSFORMERS_AVAILABLE = False


class BaseModelLoader:
    """
    模型加载基类

    封装通用的模型加载、键名修复、设备检测逻辑。
    子类通过覆盖 _get_model_classes() 和 _get_model_label() 定制化。
    """

    def _get_model_classes(self):
        """
        返回 modelscope 和 transformers 对应的模型类

        Returns:
            tuple: (MS_ModelClass, HF_ModelClass)
        """
        raise NotImplementedError

    def _get_model_label(self):
        """
        返回模型标签（用于日志区分不同模型）

        Returns:
            str: 模型标签，如 '向量化模型'、'MGeo模型'、'地址要素解析模型'
        """
        return '模型'

    def _get_extra_load_kwargs(self):
        """
        返回额外的模型加载参数

        子类可覆盖此方法提供额外参数，如 num_labels、ignore_mismatched_sizes 等。

        Returns:
            dict: 额外参数字典，默认为空
        """
        return {}

    def _check_cuda_and_set_seed(self):
        """检查 CUDA 可用性并设置随机种子"""
        if self.device == 'cuda' and not torch.cuda.is_available():
            logger.warning("CUDA 不可用，切换到 CPU")
            self.device = 'cpu'

        import random
        import numpy as np
        random.seed(42)
        np.random.seed(42)
        torch.manual_seed(42)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(42)

    def _try_load_from_local(self, local_path):
        """
        尝试从本地路径加载模型

        依次尝试 modelscope 和 transformers 两种加载方式

        Args:
            local_path: 本地模型目录路径

        Returns:
            bool: 加载成功返回 True
        """
        label = self._get_model_label()
        ms_model_cls, hf_model_cls = self._get_model_classes()
        extra_kwargs = self._get_extra_load_kwargs()

        if MODELSCOPE_AVAILABLE:
            try:
                logger.info(f"使用 modelscope 从本地加载{label}: {local_path}")
                self.tokenizer = MS_AutoTokenizer.from_pretrained(local_path, local_files_only=True)
                model_kwargs = {'local_files_only': True}
                model_kwargs.update(extra_kwargs)
                self.model = ms_model_cls.from_pretrained(local_path, **model_kwargs).to(self.device)
                logger.info(f"modelscope 本地加载{label}成功")
                return True
            except Exception as e:
                logger.warning(f"modelscope 本地加载{label}失败: {str(e)}")

        if TRANSFORMERS_AVAILABLE:
            try:
                logger.info(f"使用 transformers 从本地加载{label}: {local_path}")
                self.tokenizer = HF_AutoTokenizer.from_pretrained(local_path, local_files_only=True, trust_remote_code=True)
                model_kwargs = {'local_files_only': True, 'trust_remote_code': True}
                model_kwargs.update(extra_kwargs)
                self.model = hf_model_cls.from_pretrained(local_path, **model_kwargs).to(self.device)
                logger.info(f"transformers 本地加载{label}成功")
                return True
            except Exception as e:
                logger.warning(f"transformers 本地加载{label}失败: {str(e)}")

        return False

    def _try_load_from_model_name(self):
        """
        尝试从模型名称在线下载并加载

        依次尝试 modelscope 和 transformers 两种加载方式

        Returns:
            bool: 加载成功返回 True
        """
        label = self._get_model_label()
        ms_model_cls, hf_model_cls = self._get_model_classes()
        extra_kwargs = self._get_extra_load_kwargs()

        if MODELSCOPE_AVAILABLE:
            try:
                logger.info(f"使用 modelscope 在线下载{label}: {self.model_name}")
                self.tokenizer = MS_AutoTokenizer.from_pretrained(self.model_name)
                self.model = ms_model_cls.from_pretrained(self.model_name, **extra_kwargs).to(self.device)
                logger.info(f"modelscope 在线加载{label}成功")
                return True
            except Exception as e:
                logger.warning(f"modelscope 在线加载{label}失败: {str(e)}")

        if TRANSFORMERS_AVAILABLE:
            try:
                logger.info(f"使用 transformers 在线下载{label}: {self.model_name}")
                self.tokenizer = HF_AutoTokenizer.from_pretrained(self.model_name, trust_remote_code=True)
                model_kwargs = {'trust_remote_code': True}
                model_kwargs.update(extra_kwargs)
                self.model = hf_model_cls.from_pretrained(self.model_name, **model_kwargs).to(self.device)
                logger.info(f"transformers 在线加载{label}成功")
                return True
            except Exception as e:
                logger.warning(f"transformers 在线加载{label}失败: {str(e)}")

        return False

    def _fix_checkpoint_key_mapping(self):
        """
        修复checkpoint键名映射问题

        ModelScope原始checkpoint中BERT编码器键名使用 bert.text_encoder.* 前缀，
        但HuggingFace BERT模型期望 bert.* 前缀。此方法检测并修复键名不匹配问题。

        内存优化：先只读 keys 判断是否需要映射，不需要则直接返回；
        需要映射时，逐键重命名并立即删除旧键，避免同时持有两份完整权重。
        """
        label = self._get_model_label()
        model_path = None
        if hasattr(self.model, 'name_or_path') and self.model.name_or_path:
            model_path = self.model.name_or_path

        if not model_path:
            local_path = getattr(Config, 'LOCAL_MODEL_PATH', None)
            if local_path and os.path.isdir(local_path):
                model_path = local_path
            else:
                model_path = _find_model_local_path(self.model_name)

        if not model_path or not os.path.isdir(model_path):
            logger.info(f"[{label}] 无法确定模型路径，跳过checkpoint键名映射检查")
            return

        ckpt_path = os.path.join(model_path, 'pytorch_model.bin')
        if not os.path.exists(ckpt_path):
            ckpt_path_safetensors = os.path.join(model_path, 'model.safetensors')
            if not os.path.exists(ckpt_path_safetensors):
                logger.info(f"[{label}] 未找到 pytorch_model.bin 或 model.safetensors，跳过键名映射检查")
                return
            ckpt_path = ckpt_path_safetensors

        if ckpt_path.endswith('.safetensors'):
            try:
                from safetensors.torch import load_file
                checkpoint = load_file(ckpt_path)
            except ImportError:
                logger.warning(f"[{label}] safetensors 库不可用，无法检查 .safetensors 格式的checkpoint")
                return
        else:
            # 使用 map_location='cpu' 加载，避免占用 GPU 显存
            checkpoint = torch.load(ckpt_path, map_location='cpu', weights_only=False)

        # 先检查是否需要映射，不需要则立即释放
        ckpt_keys = set(checkpoint.keys())
        text_encoder_keys = [k for k in ckpt_keys if k.startswith('bert.text_encoder.')]
        if not text_encoder_keys:
            logger.info(f"[{label}] checkpoint中未找到 bert.text_encoder.* 键名，键名映射OK")
            del checkpoint
            return

        logger.warning(f"[{label}] 发现 {len(text_encoder_keys)} 个 bert.text_encoder.* 前缀键名，应用键名映射...")

        # 逐键重命名：修改 key 后删除旧 key，避免同时持有两份权重
        renamed = 0
        keys_to_rename = [k for k in checkpoint.keys() if k.startswith('bert.text_encoder.')]
        for old_key in keys_to_rename:
            new_key = old_key.replace('bert.text_encoder.', 'bert.')
            checkpoint[new_key] = checkpoint.pop(old_key)
            renamed += 1

        missing, unexpected = self.model.load_state_dict(checkpoint, strict=False)

        # 立即释放 checkpoint 内存
        del checkpoint

        if missing:
            logger.warning(f"[{label}] 键名映射后仍缺失的键: {len(missing)}个")
        if unexpected:
            logger.warning(f"[{label}] 键名映射后多余的键: {len(unexpected)}个")

        logger.info(f"[{label}] 键名映射完成: {renamed}个键从 bert.text_encoder.* 重命名为 bert.*")
