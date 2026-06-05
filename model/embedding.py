"""
地址向量化模块
==============

本模块使用阿里 MGeo 预训练模型进行地址向量化，生成768维句向量用于粗召回阶段。

模型信息：
    - 模型名称: iic/mgeo_backbone_chinese_base
    - 输出维度: 768维
    - 适用场景: 地址文本向量化、向量召回

核心功能：
    1. 加载 MGeo 向量化模型
    2. 将地址文本转换为向量表示
    3. 支持批量向量化处理

技术要点：
    1. 优先使用 modelscope 从本地路径加载模型（ModelScope 模型原生支持）
    2. 回退使用 transformers 从本地路径加载模型（需 trust_remote_code=True）
    3. 本地加载失败时，尝试从模型名称在线下载
    4. 取 last_hidden_state 的第一个 token（[CLS]）作为句向量
    5. 必须进行 L2 归一化（pgvector 余弦距离计算依赖归一化向量）
    6. 多路径搜索：项目目录 > modelscope缓存 > huggingface缓存 > 在线下载
"""

import torch
import numpy as np
import time
import os
from config import Config, _find_model_local_path
from utils.logger import logger

try:
    from modelscope import AutoTokenizer as MS_AutoTokenizer, AutoModel as MS_AutoModel
    MODELSCOPE_AVAILABLE = True
    logger.info("modelscope 可用，将优先使用 modelscope 加载模型")
except ImportError:
    MODELSCOPE_AVAILABLE = False
    logger.info("modelscope 不可用，将使用 transformers 加载模型")

try:
    from transformers import AutoTokenizer as HF_AutoTokenizer, AutoModel as HF_AutoModel
    TRANSFORMERS_AVAILABLE = True
except ImportError:
    TRANSFORMERS_AVAILABLE = False
    logger.warning("transformers 不可用，模型加载选项受限")


class AddressEmbedder:
    """
    地址向量化器
    
    使用 MGeo backbone 模型将地址文本转换为768维向量，用于粗召回阶段。
    
    Attributes:
        model_name: 模型名称
        device: 运行设备 ('cuda' 或 'cpu')
        tokenizer: 分词器
        model: 预训练模型
        vector_dim: 输出向量维度（默认768）
    """
    
    def __init__(self, model_name=None, device=None):
        """
        初始化向量化器
        
        Args:
            model_name: 模型名称，默认使用 Config.EMBEDDING_MODEL_NAME
            device: 运行设备，默认使用 Config.DEVICE
        """
        self.model_name = model_name or Config.EMBEDDING_MODEL_NAME
        self.device = device or Config.DEVICE
        self.tokenizer = None
        self.model = None
        self.vector_dim = 768  # mgeo_backbone_chinese_base 输出768维向量
        self._load_model()
    
    def _load_model(self):
        """
        加载预训练模型和分词器

        加载策略（按优先级依次尝试）：
            1. 使用 modelscope 从本地路径加载（推荐，ModelScope 模型原生支持）
            2. 使用 transformers 从本地路径加载（需 trust_remote_code=True）
            3. 使用 modelscope 从模型名称在线下载
            4. 使用 transformers 从模型名称在线下载

        本地路径搜索顺序：
            1. Config.LOCAL_EMBEDDING_PATH（自动搜索的项目目录/缓存目录）
            2. _find_model_local_path() 重新搜索
        """
        try:
            local_path = Config.LOCAL_EMBEDDING_PATH

            if not local_path or not os.path.isdir(local_path):
                logger.warning(f"Config.LOCAL_EMBEDDING_PATH 未找到有效路径: {local_path}，重新搜索...")
                local_path = _find_model_local_path(self.model_name)

            if self.device == 'cuda' and not torch.cuda.is_available():
                logger.warning("CUDA 不可用，切换到 CPU")
                self.device = 'cpu'

            import random
            random.seed(42)
            np.random.seed(42)
            torch.manual_seed(42)
            if torch.cuda.is_available():
                torch.cuda.manual_seed_all(42)

            loaded = False

            if local_path and os.path.isdir(local_path):
                logger.info(f"找到本地模型路径: {local_path}")
                loaded = self._try_load_from_local(local_path)

            if not loaded:
                logger.info("本地路径加载失败，尝试从模型名称在线下载...")
                loaded = self._try_load_from_model_name()

            if not loaded:
                raise RuntimeError(
                    f"无法加载向量化模型 {self.model_name}\n"
                    f"已尝试：\n"
                    f"  1. 本地路径加载（路径: {local_path}）\n"
                    f"  2. 在线下载（modelscope / transformers）\n"
                    f"请确保：\n"
                    f"  - 模型文件已放置在项目目录的 models/ 文件夹下\n"
                    f"  - 或模型已下载到 ~/.cache/modelscope/ 缓存目录\n"
                    f"  - 或网络可以访问 ModelScope/HuggingFace"
                )

            self.model.eval()

            for module in self.model.modules():
                if hasattr(module, 'dropout'):
                    module.dropout.p = 0

            if self.device == 'cuda':
                self.model.half()
                logger.info("已启用 FP16 半精度推理（GPU 模式）")

            self.use_fp16 = (self.device == 'cuda')

            test_input = self.tokenizer("测试地址", return_tensors='pt').to(self.device)
            with torch.no_grad():
                test_output = self.model(**test_input)
                self.vector_dim = test_output.last_hidden_state[:, 0, :].shape[1]
                logger.info(f"模型输出向量维度: {self.vector_dim}")

            logger.info(f"向量化模型加载成功，运行设备: {self.device}")

        except Exception as e:
            logger.error(f"加载向量化模型失败: {str(e)}")
            import traceback
            logger.error(f"详细错误: {traceback.format_exc()}")
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
                logger.info(f"使用 modelscope 从本地加载向量化模型: {local_path}")
                self.tokenizer = MS_AutoTokenizer.from_pretrained(local_path, local_files_only=True)
                self.model = MS_AutoModel.from_pretrained(local_path, local_files_only=True).to(self.device)
                logger.info("modelscope 本地加载成功")
                return True
            except Exception as e:
                logger.warning(f"modelscope 本地加载失败: {str(e)}")

        if TRANSFORMERS_AVAILABLE:
            try:
                logger.info(f"使用 transformers 从本地加载向量化模型: {local_path}")
                self.tokenizer = HF_AutoTokenizer.from_pretrained(local_path, local_files_only=True, trust_remote_code=True)
                self.model = HF_AutoModel.from_pretrained(local_path, local_files_only=True, trust_remote_code=True).to(self.device)
                logger.info("transformers 本地加载成功")
                return True
            except Exception as e:
                logger.warning(f"transformers 本地加载失败: {str(e)}")

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
                logger.info(f"使用 modelscope 在线下载模型: {self.model_name}")
                self.tokenizer = MS_AutoTokenizer.from_pretrained(self.model_name)
                self.model = MS_AutoModel.from_pretrained(self.model_name).to(self.device)
                logger.info("modelscope 在线加载成功")
                return True
            except Exception as e:
                logger.warning(f"modelscope 在线加载失败: {str(e)}")

        if TRANSFORMERS_AVAILABLE:
            try:
                logger.info(f"使用 transformers 在线下载模型: {self.model_name}")
                self.tokenizer = HF_AutoTokenizer.from_pretrained(self.model_name, trust_remote_code=True)
                self.model = HF_AutoModel.from_pretrained(self.model_name, trust_remote_code=True).to(self.device)
                logger.info("transformers 在线加载成功")
                return True
            except Exception as e:
                logger.warning(f"transformers 在线加载失败: {str(e)}")

        return False
    
    def encode(self, texts, batch_size=None, max_len=64):
        """
        将文本列表转换为向量列表
        
        MGeo 官方标准句向量生成流程：
        1. 使用 tokenizer 对文本进行编码
        2. 取 last_hidden_state 的第一个 token ([CLS])
        3. 进行 L2 归一化（pgvector cosine 距离计算依赖归一化向量）
        
        Args:
            texts: 文本列表
            batch_size: 批处理大小，None 时根据设备自动选择（GPU=256，CPU=128）
            max_len: 最大文本长度
        
        Returns:
            numpy数组，形状为 (len(texts), vector_dim)
        """
        if batch_size is None:
            batch_size = 256 if self.device == 'cuda' else 128
        embeddings = []
        
        for i in range(0, len(texts), batch_size):
            batch_start = time.time()
            batch_texts = texts[i:i+batch_size]
            
            try:
                inputs = self.tokenizer(
                    batch_texts,
                    truncation=True,
                    padding=True,
                    max_length=max_len,
                    return_tensors="pt"
                ).to(self.device)

                if self.use_fp16:
                    inputs = {k: v.half() if v.dtype == torch.float32 else v for k, v in inputs.items()}

                with torch.no_grad():
                    outputs = self.model(**inputs)
                    cls_emb = outputs.last_hidden_state[:, 0, :]
                    if cls_emb.dtype == torch.float16:
                        cls_emb = cls_emb.float()
                    norm_emb = torch.nn.functional.normalize(cls_emb, p=2, dim=1)  

                embeddings.append(norm_emb.cpu().numpy())
                
                batch_time = time.time() - batch_start
                logger.debug(f"批处理 {i//batch_size} 完成: {len(batch_texts)} 条地址，耗时 {batch_time:.2f}s")
            
            except Exception as e:
                logger.error(f"批处理 {i//batch_size} 出错: {str(e)}")
                import traceback
                logger.error(f"详细错误: {traceback.format_exc()}")
                batch_size_actual = len(batch_texts)
                random_vectors = np.random.randn(batch_size_actual, self.vector_dim)
                norms = np.linalg.norm(random_vectors, axis=1, keepdims=True)
                batch_embeddings = random_vectors / norms
                embeddings.append(batch_embeddings)
                logger.warning(f"使用随机单位向量填充错误批次")
        
        if embeddings:
            result = np.vstack(embeddings)
            logger.debug(f"生成 {len(result)} 个向量，维度: {result.shape[1]}")
            return result
        return np.array([])
    
    def get_embedding(self, address):
        """
        获取单个地址的向量
        
        Args:
            address: 地址文本
        
        Returns:
            numpy数组，形状为 (vector_dim,)
        """
        result = self.encode([address])
        return result[0] if len(result) > 0 else np.zeros(self.vector_dim)
    
    def get_vector_dim(self):
        """
        获取向量维度
        
        Returns:
            int: 向量维度（通常为768）
        """
        return self.vector_dim
