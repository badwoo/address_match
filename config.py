"""
配置文件
========

地址匹配系统的全局配置项，包含数据库连接、模型参数、向量存储等配置。

项目目标：实现150万企业表数据和1300万标准地址数据通过地址匹配，获取标准地址的房号。

两阶段匹配流程：
    阶段1（粗召回）：使用 MGeo backbone 模型向量化，通过 pgvector 检索候选地址
    阶段2（精排）：使用 MGeo 地址相似度匹配模型进行精准排序

MGeo精排模型输出：
    模型输出三个概率值：exact_match（精确匹配）、not_match（不匹配）、partial_match（部分匹配）
    候选排序逻辑：
        主排序标准：exact_match - 按精确匹配概率最高值筛选最佳匹配候选
        次排序标准：not_match - 当 exact_match 相同时，优先选择不匹配概率更低的候选
    匹配状态判断：取三个概率中最大值决定匹配状态
        - exact_match 最大 → 精确匹配
        - partial_match 最大 → 部分匹配
        - not_match 最大 → 不匹配
        - 无候选 → 不匹配
"""

import os
import subprocess
import torch


def _detect_gpu_info():
    """
    增强GPU检测：综合多种方式检测系统是否有独立显卡及CUDA是否可用

    检测逻辑：
        1. 检测 torch.cuda.is_available() - PyTorch CUDA 是否可用
        2. 检测 nvidia-smi 命令 - 系统是否安装了 NVIDIA 驱动
        3. 检测 torch.backends.cuda.is_built() - PyTorch 是否为 CUDA 版本

    Returns:
        dict: GPU检测信息，包含以下字段：
            - has_gpu (bool): 系统是否有NVIDIA独立显卡
            - cuda_available (bool): PyTorch CUDA是否可用
            - torch_is_cuda_build (bool): PyTorch是否为CUDA版本
            - device_name (str): GPU设备名称，无GPU时为空字符串
            - cuda_version (str): CUDA版本，无GPU时为空字符串
            - torch_version (str): PyTorch版本号
            - warning (str): 警告信息，无警告时为空字符串
    """
    info = {
        'has_gpu': False,
        'cuda_available': torch.cuda.is_available(),
        'torch_is_cuda_build': False,
        'device_name': '',
        'cuda_version': '',
        'torch_version': torch.__version__,
        'warning': ''
    }

    try:
        info['torch_is_cuda_build'] = torch.backends.cuda.is_built()
    except Exception:
        pass

    if info['cuda_available']:
        info['has_gpu'] = True
        try:
            info['device_name'] = torch.cuda.get_device_name(0)
        except Exception:
            info['device_name'] = 'Unknown GPU'
        try:
            info['cuda_version'] = torch.version.cuda or ''
        except Exception:
            info['cuda_version'] = ''
        return info

    nvidia_smi_found = False
    try:
        result = subprocess.run(
            ['nvidia-smi', '--query-gpu=name,driver_version', '--format=csv,noheader'],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0 and result.stdout.strip():
            nvidia_smi_found = True
            first_line = result.stdout.strip().split('\n')[0]
            parts = [p.strip() for p in first_line.split(',')]
            info['device_name'] = parts[0] if len(parts) >= 1 else ''
            info['has_gpu'] = True
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass

    if nvidia_smi_found and not info['torch_is_cuda_build']:
        info['warning'] = (
            f"检测到NVIDIA独立显卡({info['device_name']})，但当前安装的PyTorch为CPU版本"
            f"(v{info['torch_version']})，无法使用GPU加速。"
            f"请安装CUDA版本的PyTorch以启用GPU支持。"
        )
    elif not nvidia_smi_found and not info['cuda_available']:
        info['warning'] = ''

    return info


def _find_model_local_path(model_name):
    """
    自动搜索本地模型路径

    按优先级依次搜索以下位置：
        1. 项目目录下的 models/ 文件夹
        2. 用户主目录下的 .cache/modelscope/hub/models/ 文件夹
        3. 环变量 MODELSCOPE_CACHE 指定的缓存目录

    Args:
        model_name: 模型名称，如 'iic/mgeo_backbone_chinese_base'

    Returns:
        str or None: 找到的本地模型路径，未找到返回 None
    """
    model_subdir = model_name.replace('/', os.sep)

    project_model_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'models', model_subdir)
    if os.path.isdir(project_model_dir):
        return project_model_dir

    home = os.path.expanduser('~')
    modelscope_cache = os.environ.get('MODELSCOPE_CACHE',
                                      os.path.join(home, '.cache', 'modelscope', 'hub', 'models'))
    modelscope_model_dir = os.path.join(modelscope_cache, model_subdir)
    if os.path.isdir(modelscope_model_dir):
        return modelscope_model_dir

    huggingface_cache = os.environ.get('HF_HOME',
                                       os.path.join(home, '.cache', 'huggingface', 'hub'))
    hf_model_name = 'models--' + model_name.replace('/', '--')
    hf_model_dir = os.path.join(huggingface_cache, hf_model_name)
    if os.path.isdir(hf_model_dir):
        return hf_model_dir

    return None


class Config:
    # ==================== 数据库配置 ====================
    DB_HOST = 'localhost'
    DB_PORT = 5432
    DB_NAME = 'postgres'
    DB_USER = 'postgres'
    DB_PASSWORD = '123456'
    DB_SCHEMA = 'public'  # 数据库模式（schema），默认为public
    
    # ==================== 模型配置 ====================
    # 向量化模型（粗召回阶段使用）
    EMBEDDING_MODEL_NAME = 'iic/mgeo_backbone_chinese_base'
    LOCAL_EMBEDDING_PATH = _find_model_local_path('iic/mgeo_backbone_chinese_base')
    
    # 精排模型（精排阶段使用）
    MODEL_NAME = 'iic/mgeo_geographic_entity_alignment_chinese_base'
    MODEL_REVISION = None
    LOCAL_MODEL_PATH = _find_model_local_path('iic/mgeo_geographic_entity_alignment_chinese_base')
    
    # 运行设备（自动检测GPU，使用增强检测逻辑）
    GPU_INFO = _detect_gpu_info()
    DEVICE = 'cuda' if GPU_INFO['cuda_available'] else 'cpu'
    
    # ==================== 向量配置 ====================
    VECTOR_DIM = 768  # MGeo backbone 模型输出维度
    VECTOR_TABLE = 'address_vectors'
    INDEX_NAME = 'address_vector_idx'
    ENTERPRISE_VECTOR_TABLE = 'enterprise_vectors'  # 企业地址向量表
    STANDARD_VECTOR_TABLE = 'standard_address_vectors'      # 标准地址向量表
    
    # ==================== 批处理配置 ====================
    BATCH_SIZE_DB = 1000        # 数据库批量加载大小
    BATCH_SIZE_EMBEDDING = 32   # 向量化批处理大小
    BATCH_SIZE_MODEL = 128       # 精排模型批处理大小（GPU默认128，CPU默认64，模型内部自动选择）
    
    # ==================== 匹配配置 ====================
    SIMILARITY_THRESHOLD = 0.8  # 相似度阈值（0-1）
    RECALL_TOP_N = 50           # 粗召回数量（每个企业召回前N条候选）
    
    # ==================== 表名配置 ====================
    RECALL_RESULTS_TABLE = 'recall_results'
    MATCH_RESULTS_TABLE = 'match_results'
    RESULT_TABLE = 'match_results'  # 兼容旧代码使用
    MGEO_SIMILARITY_RESULTS_TABLE = 'mgeo_similarity_results'  # MGeo地址相似度匹配结果表
    
    # ==================== 日志配置 ====================
    LOG_LEVEL = 'INFO'
    LOG_FILE = 'app.log'
