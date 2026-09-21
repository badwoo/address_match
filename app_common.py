"""
公共工具函数和共享状态
====================
被多个页面模块共享的工具函数、session_state 初始化、缓存数据库连接等。
"""

import streamlit as st
import pandas as pd
import os
import threading
from collections import OrderedDict
from database.connection import DBConnection
from config import Config
from utils.logger import logger


# ==================== Fragment 轮询间隔配置 ====================
# 集中管理各页面 fragment 的轮询间隔（秒），避免分散硬编码
# 任务未运行时 fragment 内应立即 return，避免无意义 DB 查询
FRAGMENT_POLL_INTERVALS = {
    'matching': 3,         # 地址匹配任务进度
    'vectorize': 3,        # 向量化进度
    'tagging': 3,          # 地址结构化解析进度
    'mgeo_similarity': 3,  # MGeo 相似度匹配进度
}

# ==================== Matcher 状态字段白名单 ====================
# 集中定义 matcher 状态字段，避免 sync_matcher_status 遗漏字段
MATCHER_STATUS_FIELDS = (
    'is_running', 'is_paused', 'processed_count', 'total_count',
    'current_stage', 'progress', 'speed', 'remaining_time',
    'status_message', 'error_message'
)


def sync_matcher_status(matcher, status_dict, extra_fields=None):
    """
    从 matcher 同步状态到 session_state 字典

    替代手动 matching_status.update({...}) 逐字段复制，避免遗漏。
    线程安全：通过 matcher.get_status() 获取快照。

    Args:
        matcher: AddressMatcher 实例
        status_dict: session_state 中的状态字典（如 st.session_state.matching_status）
        extra_fields: 额外要同步的字段名列表（如 ['recall_completed', 'match_count']）
    """
    if matcher is None:
        return
    try:
        stat = matcher.get_status()
        for field in MATCHER_STATUS_FIELDS:
            if field in stat:
                status_dict[field] = stat[field]
        if extra_fields:
            for field in extra_fields:
                if field in stat:
                    status_dict[field] = stat[field]
    except Exception as e:
        logger.error(f"同步 matcher 状态失败: {e}")


# ==================== 模型实例缓存（模块级单例，线程安全） ====================
# 模型在后台线程中使用，不能用 @st.cache_resource（Streamlit cache 与线程不兼容）
# 模型实例本身是线程安全的（model.eval() + torch.no_grad()），可跨线程共享
# 使用 OrderedDict 实现 LRU 淘汰，避免切换设备后旧模型仍占显存
_model_lock = threading.Lock()
_model_cache = OrderedDict()
_MAX_MODEL_CACHE = 2  # 最多保留 2 个模型实例（如 embedder+mgeo 或 cuda+cpu）


def _evict_oldest_model():
    """淘汰最久未用的模型，释放显存"""
    if not _model_cache:
        return
    old_key, old_model = _model_cache.popitem(last=False)
    try:
        # 释放模型持有的资源
        if hasattr(old_model, 'model') and old_model.model is not None:
            del old_model.model
        if hasattr(old_model, 'tokenizer'):
            del old_model.tokenizer
        import gc
        gc.collect()
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass
        logger.info(f"已淘汰模型缓存: {old_key}")
    except Exception as e:
        logger.warning(f"淘汰模型缓存失败: {e}")


def format_time(seconds):
    if seconds < 60:
        return f"{seconds:.1f}秒"
    elif seconds < 3600:
        return f"{int(seconds // 60)}分{int(seconds % 60)}秒"
    else:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        return f"{hours}小时{minutes}分"


def detect_csv_encoding(file_bytes):
    """
    自动检测CSV文件的编码格式

    依次尝试常见中文编码：utf-8-sig, utf-8, gbk, gb2312, gb18030, latin1

    Args:
        file_bytes: 文件的字节数据

    Returns:
        str: 检测到的编码格式名称
    """
    encodings = ['utf-8-sig', 'utf-8', 'gbk', 'gb2312', 'gb18030', 'latin1']
    for encoding in encodings:
        try:
            file_bytes.decode(encoding)
            return encoding
        except (UnicodeDecodeError, LookupError):
            continue
    return 'utf-8'


def read_csv_with_encoding(uploaded_file, nrows=None):
    """
    使用自动检测编码读取CSV文件

    Args:
        uploaded_file: Streamlit上传的文件对象
        nrows: 读取的行数，None表示读取全部

    Returns:
        DataFrame: 读取的数据帧
    """
    file_bytes = uploaded_file.read()
    encoding = detect_csv_encoding(file_bytes)
    uploaded_file.seek(0)

    if nrows is not None:
        df = pd.read_csv(uploaded_file, encoding=encoding, nrows=nrows)
    else:
        df = pd.read_csv(uploaded_file, encoding=encoding)

    return df, encoding


def _goto_page(key, page_num):
    """翻页回调：跳转到指定页码"""
    st.session_state[key] = page_num


# 结果管理页面所有 page_size widget key 列表（用于持久化初始化）
# Streamlit 的 widget 状态管理机制：当 widget 在某次渲染中未出现，session_state[key] 会被清除。
# page_size selectbox 在 try/if 块内部，边界场景（total=0、异常、st.rerun 提前中断）下可能未渲染，
# 导致下次渲染时 selectbox 使用 index 默认值（20），用户之前设置的每页行数丢失。
# 使用非 widget key 的持久化变量存储用户选择，在 selectbox 渲染前恢复。
PAGE_SIZE_WIDGET_KEYS = (
    'recall_page_size', 'match_page_size', 'sim_page_size',
    'mgeo_page_size', 'tagging_page_size', 'tagging_17_page_size',
    'tagging_17_2_page_size', 'mgeo_copy_page_size', 'tagging_copy_page_size',
    'tagging_17_copy_page_size', 'tagging_17_2_copy_page_size',
)


def _make_page_size_persist_callback(key):
    """
    创建 page_size selectbox 的 on_change 回调函数。

    当用户改变 selectbox 时，同步更新对应的持久化变量，
    以便在 widget 状态被 Streamlit 清除后能从持久化变量恢复。

    Args:
        key: selectbox 的 widget key（如 'match_page_size'）

    Returns:
        callable: on_change 回调函数
    """
    persist_key = f'{key}_persist'

    def _on_change():
        st.session_state[persist_key] = st.session_state[key]

    return _on_change


def _restore_page_size(key, default_value=20):
    """
    在 page_size selectbox 渲染前调用，从持久化变量恢复 widget 状态。

    如果 session_state[key] 不存在（被 Streamlit 清除），从持久化变量恢复。
    如果持久化变量也不存在，使用 default_value。

    Args:
        key: selectbox 的 widget key（如 'match_page_size'）
        default_value: 默认每页行数，默认 20
    """
    persist_key = f'{key}_persist'
    if persist_key not in st.session_state:
        st.session_state[persist_key] = default_value
    if key not in st.session_state:
        st.session_state[key] = st.session_state[persist_key]


def _render_device_selector(key='device_selector'):
    """
    渲染设备运行模式下拉框

    根据GPU检测结果，显示可选的运行设备下拉框。
    有GPU时默认GPU模式，支持切换到CPU模式；无GPU时仅CPU模式。

    Args:
        key: Streamlit组件key，用于区分不同页面的下拉框

    Returns:
        str: 用户选择的设备 ('cuda' 或 'cpu')
    """
    gpu_info = st.session_state.get('gpu_info', {})
    cuda_available = gpu_info.get('cuda_available', False)
    has_gpu = gpu_info.get('has_gpu', False)
    device_name = gpu_info.get('device_name', '')

    if cuda_available:
        options = ['🖥️ GPU模式运行', '💻 CPU模式运行']
        default_index = 0
        if device_name:
            st.caption(f"检测到独立显卡: {device_name}")
    elif has_gpu:
        options = ['💻 CPU模式运行']
        default_index = 0
        if gpu_info.get('warning'):
            st.warning(gpu_info['warning'])
    else:
        options = ['💻 CPU模式运行']
        default_index = 0
        st.caption("未检测到NVIDIA独立显卡，使用CPU模式运行")

    selected = st.selectbox(
        "设备运行模式",
        options=options,
        index=default_index,
        key=key
    )

    if 'GPU' in selected and cuda_available:
        return 'cuda'
    return 'cpu'


def _prev_page(key):
    """翻页回调：上一页"""
    if key in st.session_state and st.session_state[key] > 1:
        st.session_state[key] -= 1


def _next_page(key, total_pages_key_or_val):
    """翻页回调：下一页。total_pages_key_or_val 可以是 session_state key 或直接的总页数值"""
    if isinstance(total_pages_key_or_val, int):
        total = total_pages_key_or_val
    else:
        total = st.session_state.get(total_pages_key_or_val, 1)
    if key in st.session_state and st.session_state[key] < total:
        st.session_state[key] += 1


def _default_task_status(**overrides):
    """
    任务状态默认模板

    统一各页面任务状态字典的公共字段，消除 init_session_state 中 6 处重复定义。
    差异化字段通过 overrides 传入，覆盖同名默认值。

    默认字段集（12 个公共字段）：
        is_running, progress, processed_count, total_count,
        speed, remaining_time, status_message, error_message,
        start_time, end_time, completed, result_count

    Args:
        **overrides: 差异化字段（如 input_type='file', source_table='', result_table=''）

    Returns:
        dict: 完整的任务状态字典
    """
    base = {
        'is_running': False,
        'progress': 0.0,
        'processed_count': 0,
        'total_count': 0,
        'speed': 0.0,
        'remaining_time': 0.0,
        'status_message': '',
        'error_message': '',
        'start_time': None,
        'end_time': None,
        'completed': False,
        'result_count': 0,
    }
    base.update(overrides)
    return base


def init_session_state():
    """初始化Streamlit会话状态，存储全局配置信息"""
    from config import _detect_gpu_info

    if 'gpu_info' not in st.session_state:
        st.session_state.gpu_info = _detect_gpu_info()

    if 'selected_device' not in st.session_state:
        if st.session_state.gpu_info['cuda_available']:
            st.session_state.selected_device = 'cuda'
        else:
            st.session_state.selected_device = 'cpu'

    # 数据库连接配置（从环境变量读取默认值，兼容 .env 文件）
    if 'db_config' not in st.session_state:
        st.session_state.db_config = {
            'host': os.getenv('DB_HOST', 'localhost'),
            'port': int(os.getenv('DB_PORT', '5432')),
            'schema': os.getenv('DB_SCHEMA', 'public'),
            'dbname': os.getenv('DB_NAME', 'postgres'),
            'user': os.getenv('DB_USER', 'postgres'),
            'password': os.getenv('DB_PASSWORD', '123456')
        }

    # 数据库连接状态
    if 'connected' not in st.session_state:
        st.session_state.connected = False

    # 当前选中的菜单
    if 'selected_menu' not in st.session_state:
        st.session_state.selected_menu = "首页"

    # 向量化配置（企业表和标准地址表字段映射）
    if 'vec_config' not in st.session_state:
        st.session_state.vec_config = {
            'enterprise_table': '',      # 企业表名
            'enterprise_id_col': '',     # 企业标识字段
            'enterprise_name_col': '',   # 企业名字段
            'enterprise_address_col': '',# 企业地址字段
            'enterprise_vector_table': Config.ENTERPRISE_VECTOR_TABLE,  # 企业向量表名（自定义）
            'standard_table': '',        # 标准地址表名
            'standard_id_col': '',       # 地址编码字段
            'standard_address_col': '',  # 标准地址字段
            'standard_room_col': '',     # 房屋编码字段
            'standard_vector_table': Config.STANDARD_VECTOR_TABLE,      # 标准地址向量表名（自定义）
            'table_vec_mapping': {}      # 源表名→向量表名 映射，用于切换源表时回显已创建的向量表
        }

    # 匹配配置
    if 'matching_config' not in st.session_state:
        st.session_state.matching_config = {
            'enterprise_vector_table': '',  # 企业向量表名
            'standard_vector_table': '',    # 标准地址向量表名
            'recall_top_n': 10,            # 粗召回数量
            'ef_search': None,             # HNSW ef_search 参数，None 表示由系统自动推荐
            'similarity_threshold': 0.7     # 相似度阈值
        }

    # 匹配任务状态
    if 'matching_status' not in st.session_state:
        st.session_state.matching_status = _default_task_status(
            current_stage='',  # 当前阶段（数据粗召回/MGeo精确匹配/流式匹配等）
            recall_completed=False,  # 粗召回是否完成
            ranking_completed=False,  # 精排是否完成
            ranking_ui_shown=False,  # 精排完成UI是否已显示
            recall_count=0,  # 召回结果数量
            match_count=0  # 匹配结果数量
        )

    # 粗召回结果状态（用于分步执行）
    if 'recall_status' not in st.session_state:
        st.session_state.recall_status = {
            'completed': False,
            'start_time': None,
            'end_time': None,
            'recall_count': 0,
            'candidate_count': 0
        }

    # MGeo相似度匹配状态
    if 'mgeo_similarity_status' not in st.session_state:
        st.session_state.mgeo_similarity_status = _default_task_status(
            input_type='file',
            source_table='',
            copy_table=''
        )

    # 地址结构化解析状态
    if 'address_tagging_status' not in st.session_state:
        st.session_state.address_tagging_status = _default_task_status(
            input_type='file',
            source_table='',
            result_table='',
            copy_table=''
        )

    # 地址17级结构化解析状态
    if 'address_tagging_17_status' not in st.session_state:
        st.session_state.address_tagging_17_status = _default_task_status(
            input_type='file',
            source_table='',
            result_table='',
            copy_table=''
        )

    # 地址17级双字段结构化解析状态
    if 'address_tagging_17_2_status' not in st.session_state:
        st.session_state.address_tagging_17_2_status = _default_task_status(
            input_type='file',
            source_table='',
            result_table='',
            copy_table=''
        )

    # 标签相关状态
    if 'current_tag' not in st.session_state:
        st.session_state.current_tag = ''
    if 'current_tag_prefix' not in st.session_state:
        st.session_state.current_tag_prefix = ''
    if 'current_recall_table' not in st.session_state:
        st.session_state.current_recall_table = Config.RECALL_RESULTS_TABLE
    if 'show_new_tag_input' not in st.session_state:
        st.session_state.show_new_tag_input = False
    if 'current_match_table' not in st.session_state:
        st.session_state.current_match_table = Config.MATCH_RESULTS_TABLE

    # 人工纠正相关状态
    if 'manual_correction_mode' not in st.session_state:
        st.session_state.manual_correction_mode = False
    if 'manual_correction_enterprise_ids' not in st.session_state:
        st.session_state.manual_correction_enterprise_ids = []
    if 'manual_correction_selected_rows' not in st.session_state:
        st.session_state.manual_correction_selected_rows = []
    if 'show_correction_confirm' not in st.session_state:
        st.session_state.show_correction_confirm = False
    if 'pending_correction_data' not in st.session_state:
        st.session_state.pending_correction_data = []
    if 'correction_success_count' not in st.session_state:
        st.session_state.correction_success_count = 0
    if 'direct_correction_mode' not in st.session_state:
        st.session_state.direct_correction_mode = False
    if 'direct_correction_data' not in st.session_state:
        st.session_state.direct_correction_data = pd.DataFrame()
    if 'direct_correction_success_count' not in st.session_state:
        st.session_state.direct_correction_success_count = 0

    # 向量化状态（统一初始化，避免页面内重复）
    if 'vec_status' not in st.session_state:
        st.session_state.vec_status = {
            'is_running': False,
            'table_type': '',
            'cancel_requested': False,
            'processed_count': 0,
            'total_count': 0,
            'progress': 0.0,
            'speed': 0.0,
            'elapsed': 0.0,
            'remaining': 0.0,
            'status_message': '',
            'error_message': '',
            'completed': False,
            'cancelled': False,
            'start_datetime': '',
            'end_datetime': '',
            'execution_time': 0.0
        }

    # 索引创建状态
    if 'index_status' not in st.session_state:
        st.session_state.index_status = {
            'is_running': False,
            'completed': False,
            'error_message': '',
            'start_datetime': '',
            'end_datetime': '',
            'execution_time': 0.0,
            'start_time': 0.0
        }

    # 结果管理页面分页状态（统一初始化，避免页面内重复）
    for _pg_key in ['recall_page', 'match_page', 'sim_page', 'tagging_page',
                    'tagging_17_page', 'tagging_17_2_page',
                    'mgeo_copy_page', 'tagging_copy_page', 'tagging_17_copy_page',
                    'tagging_17_2_copy_page']:
        if _pg_key not in st.session_state:
            st.session_state[_pg_key] = 1


@st.cache_resource(ttl=60, show_spinner=False)
def _get_cached_db_connection(host, port, dbname, user, password, schema):
    """缓存的 DB 连接，避免每次 st.rerun() 都重建 TCP 连接。TTL=60s。"""
    conn = DBConnection(host=host, port=port, schema=schema, dbname=dbname, user=user, password=password)
    if conn.connect():
        return conn
    return None


def get_cached_embedder(device):
    """
    获取缓存的 AddressEmbedder 实例（线程安全）。

    模型实例全局单例，避免每次向量化/调试都重新加载（5-15秒/次）。
    模型在后台线程中使用，不能用 @st.cache_resource（Streamlit cache 与线程不兼容）。
    模型实例本身线程安全（model.eval() + torch.no_grad()），可跨线程共享。

    Args:
        device: 运行设备 ('cuda' 或 'cpu')

    Returns:
        AddressEmbedder 实例
    """
    key = ('embedder', device)
    with _model_lock:
        if key in _model_cache:
            _model_cache.move_to_end(key)
            return _model_cache[key]
        if len(_model_cache) >= _MAX_MODEL_CACHE:
            _evict_oldest_model()
        from model.embedding import AddressEmbedder
        _model_cache[key] = AddressEmbedder(device=device)
        return _model_cache[key]


def get_cached_mgeo_model(device):
    """
    获取缓存的 MGeoModel 实例（线程安全）。

    模型实例全局单例，避免每次精排都重新加载（5-15秒/次）。

    Args:
        device: 运行设备 ('cuda' 或 'cpu')

    Returns:
        MGeoModel 实例
    """
    key = ('mgeo', device)
    with _model_lock:
        if key in _model_cache:
            _model_cache.move_to_end(key)
            return _model_cache[key]
        if len(_model_cache) >= _MAX_MODEL_CACHE:
            _evict_oldest_model()
        from model.mgeo_model import MGeoModel
        _model_cache[key] = MGeoModel(device=device)
        return _model_cache[key]


def get_cached_tagging_model(device):
    """
    获取缓存的 AddressTaggingModel 实例（线程安全）。

    模型实例全局单例，避免每次解析都重新加载（5-15秒/次）。
    mode 参数只影响解析逻辑（输出字段），不影响模型加载，因此缓存 key 不含 mode。

    Args:
        device: 运行设备 ('cuda' 或 'cpu')

    Returns:
        AddressTaggingModel 实例
    """
    key = ('tagging', device)
    with _model_lock:
        if key in _model_cache:
            _model_cache.move_to_end(key)
            return _model_cache[key]
        if len(_model_cache) >= _MAX_MODEL_CACHE:
            _evict_oldest_model()
        from model.address_tagging_model import AddressTaggingModel
        _model_cache[key] = AddressTaggingModel(device=device)
        return _model_cache[key]


# ==================== 只读 DB 查询缓存 ====================
# 使用 @st.cache_data(ttl=30) 缓存只读查询结果，减少每次 rerun 的 DB 往返
# TTL=30秒，平衡数据新鲜度和性能
# 用连接参数（host+port+dbname+user+schema）作为缓存 key，参数变化时自动失效
# 注意：数据变更时需调用 st.cache_data.clear() 清除缓存

@st.cache_data(ttl=30, show_spinner=False)
def get_cached_tables(host, port, dbname, user, schema):
    """
    缓存表列表（30秒TTL）。

    Args:
        host, port, dbname, user, schema: 数据库连接参数（作为缓存 key）

    Returns:
        tuple: 表名元组（不可变，可被 cache_data 序列化）
    """
    conn = _get_cached_db_connection(host, port, dbname, user, '', schema)
    if conn is None:
        return ()
    try:
        return tuple(conn.get_tables())
    except Exception:
        return ()


@st.cache_data(ttl=30, show_spinner=False)
def get_cached_vector_tables(host, port, dbname, user, password, schema):
    """
    缓存向量表列表（30秒TTL）。

    Args:
        host, port, dbname, user, password, schema: 数据库连接参数（作为缓存 key）

    Returns:
        tuple: 向量表名元组
    """
    conn = _get_cached_db_connection(host, port, dbname, user, password, schema)
    if conn is None:
        return ()
    try:
        from database.vector_store import VectorStore
        vs = VectorStore(conn)
        return tuple(vs.get_vector_tables())
    except Exception:
        return ()


def invalidate_vector_tables_cache():
    """
    清除向量表/数据表相关缓存。

    在创建/删除/重命名/清空向量表后必须调用，否则页面 30 秒内仍显示旧数据。
    会同时清除 get_cached_vector_tables 和 get_cached_tables 的所有缓存条目。
    """
    try:
        # st.cache_data.clear() 会清除所有 @st.cache_data 装饰的函数缓存
        # 安全做法：仅清除涉及表列表的两个函数
        get_cached_vector_tables.clear()
        get_cached_tables.clear()
    except Exception as e:
        logger.warning(f"清除向量表缓存失败: {e}")


@st.cache_data(ttl=30, show_spinner=False)
def get_cached_all_tags(host, port, dbname, user, password, schema):
    """
    缓存标签列表（30秒TTL）。

    Args:
        host, port, dbname, user, password, schema: 数据库连接参数（作为缓存 key）

    Returns:
        tuple: 标签信息元组，每个元素为 (tag_name, prefix, recall_table, match_table)
    """
    conn = _get_cached_db_connection(host, port, dbname, user, password, schema)
    if conn is None:
        return ()
    try:
        from database.tag_manager import TagManager
        tag_mgr = TagManager(conn)
        tags = tag_mgr.get_all_tags()
        # 转为可哈希的元组形式
        return tuple(
            (t['tag_name'], t['prefix'], t['recall_table'], t['match_table'])
            for t in tags
        )
    except Exception:
        return ()


def _tags_tuple_to_list(tags_tuple):
    """将 get_cached_all_tags 返回的元组转换为原始 dict 列表格式"""
    return [
        {
            'tag_name': t[0],
            'prefix': t[1],
            'recall_table': t[2],
            'match_table': t[3]
        }
        for t in tags_tuple
    ]
