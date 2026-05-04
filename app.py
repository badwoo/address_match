"""
中文地址语义匹配系统 - Streamlit 主应用入口
================================================

项目目标：实现150万企业表数据和1300万标准地址数据通过地址匹配，获取标准地址的房号

项目架构：
    阶段1：数据粗召回 - 通过向量相似度检索每个企业前N条最相似的标准地址
    阶段2：数据精排匹配 - 使用MGeo精排模型对召回结果进行精准匹配

技术栈：
    - Streamlit: 前端界面框架
    - PostgreSQL + pgvector: 向量数据库存储与检索
    - MGeo模型: 地址向量化和相似度匹配
    - Python: 后端业务逻辑

主要功能模块：
    1. 数据库配置 - 配置PostgreSQL连接参数
    2. 向量预处理 - 企业表和标准地址表向量化
    3. 地址匹配 - 两阶段匹配（粗召回 + MGeo精排）
    4. 结果管理 - 匹配结果展示与统计
    5. 系统日志 - 日志查看和向量调试测试
"""

import streamlit as st
import pandas as pd
import time
import threading
from database.connection import DBConnection
from database.data_loader import DataLoader
from database.vector_store import VectorStore
from config import Config
from utils.logger import logger, setup_logger

# 初始化日志文件输出
setup_logger()

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

def _next_page(key, total_pages_key):
    """翻页回调：下一页"""
    total = st.session_state.get(total_pages_key, 1)
    if key in st.session_state and st.session_state[key] < total:
        st.session_state[key] += 1

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

    # 数据库连接配置
    if 'db_config' not in st.session_state:
        st.session_state.db_config = {
            'host': 'localhost',
            'port': 5432,
            'schema': 'public',
            'dbname': 'postgres',
            'user': 'postgres',
            'password': '123456'
        }
    
    # 数据库连接状态
    if 'connected' not in st.session_state:
        st.session_state.connected = False
    
    # 当前选中的菜单
    if 'selected_menu' not in st.session_state:
        st.session_state.selected_menu = "数据库配置"
    
    # 向量化配置（企业表和标准地址表字段映射）
    if 'vec_config' not in st.session_state:
        st.session_state.vec_config = {
            'enterprise_table': '',      # 企业表名
            'enterprise_id_col': '',     # 企业标识字段
            'enterprise_name_col': '',   # 企业名字段
            'enterprise_address_col': '',# 企业地址字段
            'standard_table': '',        # 标准地址表名
            'standard_id_col': '',       # 地址编码字段
            'standard_address_col': '',  # 标准地址字段
            'standard_room_col': ''      # 房屋编码字段
        }
    
    # 匹配配置
    if 'matching_config' not in st.session_state:
        st.session_state.matching_config = {
            'enterprise_vector_table': '',  # 企业向量表名
            'standard_vector_table': '',    # 标准地址向量表名
            'recall_top_n': 10,            # 粗召回数量
            'similarity_threshold': 0.7     # 相似度阈值
        }
    
    # 匹配任务状态
    if 'matching_status' not in st.session_state:
        st.session_state.matching_status = {
            'is_running': False,
            'processed_count': 0,
            'total_count': 0,
            'current_stage': '',
            'progress': 0.0,
            'speed': 0.0,
            'remaining_time': 0.0,
            'status_message': '',
            'error_message': '',
            'start_time': None,  # 开始时间
            'recall_completed': False,  # 粗召回是否完成
            'ranking_completed': False,  # 精排是否完成
            'ranking_ui_shown': False,  # 精排完成UI是否已显示
            'recall_count': 0,  # 召回结果数量
            'match_count': 0  # 匹配结果数量
        }
    
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
        st.session_state.mgeo_similarity_status = {
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
            'input_type': 'file',
            'source_table': '',
            'copy_table': ''
        }

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

def show_db_config():
    """数据库配置页面：配置PostgreSQL连接参数并测试连接"""
    st.subheader("数据库配置")
    
    with st.form("db_config_form"):
        # 第一行：数据库主机 + 端口
        col1, col2 = st.columns(2)
        with col1:
            st.session_state.db_config['host'] = st.text_input("数据库主机", st.session_state.db_config['host'])
        with col2:
            st.session_state.db_config['port'] = st.number_input("端口", value=st.session_state.db_config['port'], min_value=1, max_value=65535)
        
        # 第二行：数据库名 + 模式
        col3, col4 = st.columns(2)
        with col3:
            st.session_state.db_config['dbname'] = st.text_input("数据库名", st.session_state.db_config['dbname'])
        with col4:
            st.session_state.db_config['schema'] = st.text_input("模式", st.session_state.db_config['schema'])
        
        # 第三行：用户名 + 密码
        col5, col6 = st.columns(2)
        with col5:
            st.session_state.db_config['user'] = st.text_input("用户名", st.session_state.db_config['user'])
        with col6:
            st.session_state.db_config['password'] = st.text_input("密码", st.session_state.db_config['password'], type='password')
        
        submitted = st.form_submit_button("测试连接")
        if submitted:
            db_conn = DBConnection(
                host=st.session_state.db_config['host'],
                port=st.session_state.db_config['port'],
                schema=st.session_state.db_config['schema'],
                dbname=st.session_state.db_config['dbname'],
                user=st.session_state.db_config['user'],
                password=st.session_state.db_config['password']
            )
            
            if db_conn.test_connection():
                st.success("数据库连接成功！")
                st.session_state.connected = True
                st.session_state.db_conn = db_conn
                logger.info("Database connection successful")
            else:
                st.error("数据库连接失败，请检查配置")
    
    # 连接成功后显示数据库表信息
    if st.session_state.get('connected'):
        st.success("数据库已连接")
        try:
            tables = st.session_state.db_conn.get_tables()
            st.write(f"数据库中共有 {len(tables)} 个数据表")
            
            selected_table = st.selectbox("查看表结构", tables)
            if selected_table:
                columns = st.session_state.db_conn.get_columns(selected_table)
                df = pd.DataFrame(columns, columns=["字段名", "数据类型"])
                st.dataframe(df)
        except Exception as e:
            st.error(f"获取表信息失败: {str(e)}")

def show_vector_preprocess():
    """向量预处理页面：配置企业表和标准地址表的字段映射，执行向量化"""
    if not st.session_state.connected:
        st.warning("⚠️ 向量预处理功能需要数据库连接，请先在【数据库配置】页面配置并连接数据库")
        return
    
    db_config = st.session_state.db_config
    db_conn = DBConnection(
        host=db_config['host'],
        port=db_config['port'],
        schema=db_config['schema'],
        dbname=db_config['dbname'],
        user=db_config['user'],
        password=db_config['password']
    )
    
    if not db_conn.connect():
        st.error("无法连接数据库，请检查配置")
        return
    
    try:
        tables = db_conn.get_tables()
        if not tables:
            st.warning("数据库中没有可用的数据表")
            db_conn.close()
            return
    except Exception as e:
        st.error(f"获取数据表列表失败: {str(e)}")
        db_conn.close()
        return
    
    # 企业表向量化配置
    with st.expander("企业表向量化配置", expanded=True):
        col1, col2, col3 = st.columns(3)
        
        with col1:
            enterprise_table = st.selectbox(
                "选择企业表", 
                [''] + tables, 
                index=tables.index(st.session_state.vec_config['enterprise_table']) + 1 if st.session_state.vec_config['enterprise_table'] in tables else 0,
                key='enterprise_table_vec'
            )
            
            # 检测企业表是否变化，变化时重置字段选择为第一个字段
            if enterprise_table != st.session_state.vec_config.get('enterprise_table'):
                st.session_state.vec_config['enterprise_id_col'] = ''
                st.session_state.vec_config['enterprise_name_col'] = ''
                st.session_state.vec_config['enterprise_address_col'] = ''
                # 清除Streamlit selectbox缓存的值，使其重新使用默认值
                for key in ['enterprise_id_vec', 'enterprise_name_vec', 'enterprise_addr_vec']:
                    if key in st.session_state:
                        del st.session_state[key]
            
            st.session_state.vec_config['enterprise_table'] = enterprise_table
        
        enterprise_columns = []
        if enterprise_table:
            try:
                enterprise_columns = [col[0] for col in db_conn.get_columns(enterprise_table)]
            except Exception as e:
                st.error(f"获取企业表字段失败: {str(e)}")
                enterprise_columns = []
        
        with col2:
            if enterprise_columns:
                id_col_index = 0
                enterprise_id_col = st.selectbox(
                    "企业标识字段", 
                    enterprise_columns, 
                    index=id_col_index,
                    key='enterprise_id_vec'
                )
                st.session_state.vec_config['enterprise_id_col'] = enterprise_id_col
            else:
                st.selectbox("企业标识字段", ['请先选择企业表'], index=0, disabled=True)
                st.session_state.vec_config['enterprise_id_col'] = ''
        
        with col3:
            if enterprise_columns:
                name_col_index = 0
                enterprise_name_col = st.selectbox(
                    "企业名字段", 
                    enterprise_columns, 
                    index=name_col_index,
                    key='enterprise_name_vec'
                )
                st.session_state.vec_config['enterprise_name_col'] = enterprise_name_col
                
                addr_col_index = 0
                enterprise_address_col = st.selectbox(
                    "企业地址字段", 
                    enterprise_columns, 
                    index=addr_col_index,
                    key='enterprise_addr_vec'
                )
                st.session_state.vec_config['enterprise_address_col'] = enterprise_address_col
            else:
                st.selectbox("企业名字段", ['请先选择企业表'], index=0, disabled=True)
                st.selectbox("企业地址字段", ['请先选择企业表'], index=0, disabled=True)
                st.session_state.vec_config['enterprise_name_col'] = ''
                st.session_state.vec_config['enterprise_address_col'] = ''
    
    # 标准地址表向量化配置
    with st.expander("标准地址表向量化配置", expanded=True):
        col1, col2, col3 = st.columns(3)
        
        with col1:
            standard_table = st.selectbox(
                "选择标准地址表", 
                [''] + tables, 
                index=tables.index(st.session_state.vec_config['standard_table']) + 1 if st.session_state.vec_config['standard_table'] in tables else 0,
                key='standard_table_vec'
            )
            
            # 检测标准地址表是否变化，变化时重置字段选择为第一个字段
            if standard_table != st.session_state.vec_config.get('standard_table'):
                st.session_state.vec_config['standard_id_col'] = ''
                st.session_state.vec_config['standard_address_col'] = ''
                st.session_state.vec_config['standard_room_col'] = ''
                # 清除Streamlit selectbox缓存的值，使其重新使用默认值
                for key in ['standard_id_vec', 'standard_addr_vec', 'standard_room_vec']:
                    if key in st.session_state:
                        del st.session_state[key]
            
            st.session_state.vec_config['standard_table'] = standard_table
        
        standard_columns = []
        if standard_table:
            try:
                standard_columns = [col[0] for col in db_conn.get_columns(standard_table)]
            except Exception as e:
                st.error(f"获取标准地址表字段失败: {str(e)}")
                standard_columns = []
        
        with col2:
            if standard_columns:
                standard_id_col = st.selectbox(
                    "地址编码字段", 
                    standard_columns, 
                    index=0,
                    key='standard_id_vec'
                )
                st.session_state.vec_config['standard_id_col'] = standard_id_col
                
                standard_address_col = st.selectbox(
                    "标准地址字段", 
                    standard_columns, 
                    index=0,
                    key='standard_addr_vec'
                )
                st.session_state.vec_config['standard_address_col'] = standard_address_col
            else:
                st.selectbox("地址编码字段", ['请先选择标准地址表'], index=0, disabled=True)
                st.selectbox("标准地址字段", ['请先选择标准地址表'], index=0, disabled=True)
                st.session_state.vec_config['standard_id_col'] = ''
                st.session_state.vec_config['standard_address_col'] = ''
        
        with col3:
            if standard_columns:
                room_col_index = 0
                standard_room_col = st.selectbox(
                    "房屋编码字段", 
                    standard_columns, 
                    index=room_col_index,
                    key='standard_room_vec'
                )
                st.session_state.vec_config['standard_room_col'] = standard_room_col
            else:
                st.selectbox("房屋编码字段", ['请先选择标准地址表'], index=0, disabled=True)
                st.session_state.vec_config['standard_room_col'] = ''
    
    # 显示向量表统计
    vector_store = VectorStore(db_conn)
    enterprise_count = vector_store.get_vector_count(Config.ENTERPRISE_VECTOR_TABLE)
    standard_count = vector_store.get_vector_count(Config.STANDARD_VECTOR_TABLE)
    
    st.write(f"企业向量表记录数: {enterprise_count}")
    st.write(f"标准地址向量表记录数: {standard_count}")
    
    st.divider()
    
    # 向量表管理操作
    with st.expander("向量表管理", expanded=True):
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            if st.button("创建企业向量表"):
                with st.spinner("正在创建企业向量表..."):
                    if vector_store.create_vector_table(Config.ENTERPRISE_VECTOR_TABLE, table_type='enterprise'):
                        vector_store.create_vector_index(Config.ENTERPRISE_VECTOR_TABLE, 'idx_enterprise_vector')
                        st.success("企业向量表及索引创建成功")
        
        with col2:
            if st.button("创建标准地址向量表"):
                with st.spinner("正在创建标准地址向量表..."):
                    if vector_store.create_vector_table(Config.STANDARD_VECTOR_TABLE, table_type='standard'):
                        vector_store.create_vector_index(Config.STANDARD_VECTOR_TABLE, 'idx_standard_vector')
                        st.success("标准地址向量表及索引创建成功")
        
        with col3:
            if st.button("清空企业向量表"):
                if vector_store.truncate_vector_table(Config.ENTERPRISE_VECTOR_TABLE):
                    st.success("企业向量表已清空")
        
        with col4:
            if st.button("清空标准地址向量表"):
                if vector_store.truncate_vector_table(Config.STANDARD_VECTOR_TABLE):
                    st.success("标准地址向量表已清空")
        
        st.subheader("删除向量表")
        vector_tables = vector_store.get_vector_tables()
        if vector_tables:
            selected_table = st.selectbox("选择要删除的向量表", vector_tables)
            if st.button("删除选中的向量表"):
                if st.session_state.get('confirm_delete'):
                    if vector_store.drop_vector_table(selected_table):
                        st.success(f"向量表 {selected_table} 删除成功")
                        st.session_state.confirm_delete = False
                else:
                    st.warning(f"确定要删除向量表 {selected_table} 吗？此操作不可撤销！")
                    st.session_state.confirm_delete = True
        else:
            st.info("没有找到向量表")
    
    st.divider()
    
    # 向量化执行区域
    st.subheader("开始向量化")
    vec_device = _render_device_selector(key='vec_device_selector')
    batch_size = st.number_input("处理批次大小", value=1000, min_value=100, max_value=10000)
    
    col1, col2 = st.columns(2)
    with col1:
        if st.button("企业表向量化"):
            process_enterprise_vectorization(
                st.session_state.vec_config['enterprise_table'], 
                st.session_state.vec_config['enterprise_id_col'], 
                st.session_state.vec_config['enterprise_name_col'], 
                st.session_state.vec_config['enterprise_address_col'], 
                batch_size,
                vec_device
            )
    
    with col2:
        if st.button("标准地址表向量化"):
            process_standard_vectorization(
                st.session_state.vec_config['standard_table'], 
                st.session_state.vec_config['standard_id_col'], 
                st.session_state.vec_config['standard_address_col'], 
                st.session_state.vec_config['standard_room_col'],
                batch_size,
                vec_device
            )
    
    db_conn.close()

def process_enterprise_vectorization(enterprise_table, enterprise_id_col, enterprise_name_col, enterprise_address_col, batch_size, device=None):
    if not enterprise_table or not enterprise_id_col or not enterprise_name_col or not enterprise_address_col:
        st.error("请先选择企业表和对应的字段")
        return
    
    if device is None:
        device = st.session_state.get('selected_device', 'cpu')
    
    db_config = st.session_state.db_config
    if not db_config.get('host') or not db_config.get('dbname'):
        st.error("请先配置并连接数据库")
        return
    
    start_time = time.time()
    start_datetime = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
    
    status_container = st.empty()
    progress_bar = st.progress(0)
    status_text = st.empty()
    speed_text = st.empty()
    elapsed_text = st.empty()
    eta_text = st.empty()
    
    status_container.info("开始企业表向量化处理...")
    
    try:
        status_container.info("连接数据库...")
        working_conn = DBConnection(
            host=db_config['host'],
            port=db_config['port'],
            schema=db_config['schema'],
            dbname=db_config['dbname'],
            user=db_config['user'],
            password=db_config['password']
        )
        
        if not working_conn.connect():
            status_container.error("无法连接数据库，请检查配置")
            return
        
        status_container.info("数据库连接成功")
        
        working_data_loader = DataLoader(working_conn)
        
        status_container.info("获取有效地址数量...")
        total_count = working_data_loader.get_valid_address_count(enterprise_table, enterprise_address_col)
        status_container.write(f"有效地址数量: {total_count:,}")
        
        if total_count == 0:
            status_container.warning("企业表中没有有效的地址数据")
            working_conn.close()
            return
        
        estimated_batches = (total_count + batch_size - 1) // batch_size
        status_container.write(f"预计处理批次: {estimated_batches:,} 批")
        
        status_container.info("加载向量化模型...（首次加载可能需要几分钟）")
        from model.embedding import AddressEmbedder
        import torch
        if device == 'cuda' and not torch.cuda.is_available():
            logger.warning("用户选择GPU模式但CUDA不可用，切换到CPU模式")
            device = 'cpu'
        embedder = AddressEmbedder(device=device)
        model_load_time = time.time() - start_time
        vector_dim = embedder.get_vector_dim()
        status_container.info(f"向量化模型加载成功（耗时 {model_load_time:.2f} 秒）")
        status_container.info(f"模型输出向量维度: {vector_dim}")
        device_label = "🖥️ GPU模式运行" if device == 'cuda' else "💻 CPU模式运行"
        st.caption(f"当前运行模式: {device_label}")
        
        status_container.info("检查企业向量表...")
        working_vector_store = VectorStore(working_conn)
        
        existing_dim = working_vector_store.check_vector_table_dimension(Config.ENTERPRISE_VECTOR_TABLE)
        if existing_dim is not None and existing_dim != vector_dim:
            status_container.warning(f"现有向量表维度({existing_dim})与模型输出维度({vector_dim})不匹配，将重建向量表")
            working_vector_store.drop_vector_table(Config.ENTERPRISE_VECTOR_TABLE)
        
        working_vector_store.create_vector_table_with_dim(Config.ENTERPRISE_VECTOR_TABLE, vector_dim, table_type='enterprise')
        
        processed_count = 0
        batch_num = 0
        
        status_text.text(f"开始企业表向量化，共 {total_count:,} 条地址")
        
        for df in working_data_loader.load_enterprise_data(
            enterprise_table, enterprise_id_col, enterprise_name_col, enterprise_address_col, batch_size
        ):
            batch_num += 1
            
            addresses = df['address'].tolist()
            source_ids = df['id'].tolist()
            names = df['name'].tolist()
            
            vectors = embedder.encode(addresses)
            working_vector_store.insert_vectors(vectors, source_ids, addresses, Config.ENTERPRISE_VECTOR_TABLE, names, table_type='enterprise')
            
            processed_count += len(addresses)
            progress = processed_count / total_count
            progress_bar.progress(min(progress, 1.0))
            
            elapsed_time = time.time() - start_time
            speed = processed_count / elapsed_time if elapsed_time > 0 else 0
            
            if speed > 0:
                remaining = (total_count - processed_count) / speed
                eta_text.text(f"⏳ 预计剩余时间: {format_time(remaining)}")
            
            elapsed_text.text(f"⏱ 已执行时间: {format_time(elapsed_time)}")
            speed_text.text(f"⚡ 处理速度: {speed:.2f} 条/秒")
            status_text.text(f"📦 批次 {batch_num}/{estimated_batches}: 已处理 {processed_count:,}/{total_count:,} ({progress * 100:.1f}%)")
            
            logger.info(f"Enterprise vectorized batch {batch_num}: {processed_count}/{total_count} addresses")
        
        status_container.info("创建企业向量索引...")
        working_vector_store.create_vector_index(Config.ENTERPRISE_VECTOR_TABLE, 'idx_enterprise_vector')
        
        total_time = time.time() - start_time
        end_datetime = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
        avg_speed = processed_count / total_time if total_time > 0 else 0
        
        status_text.text(f"企业表向量化完成！共处理 {processed_count:,} 条地址")
        speed_text.text(f"平均处理速度: {avg_speed:.2f} 条/秒")
        elapsed_text.text(f"总耗时: {format_time(total_time)}")
        eta_text.text(f"开始时间: {start_datetime}")
        status_container.success(f"企业表向量化完成！\n开始时间: {start_datetime}\n结束时间: {end_datetime}")
        logger.info(f"Enterprise vectorization completed: {processed_count} addresses in {total_time:.2f} seconds")
        
    except Exception as e:
        st.error(f"企业表向量化失败: {str(e)}")
        import traceback
        st.write(f"详细错误: {traceback.format_exc()}")
        logger.error(f"Enterprise vectorization failed: {str(e)}")
    finally:
        if 'working_conn' in locals() and working_conn:
            working_conn.close()

def process_standard_vectorization(standard_table, standard_id_col, standard_address_col, standard_room_col, batch_size, device=None):
    if not standard_table or not standard_id_col or not standard_address_col:
        st.error("请先选择标准地址表和对应的字段")
        return
    
    if device is None:
        device = st.session_state.get('selected_device', 'cpu')
    
    db_config = st.session_state.db_config
    if not db_config.get('host') or not db_config.get('dbname'):
        st.error("请先配置并连接数据库")
        return
    
    start_time = time.time()
    start_datetime = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
    
    status_container = st.empty()
    progress_bar = st.progress(0)
    status_text = st.empty()
    speed_text = st.empty()
    elapsed_text = st.empty()
    eta_text = st.empty()
    
    status_container.info("开始标准地址表向量化处理...")
    
    try:
        status_container.info("连接数据库...")
        working_conn = DBConnection(
            host=db_config['host'],
            port=db_config['port'],
            schema=db_config['schema'],
            dbname=db_config['dbname'],
            user=db_config['user'],
            password=db_config['password']
        )
        
        if not working_conn.connect():
            status_container.error("无法连接数据库，请检查配置")
            return
        
        status_container.info("数据库连接成功")
        
        working_data_loader = DataLoader(working_conn)
        
        status_container.info("获取有效地址数量...")
        total_count = working_data_loader.get_valid_address_count(standard_table, standard_address_col)
        status_container.write(f"有效地址数量: {total_count:,}")
        
        if total_count == 0:
            status_container.warning("标准地址表中没有有效的地址数据")
            working_conn.close()
            return
        
        estimated_batches = (total_count + batch_size - 1) // batch_size
        status_container.write(f"预计处理批次: {estimated_batches:,} 批")
        
        status_container.info("加载向量化模型...（首次加载可能需要几分钟）")
        from model.embedding import AddressEmbedder
        import torch
        if device == 'cuda' and not torch.cuda.is_available():
            logger.warning("用户选择GPU模式但CUDA不可用，切换到CPU模式")
            device = 'cpu'
        embedder = AddressEmbedder(device=device)
        model_load_time = time.time() - start_time
        vector_dim = embedder.get_vector_dim()
        status_container.info(f"向量化模型加载成功（耗时 {model_load_time:.2f} 秒）")
        status_container.info(f"模型输出向量维度: {vector_dim}")
        device_label = "🖥️ GPU模式运行" if device == 'cuda' else "💻 CPU模式运行"
        st.caption(f"当前运行模式: {device_label}")
        
        status_container.info("检查标准地址向量表...")
        working_vector_store = VectorStore(working_conn)
        
        existing_dim = working_vector_store.check_vector_table_dimension(Config.STANDARD_VECTOR_TABLE)
        if existing_dim is not None and existing_dim != vector_dim:
            status_container.warning(f"现有向量表维度({existing_dim})与模型输出维度({vector_dim})不匹配，将重建向量表")
            working_vector_store.drop_vector_table(Config.STANDARD_VECTOR_TABLE)
        
        working_vector_store.create_vector_table_with_dim(Config.STANDARD_VECTOR_TABLE, vector_dim, table_type='standard')
        
        processed_count = 0
        batch_num = 0
        
        status_text.text(f"开始标准地址表向量化，共 {total_count:,} 条地址")
        
        for df in working_data_loader.load_standard_addresses(standard_table, standard_id_col, standard_address_col, standard_room_col, batch_size):
            batch_num += 1
            
            addresses = df['address'].tolist()
            source_ids = df['id'].tolist()
            room_nos = df.get('room_no', [''] * len(addresses)).tolist()
            
            vectors = embedder.encode(addresses)
            working_vector_store.insert_vectors(vectors, source_ids, addresses, Config.STANDARD_VECTOR_TABLE, room_nos, table_type='standard')
            
            processed_count += len(addresses)
            progress = processed_count / total_count
            progress_bar.progress(min(progress, 1.0))
            
            elapsed_time = time.time() - start_time
            speed = processed_count / elapsed_time if elapsed_time > 0 else 0
            
            if speed > 0:
                remaining = (total_count - processed_count) / speed
                eta_text.text(f"⏳ 预计剩余时间: {format_time(remaining)}")
            
            elapsed_text.text(f"⏱ 已执行时间: {format_time(elapsed_time)}")
            speed_text.text(f"⚡ 处理速度: {speed:.2f} 条/秒")
            status_text.text(f"📦 批次 {batch_num}/{estimated_batches}: 已处理 {processed_count:,}/{total_count:,} ({progress * 100:.1f}%)")
            
            logger.info(f"Standard vectorized batch {batch_num}: {processed_count}/{total_count} addresses")
        
        status_container.info("创建标准地址向量索引...")
        working_vector_store.create_vector_index(Config.STANDARD_VECTOR_TABLE, 'idx_standard_vector')
        
        total_time = time.time() - start_time
        end_datetime = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
        avg_speed = processed_count / total_time if total_time > 0 else 0
        
        status_text.text(f"标准地址表向量化完成！共处理 {processed_count:,} 条地址")
        speed_text.text(f"平均处理速度: {avg_speed:.2f} 条/秒")
        elapsed_text.text(f"总耗时: {format_time(total_time)}")
        eta_text.text(f"开始时间: {start_datetime}")
        status_container.success(f"标准地址表向量化完成！\n开始时间: {start_datetime}\n结束时间: {end_datetime}")
        logger.info(f"Standard address vectorization completed: {processed_count} addresses in {total_time:.2f} seconds")
        
    except Exception as e:
        st.error(f"标准地址表向量化失败: {str(e)}")
        import traceback
        st.write(f"详细错误: {traceback.format_exc()}")
        logger.error(f"Standard address vectorization failed: {str(e)}")
    finally:
        if 'working_conn' in locals() and working_conn:
            working_conn.close()

def show_address_matching():
    db_config = st.session_state.db_config
    
    device = _render_device_selector(key='match_device_selector')
    
    # 确保 matching_status 已初始化
    if 'matching_status' not in st.session_state:
        st.session_state.matching_status = {
            'is_running': False,
            'processed_count': 0,
            'total_count': 0,
            'current_stage': '',
            'progress': 0.0,
            'speed': 0.0,
            'remaining_time': 0.0,
            'status_message': '',
            'error_message': '',
            'start_time': None,
            'recall_completed': False,
            'ranking_completed': False,
            'ranking_ui_shown': False,
            'recall_count': 0,
            'match_count': 0
        }
    
    # 确保 recall_status 已初始化
    if 'recall_status' not in st.session_state:
        st.session_state.recall_status = {
            'completed': False,
            'start_time': None,
            'end_time': None,
            'recall_count': 0,
            'candidate_count': 0
        }
    
    matching_status = st.session_state.matching_status
    recall_status = st.session_state.recall_status
    
    # ========== 回调触发刷新机制 ==========
    # 在后台线程回调中设置完成标志，主线程检测到后调用st.rerun()
    if st.session_state.get('recall_finished_trigger'):
        logger.info("[刷新] 检测到粗召回完成触发器，清除并刷新页面")
        del st.session_state['recall_finished_trigger']
        st.rerun()
    
    # ========== 优先检测任务完成状态（在判断运行状态之前）==========
    # 当后台任务完成(is_running=False)但状态标志未更新时，在此处理
    # 这样即使 is_running 已经变为 False，也能正确检测到任务完成
    
    # 关键修改：如果recall_completed已经为True，说明已经完成粗召回，
    # 此时不应该再重新检测粗召回完成状态，避免干扰MGeo精排任务的启动
    if not matching_status['is_running'] and not matching_status.get('recall_completed'):
        need_rerun = False
        
        # 检查是否是MGeo精排阶段，如果是则跳过粗召回完成检测
        is_mgeo_stage = matching_status.get('current_stage') == 'MGeo精确匹配' or matching_status.get('ranking_completed')
        
        # 粗召回完成检测：只有在recall_completed为False且不是MGeo精排阶段时才检测
        if (not is_mgeo_stage
            and matching_status.get('current_stage') in ['数据粗召回', '数据粗召回完成'] 
            and not matching_status.get('recall_completed')):
            logger.info("[完成检测] 检测粗召回完成状态，查询数据库验证")
            
            try:
                db_config = st.session_state.db_config
                check_conn = DBConnection(
                    host=db_config['host'],
                    port=db_config['port'],
                    schema=db_config['schema'],
                    dbname=db_config['dbname'],
                    user=db_config['user'],
                    password=db_config['password']
                )
                if check_conn.connect():
                    recall_table = Config.RECALL_RESULTS_TABLE
                    # 查询企业数量（去重）
                    enterprise_cursor = check_conn.execute(f"SELECT COUNT(DISTINCT enterprise_id) FROM {recall_table}")
                    enterprise_count = enterprise_cursor.fetchone()['count'] if enterprise_cursor else 0
                    
                    # 查询总记录数
                    cursor = check_conn.execute(f"SELECT COUNT(*) FROM {recall_table}")
                    recall_count = cursor.fetchone()['count'] if cursor else 0
                    
                    # 查询有效候选地址数
                    candidate_cursor = check_conn.execute(f"SELECT COUNT(*) FROM {recall_table} WHERE standard_id IS NOT NULL")
                    candidate_count = candidate_cursor.fetchone()['count'] if candidate_cursor else 0
                    
                    check_conn.close()
                    
                    logger.info(f"[完成检测] recall_results表记录数: {recall_count}, 企业数: {enterprise_count}, 候选地址数: {candidate_count}")
                    
                    # 只有当数据库中有数据时才标记完成
                    if recall_count > 0:
                        st.session_state.matching_status = {
                            'is_running': False,
                            'processed_count': enterprise_count,
                            'current_stage': '数据粗召回完成',
                            'progress': 1.0,
                            'speed': 0.0,
                            'remaining_time': 0.0,
                            'status_message': '粗召回完成',
                            'error_message': '',
                            'start_time': st.session_state.matching_status.get('start_time'),
                            'recall_completed': True,
                            'ranking_completed': False,
                            'ranking_ui_shown': False,
                            'recall_count': enterprise_count,
                            'match_count': 0
                        }
                        st.session_state.recall_status = {
                            'completed': True,
                            'end_time': time.time(),
                            'recall_count': enterprise_count,
                            'candidate_count': candidate_count,
                            'start_time': st.session_state.matching_status.get('start_time')
                        }
                        need_rerun = True
                        logger.info("[完成检测] 粗召回完成状态已更新")
                    else:
                        logger.warning("[完成检测] recall_results表为空，等待后台线程写入...")
            except Exception as e:
                logger.error(f"[完成检测] 查询recall_results统计失败: {str(e)}")
                st.session_state.matching_status.update({
                    'recall_completed': True,
                    'is_running': False
                })
                st.session_state.recall_status.update({
                    'completed': True,
                    'end_time': time.time()
                })
                need_rerun = True
        
        if need_rerun:
            logger.info("[完成检测] 状态已更新，刷新页面...")
            st.rerun()
    
    # MGeo精排完成检测：单独处理，不依赖上面的条件
    if not matching_status['is_running'] and matching_status.get('ranking_completed') and not matching_status.get('ranking_ui_shown'):
        logger.info("[完成检测] MGeo精确匹配已完成，更新UI状态")
        st.session_state.matching_status['ranking_ui_shown'] = True
        st.rerun()
    
    # 显示匹配执行状态
    if matching_status['is_running']:
        current_stage = matching_status.get('current_stage', '')
        is_mgeo_ranking = current_stage == 'MGeo精确匹配'
        
        if is_mgeo_ranking and 'running_ranking_status' in st.session_state and st.session_state.running_ranking_status:
            try:
                ranking_stat = st.session_state.running_ranking_status.get_status()
                st.session_state.matching_status.update({
                    'is_running': ranking_stat['is_running'],
                    'processed_count': ranking_stat['processed_count'],
                    'total_count': ranking_stat['total_count'],
                    'current_stage': ranking_stat['current_stage'],
                    'progress': ranking_stat['progress'],
                    'speed': ranking_stat['speed'],
                    'remaining_time': ranking_stat['remaining_time'],
                    'status_message': ranking_stat['status_message'],
                    'error_message': ranking_stat['error_message'],
                    'ranking_completed': ranking_stat['ranking_completed'],
                    'match_count': ranking_stat['match_count']
                })
                matching_status = st.session_state.matching_status
            except Exception as e:
                logger.error(f"获取精排状态失败: {e}")
        elif 'matcher' in st.session_state and st.session_state.matcher:
            try:
                matcher_status = st.session_state.matcher.get_status()
                st.session_state.matching_status.update({
                    'is_running': matcher_status['is_running'],
                    'processed_count': matcher_status['processed_count'],
                    'total_count': matcher_status['total_count'],
                    'current_stage': matcher_status['current_stage'],
                    'progress': matcher_status['progress'],
                    'speed': matcher_status['speed'],
                    'remaining_time': matcher_status['remaining_time'],
                    'status_message': matcher_status['status_message'],
                    'error_message': matcher_status['error_message']
                })
                matching_status = st.session_state.matching_status
            except Exception as e:
                logger.error(f"获取匹配器状态失败: {e}")
        
        st.markdown("<div style='background-color: #fef3c7; padding: 20px; border-radius: 10px; margin-bottom: 20px;'>", unsafe_allow_html=True)
        st.subheader("📊 匹配执行状态")
        
        # 判断当前阶段
        is_recall_stage = matching_status['current_stage'] == '数据粗召回' or matching_status['current_stage'] == '数据粗召回完成'
        is_mgeo_stage = matching_status['current_stage'] == 'MGeo精确匹配'
        
        # 显示开始时间和已运行时间
        if matching_status['start_time']:
            start_time_str = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(matching_status['start_time']))
            elapsed = time.time() - matching_status['start_time']
            st.write(f"**开始时间**: {start_time_str}")
            st.write(f"**已运行时间**: {format_time(elapsed)}")
        
        st.write(f"**当前阶段**: {matching_status['current_stage']}")
        
        # 粗召回阶段只显示简单进度条，不显示详细进度信息
        if is_recall_stage:
            # 粗召回使用JOIN LATERAL一次性完成，显示无限进度条
            st.progress(0)  # 显示一个空的进度条表示进行中
            st.info("🔄 正在执行批量召回，请稍候...")
        elif is_mgeo_stage:
            # MGeo精排阶段显示详细进度和实时统计
            progress_bar = st.progress(matching_status['progress'])
            st.write(f"**处理进度**: {matching_status['processed_count']:,}/{matching_status['total_count']:,} ({matching_status['progress'] * 100:.1f}%)")
            st.write(f"**处理速度**: {matching_status['speed']:.2f} 条/秒")
            st.write(f"**预计剩余时间**: {format_time(matching_status['remaining_time'])}")
            st.write(f"**实时匹配企业数量**: {matching_status['processed_count']:,} / {matching_status['total_count']:,}")
            st.write(f"**实时匹配总次数**: {matching_status['processed_count']:,}")
        else:
            # 其他阶段显示基本进度
            progress_bar = st.progress(matching_status['progress'])
            st.write(f"**处理进度**: {matching_status['processed_count']:,}/{matching_status['total_count']:,} ({matching_status['progress'] * 100:.1f}%)")
            st.write(f"**处理速度**: {matching_status['speed']:.2f} 条/秒")
            st.write(f"**预计剩余时间**: {format_time(matching_status['remaining_time'])}")
        
        col1, col2 = st.columns([1, 1])
        with col1:
            if st.button("⏹️ 取消匹配"):
                # 先停止匹配器
                if 'matcher' in st.session_state and st.session_state.matcher:
                    try:
                        st.session_state.matcher.stop()
                    except:
                        pass
                
                # 停止MGeo精排（如果存在）
                if 'running_ranking_status' in st.session_state and st.session_state.running_ranking_status:
                    try:
                        st.session_state.running_ranking_status.is_running = False
                    except:
                        pass
                
                # 使用update方法更新状态，而不是重新赋值
                st.session_state.matching_status.update({
                    'is_running': False,
                    'processed_count': 0,
                    'total_count': 0,
                    'current_stage': '',
                    'progress': 0.0,
                    'speed': 0.0,
                    'remaining_time': 0.0,
                    'status_message': '',
                    'error_message': '',
                    'start_time': None,
                    'recall_completed': False,
                    'ranking_completed': False,
                    'ranking_ui_shown': False,
                    'recall_count': 0,
                    'match_count': 0
                })
                # 重置recall_status
                st.session_state.recall_status.update({
                    'completed': False,
                    'start_time': None,
                    'end_time': None,
                    'recall_count': 0,
                    'candidate_count': 0
                })
                # 清理ranking_status
                if 'running_ranking_status' in st.session_state:
                    del st.session_state.running_ranking_status
                st.success("匹配已取消")
                st.rerun()
        
        with col2:
            st.info("🔄 匹配进行中...")
        
        st.markdown("</div>", unsafe_allow_html=True)
        
        st.subheader("地址匹配配置")
        with st.expander("参数配置（匹配进行中不可修改）", expanded=False):
            st.info("匹配正在进行中，参数配置暂时不可修改")
        
        # 添加自动刷新功能 - 使用Streamlit的自动刷新机制
        refresh_placeholder = st.empty()
        refresh_placeholder.info("页面将自动刷新以监测完成状态...")
        
        # 等待1秒后自动刷新
        time.sleep(1)
        st.rerun()
    
    # 粗召回完成后，显示结果和下一步操作按钮（但如果正在运行精排任务或已完成精排，则不显示）
    if recall_status['completed'] and not matching_status['ranking_completed'] and not matching_status['is_running'] and matching_status.get('current_stage') != 'MGeo精确匹配':
        st.markdown("<div style='background-color: #d1fae5; padding: 20px; border-radius: 10px; margin-bottom: 20px;'>", unsafe_allow_html=True)
        st.subheader("✅ 数据粗召回匹配完成")
        
        if recall_status['start_time'] and recall_status['end_time']:
            duration = recall_status['end_time'] - recall_status['start_time']
            st.write(f"**开始时间**: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(recall_status['start_time']))}")
            st.write(f"**结束时间**: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(recall_status['end_time']))}")
            st.write(f"**耗时**: {format_time(duration)}")
        
        st.write(f"**召回企业数**: {recall_status['recall_count']:,}")
        st.write(f"**候选地址总数**: {recall_status['candidate_count']:,}")
        
        st.markdown("---")
        st.markdown("**下一步操作**")
        
        col1, col2, col3 = st.columns(3)
        with col1:
            if st.button("📊 数据查看", help="查看召回结果数据"):
                st.session_state.selected_menu = "结果管理"
                st.session_state.result_management_active_tab = "粗召回数据"
                st.rerun()
        
        with col2:
            if st.button("▶️ 继续MGeo精确匹配", key='continue_mgeo', help="执行MGeo精确匹配，按企业分组比较企业地址和标准地址，找出最相似的数据"):
                start_mgeo_ranking(db_config, device)
        
        with col3:
            if st.button("↩️ 返回地址匹配", help="返回地址匹配页面"):
                reset_matching_status()
                st.rerun()
        
        st.markdown("</div>", unsafe_allow_html=True)
        
        # 显示重新匹配按钮
        if st.button("🔄 重新进行粗召回匹配"):
            # 清空recall_results表
            try:
                db_config = st.session_state.db_config
                db_conn = DBConnection(
                    host=db_config['host'],
                    port=db_config['port'],
                    schema=db_config['schema'],
                    dbname=db_config['dbname'],
                    user=db_config['user'],
                    password=db_config['password']
                )
                if db_conn.connect():
                    data_loader = DataLoader(db_conn)
                    data_loader.truncate_recall_table()
                    db_conn.close()
                    st.info("已清空召回结果表")
            except Exception as e:
                logger.error(f"清空召回表失败: {e}")
            
            # 重置状态
            st.session_state.recall_status = {
                'completed': False,
                'start_time': None,
                'end_time': None,
                'recall_count': 0,
                'candidate_count': 0
            }
            st.session_state.matching_status['recall_completed'] = False
            st.rerun()
        
        return
    
    # 精排完成后，显示最终结果
    if matching_status['ranking_completed']:
        st.markdown("<div style='background-color: #dbeafe; padding: 20px; border-radius: 10px; margin-bottom: 20px;'>", unsafe_allow_html=True)
        st.subheader("✅ MGeo精确匹配完成")
        st.write(f"**匹配结果数**: {matching_status['match_count']:,}")
        
        col1, col2, col3 = st.columns(3)
        with col1:
            if st.button("📊 查看匹配结果"):
                st.session_state.selected_menu = "结果管理"
                st.session_state.result_management_active_tab = "精排匹配结果"
                st.rerun()
        
        with col2:
            if st.button("🔄 重新开始完整匹配"):
                reset_matching_status()
                st.rerun()
        
        with col3:
            if st.button("↩️ 返回地址匹配"):
                reset_matching_status()
                st.rerun()
        
        st.markdown("</div>", unsafe_allow_html=True)
        return
    
    # 上部分：数据粗召回匹配
    st.markdown("<div style='background-color: #f0fdf4; padding: 20px; border-radius: 10px; margin-bottom: 20px;'>", unsafe_allow_html=True)
    st.subheader("🔍 数据粗召回匹配")
    
    if not st.session_state.connected:
        st.warning("⚠️ 数据粗召回匹配需要数据库连接，请先在【数据库配置】页面配置并连接数据库")
        st.markdown("</div>", unsafe_allow_html=True)
    else:
        db_conn = DBConnection(
            host=db_config['host'],
            port=db_config['port'],
            schema=db_config['schema'],
            dbname=db_config['dbname'],
            user=db_config['user'],
            password=db_config['password']
        )
        
        if not db_conn.connect():
            st.error("无法连接数据库，请检查配置")
            st.markdown("</div>", unsafe_allow_html=True)
        else:
            vector_store = VectorStore(db_conn)
            vector_tables = vector_store.get_vector_tables()
            
            with st.expander("向量表选择", expanded=True):
                col1, col2 = st.columns(2)
                with col1:
                    enterprise_vector_table = st.selectbox(
                        "选择企业向量表", 
                        [''] + vector_tables, 
                        index=vector_tables.index(st.session_state.matching_config['enterprise_vector_table']) + 1 if st.session_state.matching_config['enterprise_vector_table'] in vector_tables else 0,
                        key='enterprise_vector_match'
                    )
                    st.session_state.matching_config['enterprise_vector_table'] = enterprise_vector_table
                
                with col2:
                    standard_vector_table = st.selectbox(
                        "选择标准地址向量表", 
                        [''] + vector_tables, 
                        index=vector_tables.index(st.session_state.matching_config['standard_vector_table']) + 1 if st.session_state.matching_config['standard_vector_table'] in vector_tables else 0,
                        key='standard_vector_match'
                    )
                    st.session_state.matching_config['standard_vector_table'] = standard_vector_table
            
            with st.expander("匹配参数配置", expanded=True):
                col1, col2 = st.columns(2)
                with col1:
                    st.session_state.matching_config['recall_top_n'] = st.number_input(
                        "粗召回数量", 
                        value=st.session_state.matching_config['recall_top_n'],
                        min_value=1, 
                        max_value=100
                    )
                
                with col2:
                    st.session_state.matching_config['similarity_threshold'] = st.slider(
                        "相似度阈值", 
                        min_value=0.0, 
                        max_value=1.0, 
                        value=st.session_state.matching_config['similarity_threshold'],
                        step=0.01
                    )
                
                if device == 'cuda':
                    st.success("✅ 将使用GPU进行推理")
                else:
                    st.info("⚠️ 将使用CPU进行推理")
            
            if st.button("🚀 启动数据粗召回匹配", key='start_recall'):
                if not enterprise_vector_table or not standard_vector_table:
                    st.error("请先选择向量表")
                else:
                    start_recall_matching(db_config, device, enterprise_vector_table, standard_vector_table)
            
            db_conn.close()
    
    st.markdown("</div>", unsafe_allow_html=True)
    
    # 下部分：MGeo精确匹配
    st.markdown("<div style='background-color: #fef3c7; padding: 20px; border-radius: 10px;'>", unsafe_allow_html=True)
    st.subheader("🎯 MGeo精确匹配")
    
    if not st.session_state.connected:
        st.warning("⚠️ MGeo精确匹配需要数据库连接，请先在【数据库配置】页面配置并连接数据库")
    else:
        try:
            check_conn = DBConnection(
                host=db_config['host'],
                port=db_config['port'],
                schema=db_config['schema'],
                dbname=db_config['dbname'],
                user=db_config['user'],
                password=db_config['password']
            )
            if check_conn.connect():
                recall_cursor = check_conn.execute(f"SELECT COUNT(*) FROM {Config.RECALL_RESULTS_TABLE}")
                recall_count = recall_cursor.fetchone()['count'] if recall_cursor else 0
                check_conn.close()
                
                if recall_count > 0:
                    st.success(f"✅ 检测到召回结果数据：{recall_count:,} 条记录")
                    
                    if st.button("▶️ 启动MGeo精确匹配", key='start_mgeo'):
                        start_mgeo_ranking(db_config, device)
                else:
                    st.warning("⚠️ 未检测到召回结果数据，请先执行数据粗召回匹配")
        except Exception as e:
            st.error(f"检查召回结果失败: {str(e)}")
    
    st.markdown("</div>", unsafe_allow_html=True)

    # 第三部分：MGeo地址相似度匹配
    show_mgeo_similarity_matching(db_config, device)

def show_mgeo_similarity_matching(db_config, device):
    """
    MGeo地址相似度匹配页面

    独立的地址相似度匹配功能，支持文件上传和数据库表输入。
    直接调用MGeo模型对地址A和地址B进行逐行匹配。

    功能：
        1. 数据输入：支持上传表格/CSV文件或选择数据库表
        2. 地址字段选择：选择地址字段A和地址字段B
        3. 匹配执行：显示进度、时间等信息
        4. 结果查看：匹配完成后跳转至结果管理
    """
    st.markdown("<div style='background-color: #ede9fe; padding: 20px; border-radius: 10px;'>", unsafe_allow_html=True)
    st.subheader("🔗 MGeo地址相似度匹配")
    st.caption("独立匹配功能：直接调用MGeo模型对地址A和地址B进行相似度匹配，无需向量召回")

    sim_device = _render_device_selector(key='mgeo_sim_device_selector')
    device = sim_device

    if 'mgeo_similarity_status' not in st.session_state:
        st.session_state.mgeo_similarity_status = {
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
            'input_type': 'file',
            'source_table': '',
            'copy_table': ''
        }

    mgeo_sim_status = st.session_state.mgeo_similarity_status

    # 检测完成触发器
    if st.session_state.get('mgeo_similarity_finished_trigger'):
        logger.info("[MGeo相似度匹配] 检测到完成触发器，清除并刷新")
        del st.session_state['mgeo_similarity_finished_trigger']
        st.rerun()

    # 如果正在运行，显示进度
    if mgeo_sim_status['is_running']:
        if 'mgeo_similarity_matcher' in st.session_state and st.session_state.mgeo_similarity_matcher:
            try:
                matcher_stat = st.session_state.mgeo_similarity_matcher.get_status()
                st.session_state.mgeo_similarity_status.update({
                    'is_running': matcher_stat['is_running'],
                    'progress': matcher_stat['progress'],
                    'processed_count': matcher_stat['processed_count'],
                    'total_count': matcher_stat['total_count'],
                    'speed': matcher_stat['speed'],
                    'remaining_time': matcher_stat['remaining_time'],
                    'status_message': matcher_stat['status_message'],
                    'error_message': matcher_stat['error_message']
                })

                if matcher_stat.get('completed'):
                    end_time = matcher_stat.get('completion_end_time', time.time())
                    if matcher_stat.get('completion_success') and matcher_stat.get('completion_results'):
                        st.session_state.mgeo_similarity_status.update({
                            'is_running': False,
                            'completed': True,
                            'end_time': end_time,
                            'result_count': len(matcher_stat['completion_results']),
                            'status_message': '匹配完成',
                            'progress': 1.0
                        })
                        if mgeo_sim_status.get('input_type') == 'file':
                            st.session_state.mgeo_sim_match_results = matcher_stat['completion_results']
                        if matcher_stat.get('completion_source_table'):
                            st.session_state.mgeo_similarity_status.update({
                                'source_table': matcher_stat['completion_source_table'],
                                'copy_table': matcher_stat['completion_copy_table']
                            })
                    else:
                        st.session_state.mgeo_similarity_status.update({
                            'is_running': False,
                            'completed': False,
                            'end_time': end_time,
                            'error_message': matcher_stat.get('completion_message', ''),
                            'status_message': f"匹配失败: {matcher_stat.get('completion_message', '')}"
                        })

                mgeo_sim_status = st.session_state.mgeo_similarity_status
            except Exception as e:
                logger.error(f"获取MGeo相似度匹配状态失败: {e}")

        st.markdown("<div style='background-color: #fef3c7; padding: 15px; border-radius: 8px; margin-bottom: 15px;'>", unsafe_allow_html=True)
        st.subheader("📊 MGeo相似度匹配执行状态")

        if mgeo_sim_status['start_time']:
            start_time_str = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(mgeo_sim_status['start_time']))
            elapsed = time.time() - mgeo_sim_status['start_time']
            st.write(f"**开始时间**: {start_time_str}")
            st.write(f"**已运行时间**: {format_time(elapsed)}")

        progress_bar = st.progress(mgeo_sim_status['progress'])
        st.write(f"**处理进度**: {mgeo_sim_status['processed_count']:,}/{mgeo_sim_status['total_count']:,} ({mgeo_sim_status['progress'] * 100:.1f}%)")
        st.write(f"**处理速度**: {mgeo_sim_status['speed']:.2f} 条/秒")
        st.write(f"**预计剩余时间**: {format_time(mgeo_sim_status['remaining_time'])}")
        st.write(f"**状态**: {mgeo_sim_status['status_message']}")

        col1, col2 = st.columns(2)
        with col1:
            if st.button("⏹️ 取消匹配", key='cancel_mgeo_sim'):
                if 'mgeo_similarity_matcher' in st.session_state:
                    st.session_state.mgeo_similarity_matcher.stop()
                st.session_state.mgeo_similarity_status.update({
                    'is_running': False,
                    'progress': 0.0,
                    'status_message': '已取消',
                    'error_message': ''
                })
                st.success("匹配已取消")
                st.rerun()

        st.markdown("</div>", unsafe_allow_html=True)

        time.sleep(1)
        st.rerun()

    # 如果匹配完成，显示结果
    if mgeo_sim_status['completed']:
        st.markdown("<div style='background-color: #d1fae5; padding: 15px; border-radius: 8px; margin-bottom: 15px;'>", unsafe_allow_html=True)
        st.subheader("✅ MGeo地址相似度匹配完成")

        if mgeo_sim_status['start_time'] and mgeo_sim_status['end_time']:
            duration = mgeo_sim_status['end_time'] - mgeo_sim_status['start_time']
            st.write(f"**开始时间**: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(mgeo_sim_status['start_time']))}")
            st.write(f"**结束时间**: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(mgeo_sim_status['end_time']))}")
            st.write(f"**耗时**: {format_time(duration)}")

        st.write(f"**匹配结果数**: {mgeo_sim_status['result_count']:,}")

        input_type = mgeo_sim_status.get('input_type', 'file')

        if input_type == 'file':
            if 'mgeo_sim_match_results' in st.session_state and st.session_state.mgeo_sim_match_results:
                result_df = pd.DataFrame(st.session_state.mgeo_sim_match_results)
                
                st.subheader("📥 结果下载")
                dl_col1, dl_col2 = st.columns(2)
                with dl_col1:
                    try:
                        import io
                        excel_buffer = io.BytesIO()
                        with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
                            result_df.to_excel(writer, index=False, sheet_name='匹配结果')
                        excel_data = excel_buffer.getvalue()
                        st.download_button(
                            label="📥 下载Excel格式",
                            data=excel_data,
                            file_name=f"MGeo相似度匹配结果_{time.strftime('%Y%m%d_%H%M%S')}.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            key='download_mgeo_sim_result_excel'
                        )
                    except ImportError:
                        st.warning("导出Excel需要openpyxl库")
                with dl_col2:
                    try:
                        import io
                        csv_buffer = io.StringIO()
                        result_df.to_csv(csv_buffer, index=False, encoding='utf-8-sig')
                        csv_data = csv_buffer.getvalue()
                        st.download_button(
                            label="📥 下载CSV格式",
                            data=csv_data,
                            file_name=f"MGeo相似度匹配结果_{time.strftime('%Y%m%d_%H%M%S')}.csv",
                            mime="text/csv",
                            key='download_mgeo_sim_result_csv'
                        )
                    except Exception as e:
                        st.warning(f"导出CSV失败: {str(e)}")
            else:
                st.info("结果数据不可用")

            st.divider()
            col1, col2 = st.columns(2)
            with col1:
                if st.button("🔄 重新匹配", key='restart_mgeo_sim'):
                    st.session_state.mgeo_similarity_status = {
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
                        'input_type': 'file',
                        'source_table': '',
                        'copy_table': ''
                    }
                    if 'mgeo_sim_match_results' in st.session_state:
                        del st.session_state['mgeo_sim_match_results']
                    st.rerun()
            with col2:
                if st.button("↩️ 返回地址匹配", key='back_mgeo_sim_file'):
                    st.session_state.mgeo_similarity_status = {
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
                        'input_type': 'file',
                        'source_table': '',
                        'copy_table': ''
                    }
                    if 'mgeo_sim_match_results' in st.session_state:
                        del st.session_state['mgeo_sim_match_results']
                    st.rerun()
        else:
            col1, col2, col3 = st.columns(3)
            with col1:
                if st.button("📊 结果查看", key='view_mgeo_sim_result'):
                    st.session_state.selected_menu = "结果管理"
                    st.session_state.result_management_active_tab = "MGeo地址相似度匹配结果"
                    st.rerun()
            with col2:
                if st.button("🔄 重新匹配", key='restart_mgeo_sim'):
                    st.session_state.mgeo_similarity_status = {
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
                        'input_type': 'database',
                        'source_table': '',
                        'copy_table': ''
                    }
                    st.rerun()
            with col3:
                if st.button("↩️ 返回地址匹配", key='back_mgeo_sim_db'):
                    st.session_state.mgeo_similarity_status = {
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
                        'input_type': 'database',
                        'source_table': '',
                        'copy_table': ''
                    }
                    st.rerun()

            if mgeo_sim_status.get('copy_table'):
                st.info(f"📋 副本表: {mgeo_sim_status['copy_table']}")

        st.markdown("</div>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)
        return

    # 数据输入方式选择
    input_type = st.radio(
        "数据输入方式",
        options=['file', 'database'],
        format_func=lambda x: '📁 上传文件（CSV/Excel）' if x == 'file' else '🗄️ 数据库表',
        key='mgeo_sim_input_type',
        horizontal=True
    )

    address_a_col = ''
    address_b_col = ''
    df_preview = None

    if input_type == 'file':
        uploaded_file = st.file_uploader(
            "上传数据文件",
            type=['csv', 'xlsx', 'xls'],
            key='mgeo_sim_file_upload'
        )

        if uploaded_file is not None:
            try:
                if uploaded_file.name.endswith('.csv'):
                    df_preview, detected_encoding = read_csv_with_encoding(uploaded_file, nrows=5)
                    uploaded_file.seek(0)
                    st.session_state.mgeo_sim_uploaded_df, _ = read_csv_with_encoding(uploaded_file)
                    st.caption(f"检测到文件编码: {detected_encoding}")
                elif uploaded_file.name.endswith(('.xlsx', '.xls')):
                    df_preview = pd.read_excel(uploaded_file, nrows=5)
                    st.session_state.mgeo_sim_uploaded_df = pd.read_excel(uploaded_file)

                if df_preview is not None:
                    st.success(f"✅ 文件加载成功：{uploaded_file.name}，共 {len(st.session_state.mgeo_sim_uploaded_df):,} 行")
                    with st.expander("数据预览", expanded=False):
                        st.dataframe(df_preview, use_container_width=True)

                    columns = list(st.session_state.mgeo_sim_uploaded_df.columns)
                    col1, col2 = st.columns(2)
                    with col1:
                        address_a_col = st.selectbox(
                            "选择地址字段A",
                            options=columns,
                            key='mgeo_sim_addr_a_file'
                        )
                    with col2:
                        address_b_col = st.selectbox(
                            "选择地址字段B",
                            options=columns,
                            index=min(1, len(columns) - 1),
                            key='mgeo_sim_addr_b_file'
                        )
            except Exception as e:
                st.error(f"文件加载失败: {str(e)}")
    else:
        if not st.session_state.connected:
            st.warning("⚠️ 请先在【数据库配置】页面连接数据库")
            st.markdown("</div>", unsafe_allow_html=True)
            return

        db_conn = DBConnection(
            host=db_config['host'],
            port=db_config['port'],
            schema=db_config['schema'],
            dbname=db_config['dbname'],
            user=db_config['user'],
            password=db_config['password']
        )

        if not db_conn.connect():
            st.error("无法连接数据库")
            st.markdown("</div>", unsafe_allow_html=True)
            return

        try:
            tables = db_conn.get_tables()
            if not tables:
                st.warning("数据库中没有可用的数据表")
                db_conn.close()
                st.markdown("</div>", unsafe_allow_html=True)
                return

            selected_table = st.selectbox(
                "选择数据表",
                options=tables,
                key='mgeo_sim_db_table'
            )

            if selected_table:
                columns = [col[0] for col in db_conn.get_columns(selected_table)]

                col1, col2 = st.columns(2)
                with col1:
                    address_a_col = st.selectbox(
                        "选择地址字段A",
                        options=columns,
                        key='mgeo_sim_addr_a_db'
                    )
                with col2:
                    address_b_col = st.selectbox(
                        "选择地址字段B",
                        options=columns,
                        index=min(1, len(columns) - 1),
                        key='mgeo_sim_addr_b_db'
                    )

                st.session_state.mgeo_sim_selected_table = selected_table
                st.session_state.mgeo_sim_selected_addr_a = address_a_col
                st.session_state.mgeo_sim_selected_addr_b = address_b_col

                count_sql = f"SELECT COUNT(*) as count FROM {selected_table}"
                count_cursor = db_conn.execute(count_sql)
                if count_cursor:
                    total = count_cursor.fetchone()['count']
                    st.info(f"📊 表 {selected_table} 共 {total:,} 条记录")

        except Exception as e:
            st.error(f"获取表信息失败: {str(e)}")
        finally:
            db_conn.close()

    # 启动匹配按钮
    st.divider()

    can_start = False
    if input_type == 'file':
        can_start = (
            'mgeo_sim_uploaded_df' in st.session_state
            and address_a_col
            and address_b_col
        )
    else:
        can_start = (
            'mgeo_sim_selected_table' in st.session_state
            and address_a_col
            and address_b_col
        )

    if can_start:
        if st.button("🚀 启动相似度匹配", key='start_mgeo_sim', type='primary'):
            start_mgeo_similarity_matching(db_config, device, input_type, address_a_col, address_b_col)
    else:
        st.info("请先选择数据源和地址字段")

    st.markdown("</div>", unsafe_allow_html=True)


def start_mgeo_similarity_matching(db_config, device, input_type, address_a_col, address_b_col):
    """
    启动MGeo地址相似度匹配

    Args:
        db_config: 数据库配置字典
        device: 运行设备
        input_type: 输入类型 ('file' 或 'database')
        address_a_col: 地址A字段名
        address_b_col: 地址B字段名
    """
    try:
        from matching.mgeo_similarity import MGeoSimilarityMatcher, run_mgeo_similarity_async

        if 'mgeo_similarity_status' not in st.session_state:
            st.session_state.mgeo_similarity_status = {
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
                'input_type': input_type,
                'source_table': '',
                'copy_table': ''
            }

        matcher = MGeoSimilarityMatcher(device=device)
        st.session_state.mgeo_similarity_matcher = matcher

        start_time = time.time()

        st.session_state.mgeo_similarity_status.update({
            'is_running': True,
            'progress': 0.0,
            'processed_count': 0,
            'total_count': 0,
            'speed': 0.0,
            'remaining_time': 0.0,
            'status_message': '正在初始化...',
            'error_message': '',
            'start_time': start_time,
            'end_time': None,
            'completed': False,
            'result_count': 0,
            'input_type': input_type
        })

        if input_type == 'file':
            data_source = st.session_state.mgeo_sim_uploaded_df
            table_name = None
            db_conn = None
        else:
            data_source = None
            table_name = st.session_state.mgeo_sim_selected_table
            db_conn = DBConnection(
                host=db_config['host'],
                port=db_config['port'],
                schema=db_config['schema'],
                dbname=db_config['dbname'],
                user=db_config['user'],
                password=db_config['password']
            )
            if not db_conn.connect():
                st.error("无法连接数据库")
                return

            from database.data_loader import DataLoader
            data_loader = DataLoader(db_conn)
            sql = f"SELECT * FROM {table_name}"
            cursor = db_conn.execute(sql)
            if cursor:
                rows = cursor.fetchall()
                data_source = pd.DataFrame(rows)
            db_conn.close()

            db_conn_for_result = DBConnection(
                host=db_config['host'],
                port=db_config['port'],
                schema=db_config['schema'],
                dbname=db_config['dbname'],
                user=db_config['user'],
                password=db_config['password']
            )
            if not db_conn_for_result.connect():
                st.error("无法连接数据库（结果写入）")
                return
            db_conn = db_conn_for_result

        def on_completed(success, message, results):
            """匹配完成回调（在后台线程中执行，不访问st.session_state）"""
            logger.info(f"[MGeo相似度匹配] 回调触发: success={success}, message={message}, results_count={len(results) if results else 0}")

        run_mgeo_similarity_async(
            matcher=matcher,
            data_source=data_source,
            address_a_col=address_a_col,
            address_b_col=address_b_col,
            db_conn=db_conn,
            table_name=table_name if input_type == 'database' else None,
            completed_callback=on_completed
        )

        st.success("MGeo地址相似度匹配任务已启动！")
        st.rerun()

    except Exception as e:
        st.error(f"启动失败: {str(e)}")
        import traceback
        st.write(f"详细错误: {traceback.format_exc()}")
        logger.error(f"MGeo similarity matching failed: {str(e)}")


def reset_matching_status():
    """重置匹配状态"""
    st.session_state.matching_status = {
        'is_running': False,
        'processed_count': 0,
        'total_count': 0,
        'current_stage': '',
        'progress': 0.0,
        'speed': 0.0,
        'remaining_time': 0.0,
        'status_message': '',
        'error_message': '',
        'start_time': None,
        'recall_completed': False,
        'ranking_completed': False,
        'ranking_ui_shown': False,
        'recall_count': 0,
        'match_count': 0
    }
    st.session_state.recall_status = {
        'completed': False,
        'start_time': None,
        'end_time': None,
        'recall_count': 0,
        'candidate_count': 0
    }

def start_recall_matching(db_config, device, enterprise_vector_table, standard_vector_table):
    """启动粗召回匹配"""
    try:
        from matching.matcher import AddressMatcher
        
        db_conn = DBConnection(
            host=db_config['host'],
            port=db_config['port'],
            schema=db_config['schema'],
            dbname=db_config['dbname'],
            user=db_config['user'],
            password=db_config['password']
        )
        
        if not db_conn.connect():
            st.error("无法连接数据库")
            return
        
        matcher = AddressMatcher(db_conn, device=device, mode='recall_only')
        matcher.set_threshold(st.session_state.matching_config['similarity_threshold'])
        st.session_state.matcher = matcher
        
        # 设置开始时间
        start_time = time.time()
        
        # 更新状态（在主线程中）
        st.session_state.matching_status.update({
            'is_running': True,
            'processed_count': 0,
            'total_count': 0,
            'current_stage': '数据粗召回',
            'progress': 0.0,
            'speed': 0.0,
            'remaining_time': 0.0,
            'status_message': '',
            'error_message': '',
            'start_time': start_time,
            'recall_completed': False,
            'ranking_completed': False,
            'ranking_ui_shown': False
        })
        
        st.session_state.recall_status.update({
            'completed': False,
            'start_time': start_time,
            'end_time': None,
            'recall_count': 0,
            'candidate_count': 0
        })
        
        # 定义完成回调函数：在粗召回完成后主动更新状态
        def on_recall_completed(recall_results):
            """粗召回完成回调函数"""
            recall_count = len(recall_results)
            candidate_count = sum(len(item['candidates']) for item in recall_results)
            
            logger.info(f"[回调] 粗召回完成，企业数: {recall_count}, 候选数: {candidate_count}")
            
            # 更新状态
            st.session_state.matching_status = {
                'is_running': False,
                'processed_count': recall_count,
                'current_stage': '数据粗召回完成',
                'progress': 1.0,
                'speed': 0.0,
                'remaining_time': 0.0,
                'status_message': '粗召回完成',
                'error_message': '',
                'start_time': st.session_state.matching_status.get('start_time'),
                'recall_completed': True,
                'ranking_completed': False,
                'ranking_ui_shown': False,
                'recall_count': recall_count,
                'match_count': 0
            }
            
            st.session_state.recall_status = {
                'completed': True,
                'end_time': time.time(),
                'recall_count': recall_count,
                'candidate_count': candidate_count,
                'start_time': st.session_state.matching_status.get('start_time')
            }
            
            # 设置触发器，让主线程知道粗召回已完成
            # 在后台线程中不能直接调用st.rerun()，只能设置标志让主线程刷新
            st.session_state['recall_finished_trigger'] = True
            logger.info("[回调] 已设置recall_finished_trigger标志")
        
        # 启动后台任务，使用回调函数通知完成状态
        matcher.start_recall_async(
            enterprise_table=enterprise_vector_table,
            standard_table=standard_vector_table,
            top_n=st.session_state.matching_config['recall_top_n'],
            progress_callback=None,
            completed_callback=on_recall_completed
        )
        
        st.success("粗召回匹配任务已启动！")
        st.rerun()
        
    except Exception as e:
        st.error(f"启动失败: {str(e)}")
        import traceback
        st.write(f"详细错误: {traceback.format_exc()}")
        logger.error(f"Recall matching failed: {str(e)}")

def start_mgeo_ranking(db_config, device):
    """启动MGeo精确匹配"""
    try:
        start_time = time.time()
        threshold = st.session_state.matching_config['similarity_threshold']
        
        logger.info("[start_mgeo_ranking] 开始启动MGeo精排...")
        logger.info(f"[start_mgeo_ranking] 相似度阈值: {threshold}")
        
        # 创建线程安全的状态共享对象（类似matcher.py的方式）
        class RankingStatus:
            def __init__(self):
                self.lock = threading.Lock()
                self.is_running = True
                self.processed_count = 0
                self.total_count = 0
                self.current_stage = 'MGeo精确匹配'
                self.progress = 0.0
                self.speed = 0.0
                self.remaining_time = 0.0
                self.status_message = '正在加载MGeo模型...'
                self.error_message = ''
                self.ranking_completed = False
                self.match_count = 0
            
            def update(self, **kwargs):
                with self.lock:
                    for key, value in kwargs.items():
                        if hasattr(self, key):
                            setattr(self, key, value)
            
            def get_status(self):
                with self.lock:
                    return {
                        'is_running': self.is_running,
                        'processed_count': self.processed_count,
                        'total_count': self.total_count,
                        'current_stage': self.current_stage,
                        'progress': self.progress,
                        'speed': self.speed,
                        'remaining_time': self.remaining_time,
                        'status_message': self.status_message,
                        'error_message': self.error_message,
                        'ranking_completed': self.ranking_completed,
                        'match_count': self.match_count
                    }
        
        # 清除可能影响状态判断的残留标志
        if 'post_recall_refresh_count' in st.session_state:
            del st.session_state['post_recall_refresh_count']
        
        # 清除粗召回阶段的matcher对象，避免状态读取冲突
        if 'matcher' in st.session_state:
            del st.session_state['matcher']
        
        # 创建状态对象并保存到session_state
        ranking_status = RankingStatus()
        ranking_status.total_count = st.session_state.recall_status['recall_count']
        st.session_state.running_ranking_status = ranking_status
        
        logger.info(f"[start_mgeo_ranking] 召回企业数: {st.session_state.recall_status['recall_count']}")
        
        # 更新状态（在主线程中），先标记为运行中
        st.session_state.matching_status = {
            'is_running': True,
            'processed_count': 0,
            'total_count': st.session_state.recall_status['recall_count'],
            'current_stage': 'MGeo精确匹配',
            'progress': 0.0,
            'speed': 0.0,
            'remaining_time': 0.0,
            'status_message': '正在加载MGeo模型...',
            'error_message': '',
            'start_time': start_time,
            'recall_completed': True,
            'ranking_completed': False,
            'ranking_ui_shown': False,
            'recall_count': st.session_state.recall_status['recall_count'],
            'match_count': 0
        }
        
        # 启动后台线程执行MGeo精排（模型加载和数据库操作都在后台线程中完成）
        def ranking_thread_func(inner_db_config, inner_device, inner_threshold, inner_ranking_status, inner_start_time):
            """MGeo精排后台线程"""
            db_conn = None
            try:
                logger.info("[ranking_thread_func] 后台线程开始执行")
                
                # 在后台线程中创建独立的数据库连接
                db_conn = DBConnection(
                    host=inner_db_config['host'],
                    port=inner_db_config['port'],
                    schema=inner_db_config['schema'],
                    dbname=inner_db_config['dbname'],
                    user=inner_db_config['user'],
                    password=inner_db_config['password']
                )
                if not db_conn.connect():
                    logger.error("[ranking_thread_func] 无法连接数据库")
                    inner_ranking_status.update(
                        is_running=False,
                        error_message='无法连接数据库'
                    )
                    return
                
                data_loader = DataLoader(db_conn)
                
                # 确保结果表存在
                data_loader.create_result_table()
                data_loader.truncate_result_table()
                logger.info("[ranking_thread_func] 已清空match_results表")
                
                # 从recall_results表加载召回结果
                logger.info("[MGeo精排] 加载召回结果...")
                recall_results = data_loader.load_recall_results()
                total = len(recall_results)
                inner_ranking_status.total_count = total
                
                if total == 0:
                    logger.warning("[MGeo精排] 没有召回结果")
                    inner_ranking_status.update(
                        is_running=False,
                        current_stage='MGeo精确匹配完成',
                        status_message='没有召回结果可匹配'
                    )
                    return
                
                logger.info(f"[MGeo精排] 共 {total} 家企业需要精排")
                
                logger.info("[MGeo精排] 加载MGeo模型...")
                from model.mgeo_model import MGeoModel
                mgeo_model = MGeoModel(device=inner_device)
                logger.info(f"[MGeo精排] 模型加载完成")
                
                inner_ranking_status.update(
                    status_message='正在执行MGeo精排...'
                )
                
                final_results = []
                processed_count = 0
                
                # 遍历每个企业的召回结果
                for recall_idx, recall_item in enumerate(recall_results):
                    # 检查是否被停止
                    if not inner_ranking_status.is_running:
                        logger.info("[MGeo精排] 用户停止了匹配")
                        break
                    
                    enterprise_id = recall_item['enterprise_id']
                    enterprise_name = recall_item.get('enterprise_name', '')
                    enterprise_addr = recall_item['enterprise_address']
                    candidates = recall_item['candidates']
                    
                    if not candidates:
                        final_results.append({
                            'enterprise_id': enterprise_id,
                            'enterprise_name': enterprise_name,
                            'enterprise_address': enterprise_addr,
                            'address_id': None,
                            'standard_address': None,
                            'room_no': '',
                            'exact_match': 0.0,
                            'partial_match': 0.0,
                            'not_match': 1.0,
                            'match_status': '不匹配'
                        })
                        processed_count += 1
                        continue
                    
                    pairs = [(enterprise_addr, candidate['address']) for candidate in candidates]
                    
                    try:
                        predictions = mgeo_model.predict(pairs)
                    except Exception as e:
                        logger.error(f"[MGeo精排] 预测失败 enterprise={enterprise_id}: {str(e)}")
                        final_results.append({
                            'enterprise_id': enterprise_id,
                            'enterprise_name': enterprise_name,
                            'enterprise_address': enterprise_addr,
                            'address_id': None,
                            'standard_address': None,
                            'room_no': '',
                            'exact_match': 0.0,
                            'partial_match': 0.0,
                            'not_match': 1.0,
                            'match_status': '不匹配'
                        })
                        processed_count += 1
                        continue
                    
                    # 按相似度阈值过滤低分候选
                    filtered_pairs = []
                    for i, candidate in enumerate(candidates):
                        sim = candidate.get('similarity', 1.0)
                        if inner_threshold is not None and inner_threshold > 0 and sim < inner_threshold:
                            continue
                        filtered_pairs.append((i, candidate, predictions[i]))
                    
                    if not filtered_pairs:
                        final_results.append({
                            'enterprise_id': enterprise_id,
                            'enterprise_name': enterprise_name,
                            'enterprise_address': enterprise_addr,
                            'address_id': None,
                            'standard_address': None,
                            'room_no': '',
                            'exact_match': 0.0,
                            'partial_match': 0.0,
                            'not_match': 1.0,
                            'match_status': '不匹配'
                        })
                        processed_count += 1
                        continue
                    
                    best_score = -1.0
                    best_not_match = float('inf')
                    best_candidate = None
                    best_pred = None
                    
                    for i, candidate, pred in filtered_pairs:
                        score = pred['exact_match']
                        not_match = pred['not_match']
                        if score > best_score or (score == best_score and not_match < best_not_match):
                            best_score = score
                            best_not_match = not_match
                            best_candidate = candidates[i]
                            best_pred = pred
                    
                    if best_candidate and best_pred:
                        scores = {
                            '精确匹配': best_pred['exact_match'],
                            '部分匹配': best_pred['partial_match'],
                            '不匹配': best_pred['not_match']
                        }
                        match_status = max(scores, key=scores.get)
                        result_item = {
                            'enterprise_id': enterprise_id,
                            'enterprise_name': enterprise_name,
                            'enterprise_address': enterprise_addr,
                            'address_id': best_candidate['source_id'],
                            'standard_address': best_candidate['address'],
                            'room_no': best_candidate.get('room_no', ''),
                            'exact_match': best_pred['exact_match'],
                            'partial_match': best_pred['partial_match'],
                            'not_match': best_pred['not_match'],
                            'match_status': match_status
                        }
                        final_results.append(result_item)
                    else:
                        result_item = {
                            'enterprise_id': enterprise_id,
                            'enterprise_name': enterprise_name,
                            'enterprise_address': enterprise_addr,
                            'address_id': None,
                            'standard_address': None,
                            'room_no': '',
                            'exact_match': 0.0,
                            'partial_match': 0.0,
                            'not_match': 1.0,
                            'match_status': '不匹配'
                        }
                        final_results.append(result_item)
                    
                    processed_count += 1
                    
                    elapsed_time = time.time() - inner_start_time
                    speed = processed_count / elapsed_time if elapsed_time > 0 else 0
                    progress = processed_count / total
                    remaining_time = (total - processed_count) / speed if speed > 0 else 0
                    
                    inner_ranking_status.update(
                        processed_count=processed_count,
                        progress=progress,
                        speed=speed,
                        remaining_time=remaining_time
                    )
                    
                    if len(final_results) >= 100:
                        inserted = data_loader.insert_match_results(final_results)
                        logger.info(f"[MGeo精排] 已插入 {inserted} 条匹配结果")
                        final_results = []
                
                if final_results:
                    inserted = data_loader.insert_match_results(final_results)
                    logger.info(f"[MGeo精排] 最终插入 {inserted} 条匹配结果")
                
                total_time = time.time() - inner_start_time
                logger.info(f"[MGeo精排] 完成！总耗时: {total_time:.2f}s, 处理企业数: {processed_count}")
                
                # 标记完成
                inner_ranking_status.update(
                    is_running=False,
                    ranking_completed=True,
                    current_stage='MGeo精确匹配完成',
                    status_message='MGeo精确匹配完成',
                    progress=1.0,
                    processed_count=processed_count,
                    match_count=processed_count
                )
                
            except Exception as e:
                logger.error(f"[MGeo精排] 失败: {str(e)}")
                import traceback
                logger.error(f"[MGeo精排] 详细堆栈: {traceback.format_exc()}")
                inner_ranking_status.update(
                    is_running=False,
                    error_message=str(e),
                    current_stage='MGeo精确匹配失败'
                )
            finally:
                if db_conn:
                    try:
                        db_conn.close()
                    except:
                        pass
        
        # 启动后台线程
        ranking_thread = threading.Thread(target=ranking_thread_func, args=(db_config, device, threshold, ranking_status, start_time), daemon=True)
        ranking_thread.start()
        st.session_state.ranking_thread = ranking_thread
        
        st.success("MGeo精确匹配任务已启动！")
        st.rerun()
        
    except Exception as e:
        st.error(f"启动失败: {str(e)}")
        import traceback
        st.write(f"详细错误: {traceback.format_exc()}")
        logger.error(f"Ranking failed: {str(e)}")

def show_result_management():
    """
    结果管理页面
    
    功能：
        1. 粗召回数据浏览与导出
        2. 精排匹配结果浏览、筛选与导出
        3. 匹配统计分析
        4. MGeo地址相似度匹配结果浏览与导出
    """
    if not st.session_state.connected:
        st.warning("⚠️ 结果管理功能需要数据库连接，请先在【数据库配置】页面配置并连接数据库")
        return
    
    db_config = st.session_state.db_config
    db_conn = DBConnection(
        host=db_config['host'],
        port=db_config['port'],
        schema=db_config['schema'],
        dbname=db_config['dbname'],
        user=db_config['user'],
        password=db_config['password']
    )
    
    if not db_conn.connect():
        st.error("无法连接数据库，请检查配置")
        return
    
    data_loader = DataLoader(db_conn)
    
    data_loader.create_recall_table()
    data_loader.create_result_table()
    
    active_tab_name = st.session_state.get('result_management_active_tab', None)
    if 'result_management_active_tab' in st.session_state:
        del st.session_state['result_management_active_tab']
    
    tab1, tab2, tab3 = st.tabs(["粗召回数据", "精排匹配结果", "MGeo地址相似度匹配结果"])
    
    if active_tab_name:
        tab_index_map = {"粗召回数据": 0, "精排匹配结果": 1, "MGeo地址相似度匹配结果": 2}
        target_idx = tab_index_map.get(active_tab_name, 0)
        st.components.v1.html(
            f"""
            <script>
            var tabs = window.parent.document.querySelectorAll('[data-baseweb="tab"]');
            if (tabs.length > {target_idx}) {{
                setTimeout(function() {{ tabs[{target_idx}].click(); }}, 100);
            }}
            </script>
            """,
            height=0,
        )
    
    with tab1:
        st.subheader("粗召回数据")
        
        if st.session_state.manual_correction_mode:
            st.markdown("""
            <div style='background-color: #fff3cd; padding: 12px; border-radius: 8px; border-left: 4px solid #ffc107; margin-bottom: 16px;'>
                <strong>⚠️ 人工纠正模式</strong>：请选择需要更改的数据，勾选后点击"标记为精确匹配"按钮
            </div>
            """, unsafe_allow_html=True)
            
            enterprise_ids = st.session_state.manual_correction_enterprise_ids
            
            try:
                recall_df = data_loader.get_recall_results_by_enterprise_ids(enterprise_ids)
                
                if not recall_df.empty:
                    st.info(f"已筛选出 {len(recall_df)} 条粗召回数据（涉及 {len(enterprise_ids)} 个企业）")
                    
                    display_df = recall_df.copy()
                    display_df.insert(0, '选择', False)
                    
                    disabled_cols = [col for col in display_df.columns if col != '选择']
                    
                    edited_df = st.data_editor(
                        display_df,
                        use_container_width=True,
                        disabled=disabled_cols,
                        key='recall_correction_editor'
                    )
                    
                    selected_rows = edited_df[edited_df['选择'] == True]
                    
                    btn_col1, btn_col2, btn_col3 = st.columns([2, 1, 1])
                    with btn_col1:
                        if len(selected_rows) > 0:
                            st.success(f"已勾选 {len(selected_rows)} 条数据")
                        else:
                            st.info("请在上方表格中勾选需要标记的数据")
                    
                    with btn_col2:
                        confirm_key = 'confirm_mark_exact'
                        if len(selected_rows) > 0:
                            if st.button("✅ 标记为精确匹配", key='mark_exact_match_btn', type="primary"):
                                st.session_state.pending_correction_data = []
                                for _, row in selected_rows.iterrows():
                                    st.session_state.pending_correction_data.append({
                                        'enterprise_id': row['enterprise_id'],
                                        'standard_id': row['standard_id'],
                                        'standard_address': row['standard_address'],
                                        'room_no': row.get('room_no', '')
                                    })
                                st.session_state.show_correction_confirm = True
                    
                    with btn_col3:
                        if st.button("↩️ 返回", key='back_to_match_results'):
                            st.session_state.manual_correction_mode = False
                            st.session_state.manual_correction_enterprise_ids = []
                            st.session_state.result_management_active_tab = "精排匹配结果"
                            st.rerun()
                    
                    if st.session_state.get('show_correction_confirm', False):
                        correction_data = st.session_state.get('pending_correction_data', [])
                        st.markdown("""
                        <div style='background-color: #d1ecf1; padding: 12px; border-radius: 8px; border-left: 4px solid #0dcaf0; margin: 10px 0;'>
                            <strong>🔔 确认操作</strong>：将 {count} 条数据标记为精确匹配，此操作将更新精排匹配结果中对应企业的匹配数据。
                        </div>
                        """.format(count=len(correction_data)), unsafe_allow_html=True)
                        
                        confirm_btn_col1, confirm_btn_col2 = st.columns(2)
                        with confirm_btn_col1:
                            if st.button("✔️ 确认提交", key='confirm_correction_submit', type="primary"):
                                success_count = data_loader.batch_update_match_results_with_correction(correction_data)
                                st.session_state.manual_correction_mode = False
                                st.session_state.manual_correction_enterprise_ids = []
                                st.session_state.show_correction_confirm = False
                                st.session_state.pending_correction_data = []
                                st.session_state.result_management_active_tab = "精排匹配结果"
                                st.session_state.correction_success_count = success_count
                                st.rerun()
                        with confirm_btn_col2:
                            if st.button("❌ 取消", key='cancel_correction'):
                                st.session_state.show_correction_confirm = False
                                st.session_state.pending_correction_data = []
                                st.rerun()
                else:
                    st.warning("未找到对应企业的粗召回数据")
                    if st.button("↩️ 返回精排匹配结果", key='back_to_match_results_empty'):
                        st.session_state.manual_correction_mode = False
                        st.session_state.manual_correction_enterprise_ids = []
                        st.session_state.result_management_active_tab = "精排匹配结果"
                        st.rerun()
            except Exception as e:
                st.error(f"查询粗召回数据出错: {e}")
                if st.button("↩️ 返回精排匹配结果", key='back_to_match_results_error'):
                    st.session_state.manual_correction_mode = False
                    st.session_state.manual_correction_enterprise_ids = []
                    st.session_state.result_management_active_tab = "精排匹配结果"
                    st.rerun()
        else:
            if st.session_state.get('correction_success_count', 0) > 0:
                count = st.session_state.correction_success_count
                st.session_state.correction_success_count = 0
                st.success(f"✅ 人工纠正完成！成功更新 {count} 条匹配结果")
            
            recall_filter_col1, recall_filter_col2, recall_filter_col3 = st.columns(3)
            with recall_filter_col1:
                recall_keyword = st.text_input("关键词搜索", key='recall_keyword')
            with recall_filter_col2:
                recall_min_sim = st.number_input("最小相似度", min_value=0.0, max_value=1.0, value=0.0, step=0.1, key='recall_min_sim')
            with recall_filter_col3:
                recall_max_sim = st.number_input("最大相似度", min_value=0.0, max_value=1.0, value=1.0, step=0.1, key='recall_max_sim')
            
            recall_filters = {}
            if recall_keyword:
                recall_filters['keyword'] = recall_keyword
            if recall_min_sim > 0:
                recall_filters['min_similarity'] = recall_min_sim
            if recall_max_sim < 1:
                recall_filters['max_similarity'] = recall_max_sim
            
            try:
                total = data_loader.get_recall_results_count(filters=recall_filters)
                
                if total > 0:
                    col1, col2, col3 = st.columns([2, 3, 2])
                    
                    with col1:
                        page_size = st.selectbox(
                            "每页显示",
                            options=[10, 20, 50, 100, 200],
                            index=1,
                            key='recall_page_size'
                        )
                    
                    total_pages = (total + page_size - 1) // page_size
                    st.session_state['recall_total_pages'] = total_pages
                    
                    with col2:
                        page = st.number_input(
                            f"页码 (共{total_pages}页)",
                            min_value=1,
                            max_value=total_pages,
                            value=1,
                            key='recall_page'
                        )
                    
                    with col3:
                        st.write("")
                        st.write(f"共 {total:,} 条记录")
                    
                    nav_col1, nav_col2, nav_col3, nav_col4, nav_col5 = st.columns(5)
                    with nav_col1:
                        st.button("⏮️ 首页", key='recall_first', on_click=_goto_page, args=('recall_page', 1))
                    with nav_col2:
                        st.button("◀️ 上一页", key='recall_prev', on_click=_prev_page, args=('recall_page',))
                    with nav_col3:
                        st.markdown(f"<div style='text-align: center; padding: 8px;'>第 {page} / {total_pages} 页</div>", unsafe_allow_html=True)
                    with nav_col4:
                        st.button("▶️ 下一页", key='recall_next', on_click=_next_page, args=('recall_page', 'recall_total_pages'))
                    with nav_col5:
                        st.button("⏭️ 末页", key='recall_last', on_click=_goto_page, args=('recall_page', total_pages))
                    
                    offset = (page - 1) * page_size
                    results = data_loader.get_recall_results_paginated(
                        filters=recall_filters,
                        page=page,
                        page_size=page_size
                    )
                    
                    if not results.empty:
                        st.dataframe(results, use_container_width=True)
                        
                        start_idx = offset + 1
                        end_idx = min(offset + page_size, total)
                        st.info(f"显示第 {start_idx:,} - {end_idx:,} 条，共 {total:,} 条")
                    
                    st.divider()
                    export_col1, export_col2 = st.columns(2)
                    with export_col1:
                        if st.button("📥 导出粗召回数据 (CSV)", key='export_recall_csv'):
                            try:
                                import io
                                buffer = io.StringIO()
                                first_batch = True
                                batch_count = 0
                                for batch_df in data_loader.export_recall_results_batch(batch_size=5000):
                                    batch_df.to_csv(buffer, index=False, header=first_batch, encoding='utf-8-sig')
                                    first_batch = False
                                    batch_count += 1
                                csv_data = buffer.getvalue()
                                st.download_button(
                                    label="下载 CSV 文件",
                                    data=csv_data,
                                    file_name=f"粗召回数据_{time.strftime('%Y%m%d_%H%M%S')}.csv",
                                    mime="text/csv",
                                    key='download_recall_csv'
                                )
                                st.success(f"CSV文件已生成，共分 {batch_count} 批加载")
                            except Exception as e:
                                st.error(f"导出CSV失败: {str(e)}")
                    with export_col2:
                        if st.button("📥 导出粗召回数据 (Excel)", key='export_recall_excel'):
                            try:
                                import io
                                buffer = io.BytesIO()
                                with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                                    batch_idx = 0
                                    for batch_df in data_loader.export_recall_results_batch(batch_size=5000):
                                        sheet_name = f'数据_{batch_idx + 1}' if batch_idx < 26 else f'S{batch_idx + 1}'
                                        batch_df.to_excel(writer, sheet_name=sheet_name, index=False)
                                        batch_idx += 1
                                excel_data = buffer.getvalue()
                                st.download_button(
                                    label="下载 Excel 文件",
                                    data=excel_data,
                                    file_name=f"粗召回数据_{time.strftime('%Y%m%d_%H%M%S')}.xlsx",
                                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                    key='download_recall_excel'
                                )
                                st.success(f"Excel文件已生成，共 {batch_idx} 个工作表")
                            except ImportError:
                                st.error("导出Excel需要安装openpyxl库，请运行: pip install openpyxl")
                            except Exception as e:
                                st.error(f"导出Excel失败: {str(e)}")
                else:
                    st.info("暂无粗召回数据")
            except Exception as e:
                st.warning(f"粗召回数据表查询出错: {e}")
    
    with tab2:
        st.subheader("精排匹配结果")
        
        filter_col1, filter_col2, filter_col3 = st.columns(3)
        with filter_col1:
            match_status = st.selectbox("匹配状态筛选", ['全部', '精确匹配', '部分匹配', '不匹配'], key='match_status_filter')
        with filter_col2:
            min_exact = st.number_input("最小精确匹配概率", min_value=0.0, max_value=1.0, value=0.0, step=0.1, key='min_exact')
        with filter_col3:
            max_exact = st.number_input("最大精确匹配概率", min_value=0.0, max_value=1.0, value=1.0, step=0.1, key='max_exact')
        
        filter_col4, filter_col5, filter_col6 = st.columns(3)
        with filter_col4:
            min_partial = st.number_input("最小部分匹配概率", min_value=0.0, max_value=1.0, value=0.0, step=0.1, key='min_partial')
        with filter_col5:
            max_partial = st.number_input("最大部分匹配概率", min_value=0.0, max_value=1.0, value=1.0, step=0.1, key='max_partial')
        with filter_col6:
            min_not = st.number_input("最小不匹配概率", min_value=0.0, max_value=1.0, value=0.0, step=0.1, key='min_not')
        
        filter_col7, filter_col8 = st.columns(2)
        with filter_col7:
            max_not = st.number_input("最大不匹配概率", min_value=0.0, max_value=1.0, value=1.0, step=0.1, key='max_not')
        with filter_col8:
            keyword = st.text_input("关键词搜索", key='match_keyword')
        
        filters = {}
        if match_status != '全部':
            filters['match_status'] = match_status
        if min_exact > 0:
            filters['min_exact_match'] = min_exact
        if max_exact < 1:
            filters['max_exact_match'] = max_exact
        if min_partial > 0:
            filters['min_partial_match'] = min_partial
        if max_partial < 1:
            filters['max_partial_match'] = max_partial
        if min_not > 0:
            filters['min_not_match'] = min_not
        if max_not < 1:
            filters['max_not_match'] = max_not
        if keyword:
            filters['keyword'] = keyword
        
        try:
            total = data_loader.get_match_results_count(filters=filters)
            
            if total > 0:
                col1, col2, col3 = st.columns([2, 3, 2])
                
                with col1:
                    page_size = st.selectbox(
                        "每页显示",
                        options=[10, 20, 50, 100, 200],
                        index=1,
                        key='match_page_size'
                    )
                
                total_pages = (total + page_size - 1) // page_size
                st.session_state['match_total_pages'] = total_pages
                
                with col2:
                    page = st.number_input(
                        f"页码 (共{total_pages}页)",
                        min_value=1,
                        max_value=total_pages,
                        value=1,
                        key='match_page'
                    )
                
                with col3:
                    st.write("")
                    st.write(f"共 {total:,} 条记录")
                
                nav_col1, nav_col2, nav_col3, nav_col4, nav_col5 = st.columns(5)
                with nav_col1:
                    st.button("⏮️ 首页", key='match_first', on_click=_goto_page, args=('match_page', 1))
                with nav_col2:
                    st.button("◀️ 上一页", key='match_prev', on_click=_prev_page, args=('match_page',))
                with nav_col3:
                    st.markdown(f"<div style='text-align: center; padding: 8px;'>第 {page} / {total_pages} 页</div>", unsafe_allow_html=True)
                with nav_col4:
                    st.button("▶️ 下一页", key='match_next', on_click=_next_page, args=('match_page', 'match_total_pages'))
                with nav_col5:
                    st.button("⏭️ 末页", key='match_last', on_click=_goto_page, args=('match_page', total_pages))
                
                offset = (page - 1) * page_size
                results = data_loader.get_match_results_paginated(
                    filters=filters,
                    page=page,
                    page_size=page_size
                )
                
                if not results.empty:
                    event = st.dataframe(results, use_container_width=True, on_select="rerun", selection_mode="multi-row")
                    selected_indices = event.selection.rows
                    
                    start_idx = offset + 1
                    end_idx = min(offset + page_size, total)
                    st.info(f"显示第 {start_idx:,} - {end_idx:,} 条，共 {total:,} 条")
                    
                    if selected_indices:
                        selected_enterprise_ids = list(set([results.iloc[idx]['enterprise_id'] for idx in selected_indices if idx < len(results)]))
                        correction_col1, correction_col2 = st.columns([3, 1])
                        with correction_col1:
                            st.warning(f"已选中 {len(selected_indices)} 条数据，涉及 {len(selected_enterprise_ids)} 个企业")
                        with correction_col2:
                            if st.button("🔧 人工纠正", key='manual_correction_btn', type="primary"):
                                st.session_state.manual_correction_mode = True
                                st.session_state.manual_correction_enterprise_ids = selected_enterprise_ids
                                st.session_state.result_management_active_tab = "粗召回数据"
                                st.rerun()
                
                st.divider()
                export_col1, export_col2 = st.columns(2)
                with export_col1:
                    if st.button("📥 导出匹配结果 (CSV)", key='export_match_csv'):
                        try:
                            import io
                            buffer = io.StringIO()
                            first_batch = True
                            batch_count = 0
                            for batch_df in data_loader.export_match_results_batch(filters=filters, batch_size=5000):
                                batch_df.to_csv(buffer, index=False, header=first_batch, encoding='utf-8-sig')
                                first_batch = False
                                batch_count += 1
                            csv_data = buffer.getvalue()
                            st.download_button(
                                label="下载 CSV 文件",
                                data=csv_data,
                                file_name=f"匹配结果_{time.strftime('%Y%m%d_%H%M%S')}.csv",
                                mime="text/csv",
                                key='download_match_csv'
                            )
                            st.success(f"CSV文件已生成，共分 {batch_count} 批加载")
                        except Exception as e:
                            st.error(f"导出CSV失败: {str(e)}")
                with export_col2:
                    if st.button("📥 导出匹配结果 (Excel)", key='export_match_excel'):
                        try:
                            import io
                            buffer = io.BytesIO()
                            with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                                batch_idx = 0
                                for batch_df in data_loader.export_match_results_batch(filters=filters, batch_size=5000):
                                    sheet_name = f'数据_{batch_idx + 1}' if batch_idx < 26 else f'S{batch_idx + 1}'
                                    batch_df.to_excel(writer, sheet_name=sheet_name, index=False)
                                    batch_idx += 1
                            excel_data = buffer.getvalue()
                            st.download_button(
                                label="下载 Excel 文件",
                                data=excel_data,
                                file_name=f"匹配结果_{time.strftime('%Y%m%d_%H%M%S')}.xlsx",
                                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                key='download_match_excel'
                            )
                            st.success(f"Excel文件已生成，共 {batch_idx} 个工作表")
                        except ImportError:
                            st.error("导出Excel需要安装openpyxl库，请运行: pip install openpyxl")
                        except Exception as e:
                            st.error(f"导出Excel失败: {str(e)}")
            else:
                st.info("暂无匹配结果（当前筛选条件下无数据）")
            
            st.divider()
            st.subheader("匹配统计")
            stats = data_loader.get_match_statistics()
            
            stat_col1, stat_col2, stat_col3, stat_col4, stat_col5 = st.columns(5)
            stat_col1.metric("总记录数", f"{stats['total_count']:,}")
            stat_col2.metric("精确匹配", f"{stats['exact_match_count']:,}", f"{stats['exact_match_rate']:.1f}%")
            stat_col3.metric("部分匹配", f"{stats['partial_match_count']:,}", f"{stats['partial_match_rate']:.1f}%")
            stat_col4.metric("不匹配", f"{stats['not_match_count']:,}", f"{stats['not_match_rate']:.1f}%")
            stat_col5.metric("人工纠正", f"{stats['manual_correction_count']:,}", f"{stats['manual_correction_rate']:.1f}%")
            
            prob_col1, prob_col2, prob_col3 = st.columns(3)
            prob_col1.metric("平均精确匹配概率", f"{stats['avg_exact_match']:.4f}")
            prob_col2.metric("平均部分匹配概率", f"{stats['avg_partial_match']:.4f}")
            prob_col3.metric("平均不匹配概率", f"{stats['avg_not_match']:.4f}")
            
            if stats['total_count'] > 0:
                try:
                    import plotly.express as px
                    import plotly.graph_objects as go
                    
                    chart_col1, chart_col2, chart_col3 = st.columns(3)
                    
                    with chart_col1:
                        status_data = {
                            '匹配状态': ['精确匹配', '部分匹配', '不匹配'],
                            '数量': [stats['exact_match_count'], stats['partial_match_count'], stats['not_match_count']]
                        }
                        fig_status = px.pie(status_data, values='数量', names='匹配状态',
                                           title='匹配状态分布',
                                           color='匹配状态',
                                           color_discrete_map={'精确匹配': '#2ecc71', '部分匹配': '#f39c12', '不匹配': '#e74c3c'})
                        st.plotly_chart(fig_status, use_container_width=True)
                    
                    with chart_col2:
                        prob_data = {
                            '概率类型': ['精确匹配', '部分匹配', '不匹配'],
                            '平均概率': [stats['avg_exact_match'], stats['avg_partial_match'], stats['avg_not_match']]
                        }
                        fig_prob = px.bar(prob_data, x='概率类型', y='平均概率',
                                         title='三类匹配概率均值分布',
                                         color='概率类型',
                                         color_discrete_map={'精确匹配': '#2ecc71', '部分匹配': '#f39c12', '不匹配': '#e74c3c'})
                        fig_prob.update_layout(yaxis_range=[0, 1])
                        st.plotly_chart(fig_prob, use_container_width=True)

                    with chart_col3:
                        correction_data = {
                            '来源': ['自动匹配', '人工纠正'],
                            '数量': [stats['auto_match_count'], stats['manual_correction_count']]
                        }
                        fig_correction = px.pie(correction_data, values='数量', names='来源',
                                               title='匹配来源分布',
                                               color='来源',
                                               color_discrete_map={'自动匹配': '#3498db', '人工纠正': '#9b59b6'})
                        st.plotly_chart(fig_correction, use_container_width=True)
                except ImportError:
                    st.info("安装plotly可显示统计图表: pip install plotly")
        except Exception as e:
            st.error(f"查询匹配结果出错: {e}")

    with tab3:
        st.subheader("MGeo地址相似度匹配结果")

        filter_col1, filter_col2, filter_col3 = st.columns(3)
        with filter_col1:
            sim_match_status = st.selectbox("匹配状态筛选", ['全部', '精确匹配', '部分匹配', '不匹配'], key='sim_match_status_filter')
        with filter_col2:
            sim_min_exact = st.number_input("最小精确匹配概率", min_value=0.0, max_value=1.0, value=0.0, step=0.1, key='sim_min_exact')
        with filter_col3:
            sim_max_exact = st.number_input("最大精确匹配概率", min_value=0.0, max_value=1.0, value=1.0, step=0.1, key='sim_max_exact')

        filter_col4, filter_col5, filter_col6 = st.columns(3)
        with filter_col4:
            sim_min_partial = st.number_input("最小部分匹配概率", min_value=0.0, max_value=1.0, value=0.0, step=0.1, key='sim_min_partial')
        with filter_col5:
            sim_max_partial = st.number_input("最大部分匹配概率", min_value=0.0, max_value=1.0, value=1.0, step=0.1, key='sim_max_partial')
        with filter_col6:
            sim_min_not = st.number_input("最小不匹配概率", min_value=0.0, max_value=1.0, value=0.0, step=0.1, key='sim_min_not')

        filter_col7, filter_col8 = st.columns(2)
        with filter_col7:
            sim_max_not = st.number_input("最大不匹配概率", min_value=0.0, max_value=1.0, value=1.0, step=0.1, key='sim_max_not')
        with filter_col8:
            sim_keyword = st.text_input("关键词搜索", key='sim_match_keyword')

        sim_filters = {}
        if sim_match_status != '全部':
            sim_filters['match_status'] = sim_match_status
        if sim_min_exact > 0:
            sim_filters['min_exact_match'] = sim_min_exact
        if sim_max_exact < 1:
            sim_filters['max_exact_match'] = sim_max_exact
        if sim_min_partial > 0:
            sim_filters['min_partial_match'] = sim_min_partial
        if sim_max_partial < 1:
            sim_filters['max_partial_match'] = sim_max_partial
        if sim_min_not > 0:
            sim_filters['min_not_match'] = sim_min_not
        if sim_max_not < 1:
            sim_filters['max_not_match'] = sim_max_not
        if sim_keyword:
            sim_filters['keyword'] = sim_keyword

        try:
            sim_total = data_loader.get_mgeo_similarity_results_count(filters=sim_filters)

            if sim_total > 0:
                col1, col2, col3 = st.columns([2, 3, 2])

                with col1:
                    sim_page_size = st.selectbox(
                        "每页显示",
                        options=[10, 20, 50, 100, 200],
                        index=1,
                        key='sim_page_size'
                    )

                sim_total_pages = (sim_total + sim_page_size - 1) // sim_page_size
                st.session_state['sim_total_pages'] = sim_total_pages

                with col2:
                    sim_page = st.number_input(
                        f"页码 (共{sim_total_pages}页)",
                        min_value=1,
                        max_value=sim_total_pages,
                        value=1,
                        key='sim_page'
                    )

                with col3:
                    st.write("")
                    st.write(f"共 {sim_total:,} 条记录")

                nav_col1, nav_col2, nav_col3, nav_col4, nav_col5 = st.columns(5)
                with nav_col1:
                    st.button("⏮️ 首页", key='sim_first', on_click=_goto_page, args=('sim_page', 1))
                with nav_col2:
                    st.button("◀️ 上一页", key='sim_prev', on_click=_prev_page, args=('sim_page',))
                with nav_col3:
                    st.markdown(f"<div style='text-align: center; padding: 8px;'>第 {sim_page} / {sim_total_pages} 页</div>", unsafe_allow_html=True)
                with nav_col4:
                    st.button("▶️ 下一页", key='sim_next', on_click=_next_page, args=('sim_page', 'sim_total_pages'))
                with nav_col5:
                    st.button("⏭️ 末页", key='sim_last', on_click=_goto_page, args=('sim_page', sim_total_pages))

                sim_offset = (sim_page - 1) * sim_page_size
                sim_results = data_loader.get_mgeo_similarity_results_paginated(
                    filters=sim_filters,
                    page=sim_page,
                    page_size=sim_page_size
                )

                if not sim_results.empty:
                    st.dataframe(sim_results, use_container_width=True)

                    sim_start_idx = sim_offset + 1
                    sim_end_idx = min(sim_offset + sim_page_size, sim_total)
                    st.info(f"显示第 {sim_start_idx:,} - {sim_end_idx:,} 条，共 {sim_total:,} 条")

                st.divider()
                export_col1, export_col2 = st.columns(2)
                with export_col1:
                    if st.button("📥 导出相似度匹配结果 (CSV)", key='export_sim_csv'):
                        try:
                            import io
                            buffer = io.StringIO()
                            first_batch = True
                            batch_count = 0
                            for batch_df in data_loader.export_mgeo_similarity_results_batch(filters=sim_filters, batch_size=5000):
                                batch_df.to_csv(buffer, index=False, header=first_batch, encoding='utf-8-sig')
                                first_batch = False
                                batch_count += 1
                            csv_data = buffer.getvalue()
                            st.download_button(
                                label="下载 CSV 文件",
                                data=csv_data,
                                file_name=f"MGeo相似度匹配结果_{time.strftime('%Y%m%d_%H%M%S')}.csv",
                                mime="text/csv",
                                key='download_sim_csv'
                            )
                            st.success(f"CSV文件已生成，共分 {batch_count} 批加载")
                        except Exception as e:
                            st.error(f"导出CSV失败: {str(e)}")
                with export_col2:
                    if st.button("📥 导出相似度匹配结果 (Excel)", key='export_sim_excel'):
                        try:
                            import io
                            buffer = io.BytesIO()
                            with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                                batch_idx = 0
                                for batch_df in data_loader.export_mgeo_similarity_results_batch(filters=sim_filters, batch_size=5000):
                                    sheet_name = f'数据_{batch_idx + 1}' if batch_idx < 26 else f'S{batch_idx + 1}'
                                    batch_df.to_excel(writer, sheet_name=sheet_name, index=False)
                                    batch_idx += 1
                            excel_data = buffer.getvalue()
                            st.download_button(
                                label="下载 Excel 文件",
                                data=excel_data,
                                file_name=f"MGeo相似度匹配结果_{time.strftime('%Y%m%d_%H%M%S')}.xlsx",
                                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                key='download_sim_excel'
                            )
                            st.success(f"Excel文件已生成，共 {batch_idx} 个工作表")
                        except ImportError:
                            st.error("导出Excel需要安装openpyxl库，请运行: pip install openpyxl")
                        except Exception as e:
                            st.error(f"导出Excel失败: {str(e)}")

                st.divider()
                st.subheader("匹配统计")
                sim_stats = data_loader.get_mgeo_similarity_statistics()

                stat_col1, stat_col2, stat_col3, stat_col4 = st.columns(4)
                stat_col1.metric("总记录数", f"{sim_stats['total_count']:,}")
                stat_col2.metric("精确匹配", f"{sim_stats['exact_match_count']:,}", f"{sim_stats['exact_match_rate']:.1f}%")
                stat_col3.metric("部分匹配", f"{sim_stats['partial_match_count']:,}", f"{sim_stats['partial_match_rate']:.1f}%")
                stat_col4.metric("不匹配", f"{sim_stats['not_match_count']:,}", f"{sim_stats['not_match_rate']:.1f}%")

                prob_col1, prob_col2, prob_col3 = st.columns(3)
                prob_col1.metric("平均精确匹配概率", f"{sim_stats['avg_exact_match']:.4f}")
                prob_col2.metric("平均部分匹配概率", f"{sim_stats['avg_partial_match']:.4f}")
                prob_col3.metric("平均不匹配概率", f"{sim_stats['avg_not_match']:.4f}")

                try:
                    import plotly.express as px
                    import plotly.graph_objects as go

                    chart_col1, chart_col2 = st.columns(2)

                    with chart_col1:
                        sim_status_data = {
                            '匹配状态': ['精确匹配', '部分匹配', '不匹配'],
                            '数量': [sim_stats['exact_match_count'], sim_stats['partial_match_count'], sim_stats['not_match_count']]
                        }
                        fig_sim_status = px.pie(sim_status_data, values='数量', names='匹配状态',
                                               title='MGeo相似度匹配状态分布',
                                               color='匹配状态',
                                               color_discrete_map={'精确匹配': '#2ecc71', '部分匹配': '#f39c12', '不匹配': '#e74c3c'})
                        st.plotly_chart(fig_sim_status, use_container_width=True)

                    with chart_col2:
                        sim_prob_data = {
                            '概率类型': ['精确匹配', '部分匹配', '不匹配'],
                            '平均概率': [sim_stats['avg_exact_match'], sim_stats['avg_partial_match'], sim_stats['avg_not_match']]
                        }
                        fig_sim_prob = px.bar(sim_prob_data, x='概率类型', y='平均概率',
                                             title='MGeo相似度匹配概率均值分布',
                                             color='概率类型',
                                             color_discrete_map={'精确匹配': '#2ecc71', '部分匹配': '#f39c12', '不匹配': '#e74c3c'})
                        fig_sim_prob.update_layout(yaxis_range=[0, 1])
                        st.plotly_chart(fig_sim_prob, use_container_width=True)
                except ImportError:
                    st.info("安装plotly可显示统计图表: pip install plotly")

            else:
                st.info("暂无MGeo地址相似度匹配结果，请先在【地址匹配】页面执行MGeo地址相似度匹配")
        except Exception as e:
            st.error(f"查询MGeo相似度匹配结果出错: {e}")

        st.divider()
        st.subheader("📋 MGeo副本表查看")
        try:
            all_tables = db_conn.get_tables() if hasattr(db_conn, 'get_tables') else []
            if not all_tables:
                all_tables = st.session_state.db_conn.get_tables() if st.session_state.get('connected') else []
            mgeo_tables = [t for t in all_tables if t.endswith('_mgeo')]
            if mgeo_tables:
                selected_mgeo_table = st.selectbox("选择MGeo副本表", mgeo_tables, key='mgeo_copy_table_select')
                if selected_mgeo_table:
                    try:
                        count_sql = f"SELECT COUNT(*) as count FROM {selected_mgeo_table}"
                        count_cursor = db_conn.execute(count_sql)
                        mgeo_table_total = count_cursor.fetchone()['count'] if count_cursor else 0

                        if mgeo_table_total > 0:
                            st.info(f"📊 副本表 {selected_mgeo_table} 共 {mgeo_table_total:,} 条记录")

                            mgeo_page_size = st.selectbox("每页显示", options=[10, 20, 50, 100], index=1, key='mgeo_copy_page_size')
                            mgeo_total_pages = (mgeo_table_total + mgeo_page_size - 1) // mgeo_page_size
                            mgeo_page = st.number_input(f"页码 (共{mgeo_total_pages}页)", min_value=1, max_value=mgeo_total_pages, value=1, key='mgeo_copy_page')

                            mgeo_offset = (mgeo_page - 1) * mgeo_page_size
                            mgeo_sql = f"SELECT * FROM {selected_mgeo_table} LIMIT {mgeo_page_size} OFFSET {mgeo_offset}"
                            mgeo_cursor = db_conn.execute(mgeo_sql)
                            if mgeo_cursor:
                                mgeo_rows = mgeo_cursor.fetchall()
                                mgeo_df = pd.DataFrame(mgeo_rows)
                                st.dataframe(mgeo_df, use_container_width=True)

                            export_copy_col1, export_copy_col2 = st.columns(2)
                            with export_copy_col1:
                                if st.button("📥 导出副本表 (CSV)", key='export_mgeo_copy_csv'):
                                    try:
                                        import io
                                        copy_buffer = io.StringIO()
                                        copy_offset = 0
                                        copy_batch = 5000
                                        first_batch = True
                                        while copy_offset < mgeo_table_total:
                                            copy_sql = f"SELECT * FROM {selected_mgeo_table} LIMIT {copy_batch} OFFSET {copy_offset}"
                                            copy_cursor = db_conn.execute(copy_sql)
                                            if copy_cursor:
                                                copy_rows = copy_cursor.fetchall()
                                                if copy_rows:
                                                    pd.DataFrame(copy_rows).to_csv(copy_buffer, index=False, header=first_batch, encoding='utf-8-sig')
                                                    first_batch = False
                                            copy_offset += copy_batch
                                        st.download_button(
                                            label="下载 CSV 文件",
                                            data=copy_buffer.getvalue(),
                                            file_name=f"{selected_mgeo_table}_{time.strftime('%Y%m%d_%H%M%S')}.csv",
                                            mime="text/csv",
                                            key='download_mgeo_copy_csv'
                                        )
                                    except Exception as ex:
                                        st.error(f"导出CSV失败: {str(ex)}")
                            with export_copy_col2:
                                if st.button("📥 导出副本表 (Excel)", key='export_mgeo_copy_excel'):
                                    try:
                                        import io
                                        copy_buffer = io.BytesIO()
                                        with pd.ExcelWriter(copy_buffer, engine='openpyxl') as writer:
                                            copy_offset = 0
                                            copy_batch = 5000
                                            sheet_idx = 0
                                            while copy_offset < mgeo_table_total:
                                                copy_sql = f"SELECT * FROM {selected_mgeo_table} LIMIT {copy_batch} OFFSET {copy_offset}"
                                                copy_cursor = db_conn.execute(copy_sql)
                                                if copy_cursor:
                                                    copy_rows = copy_cursor.fetchall()
                                                    if copy_rows:
                                                        sheet_name = f'数据_{sheet_idx + 1}' if sheet_idx < 26 else f'S{sheet_idx + 1}'
                                                        pd.DataFrame(copy_rows).to_excel(writer, sheet_name=sheet_name, index=False)
                                                        sheet_idx += 1
                                                copy_offset += copy_batch
                                        st.download_button(
                                            label="下载 Excel 文件",
                                            data=copy_buffer.getvalue(),
                                            file_name=f"{selected_mgeo_table}_{time.strftime('%Y%m%d_%H%M%S')}.xlsx",
                                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                            key='download_mgeo_copy_excel'
                                        )
                                    except ImportError:
                                        st.error("导出Excel需要安装openpyxl库")
                                    except Exception as ex:
                                        st.error(f"导出Excel失败: {str(ex)}")
                        else:
                            st.info(f"副本表 {selected_mgeo_table} 为空")
                    except Exception as ex:
                        st.error(f"查询副本表失败: {str(ex)}")
            else:
                st.info("暂无MGeo副本表（库表输入匹配完成后自动生成）")
        except Exception as e:
            st.info("暂无MGeo副本表数据")

    db_conn.close()

def show_system_logs():
    st.subheader("系统日志")
    
    # 显示内存中的日志（实时）
    from utils.logger import get_log_messages, clear_logs
    
    log_messages = get_log_messages()
    if log_messages:
        # 格式化内存日志
        memory_logs = []
        for log in log_messages[-500:]:  # 只显示最近500条
            time_str = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(log['time']))
            memory_logs.append(f"{time_str} - {log['level']} - {log['message']}")
        
        memory_content = '\n'.join(memory_logs)
        st.text_area("实时日志（内存）", memory_content, height=300)
        
        if st.button("清空内存日志"):
            clear_logs()
            st.rerun()
    else:
        st.info("暂无内存日志")
    
    st.divider()
    
    # 显示文件日志
    st.subheader("文件日志")
    try:
        with open('app.log', 'r', encoding='utf-8') as f:
            content = f.read()
            if content:
                st.text_area("日志文件内容", content, height=300)
            else:
                st.info("日志文件为空")
    except FileNotFoundError:
        st.info("暂无日志文件（app.log）")
    except Exception as e:
        st.error(f"读取日志文件失败: {e}")
    
    st.divider()
    
    st.subheader("向量调试测试")
    if st.button("运行向量相似度测试"):
        run_vector_debug_test()

def run_vector_debug_test():
    import numpy as np
    from sklearn.metrics.pairwise import cosine_similarity
    from model.embedding import AddressEmbedder
    import psycopg2
    import pgvector.psycopg2
    
    test_addr = "广州市浦东新区178弄23广场"
    results = []
    
    def add_result(title, status, details):
        results.append({"title": title, "status": status, "details": details})
    
    # 测试1：Python端向量化
    st.subheader("【测试1】Python端向量化")
    try:
        from model.embedding import AddressEmbedder
        import torch
        test_device = st.session_state.get('selected_device', 'cpu')
        if test_device == 'cuda' and not torch.cuda.is_available():
            test_device = 'cpu'
        embedder = AddressEmbedder(device=test_device)
        
        vec1 = embedder.get_embedding(test_addr)
        vec2 = embedder.get_embedding(test_addr)
        
        similarity = cosine_similarity([vec1], [vec2])[0][0]
        
        st.write(f"测试地址: {test_addr}")
        st.write(f"向量维度: {vec1.shape}")
        st.write(f"向量1 L2范数: {np.linalg.norm(vec1):.8f}")
        st.write(f"向量2 L2范数: {np.linalg.norm(vec2):.8f}")
        st.write(f"Python端余弦相似度: {similarity:.8f}")
        device_label = "🖥️ GPU模式运行" if test_device == 'cuda' else "💻 CPU模式运行"
        st.caption(f"当前运行模式: {device_label}")
        
        if similarity > 0.99:
            st.success("✅ Python端向量化正确！")
            add_result("Python端向量化", "✅ 通过", f"相似度={similarity:.8f}")
        else:
            st.error("❌ Python端向量化有问题！")
            add_result("Python端向量化", "❌ 失败", f"相似度={similarity:.8f}")
            
    except Exception as e:
        st.error(f"测试失败: {str(e)}")
        add_result("Python端向量化", "❌ 失败", str(e))
    
    # 测试2：数据库表结构检查
    st.subheader("【测试2】数据库表结构检查")
    try:
        conn = psycopg2.connect(
            host=Config.DB_HOST,
            port=Config.DB_PORT,
            dbname=Config.DB_NAME,
            user=Config.DB_USER,
            password=Config.DB_PASSWORD
        )
        pgvector.psycopg2.register_vector(conn)
        cur = conn.cursor()
        
        st.write("--- 企业向量表结构 ---")
        cur.execute(f"""
            SELECT attname, format_type(atttypid, atttypmod) 
            FROM pg_attribute 
            WHERE attrelid = '{Config.ENTERPRISE_VECTOR_TABLE}'::regclass 
            AND attnum > 0
        """)
        for row in cur.fetchall():
            st.write(f"  {row[0]}: {row[1]}")
        
        st.write("--- 标准地址向量表结构 ---")
        cur.execute(f"""
            SELECT attname, format_type(atttypid, atttypmod) 
            FROM pg_attribute 
            WHERE attrelid = '{Config.STANDARD_VECTOR_TABLE}'::regclass 
            AND attnum > 0
        """)
        for row in cur.fetchall():
            st.write(f"  {row[0]}: {row[1]}")
        
        conn.close()
        st.success("✅ 表结构检查完成")
        add_result("数据库表结构", "✅ 通过", "表结构正确")
        
    except Exception as e:
        st.error(f"测试失败: {str(e)}")
        add_result("数据库表结构", "❌ 失败", str(e))
    
    # 测试3：数据库向量数据检查
    st.subheader("【测试3】数据库向量数据检查")
    try:
        conn = psycopg2.connect(
            host=Config.DB_HOST,
            port=Config.DB_PORT,
            dbname=Config.DB_NAME,
            user=Config.DB_USER,
            password=Config.DB_PASSWORD
        )
        pgvector.psycopg2.register_vector(conn)
        cur = conn.cursor()
        
        st.write("--- 企业向量表数据 ---")
        cur.execute(f"SELECT source_id, address, vector FROM {Config.ENTERPRISE_VECTOR_TABLE} LIMIT 2")
        rows = cur.fetchall()
        for row in rows:
            source_id, address, vec = row
            vec_array = np.array(vec)
            st.write(f"ID: {source_id}")
            st.write(f"地址: {address}")
            st.write(f"向量长度: {len(vec_array)}")
            st.write(f"向量范数: {np.linalg.norm(vec_array):.8f}")
            st.write("")
        
        st.write("--- 标准地址向量表数据 ---")
        cur.execute(f"SELECT source_id, address, vector FROM {Config.STANDARD_VECTOR_TABLE} LIMIT 2")
        rows = cur.fetchall()
        for row in rows:
            source_id, address, vec = row
            vec_array = np.array(vec)
            st.write(f"ID: {source_id}")
            st.write(f"地址: {address}")
            st.write(f"向量长度: {len(vec_array)}")
            st.write(f"向量范数: {np.linalg.norm(vec_array):.8f}")
            st.write("")
        
        st.write("--- 相同地址相似度测试 ---")
        cur.execute(f"""
            SELECT c1.source_id, c1.address, 1 - (c1.vector <=> c2.vector) as similarity
            FROM {Config.ENTERPRISE_VECTOR_TABLE} c1
            JOIN {Config.STANDARD_VECTOR_TABLE} c2 ON c1.address = c2.address
            LIMIT 2
        """)
        rows = cur.fetchall()
        for row in rows:
            source_id, address, similarity = row
            st.write(f"ID: {source_id}")
            st.write(f"地址: {address}")
            st.write(f"相似度: {similarity:.8f}")
            if similarity > 0.99:
                st.success("✅ 相似度正确")
                add_result("数据库相似度", "✅ 通过", f"相似度={similarity:.8f}")
            else:
                st.error("❌ 相似度有问题")
                add_result("数据库相似度", "❌ 失败", f"相似度={similarity:.8f}")
            st.write("")
        
        conn.close()
        
    except Exception as e:
        st.error(f"测试失败: {str(e)}")
        add_result("数据库向量数据", "❌ 失败", str(e))
    
    # 测试4：向量插入测试
    st.subheader("【测试4】向量插入测试")
    try:
        from model.embedding import AddressEmbedder
        import torch
        test_device = st.session_state.get('selected_device', 'cpu')
        if test_device == 'cuda' and not torch.cuda.is_available():
            test_device = 'cpu'
        embedder = AddressEmbedder(device=test_device)
        test_addr_local = "测试地址123"
        vec = embedder.get_embedding(test_addr_local)
        
        st.write(f"原始向量范数: {np.linalg.norm(vec):.8f}")
        device_label = "🖥️ GPU模式运行" if test_device == 'cuda' else "💻 CPU模式运行"
        st.caption(f"当前运行模式: {device_label}")
        
        conn = psycopg2.connect(
            host=Config.DB_HOST,
            port=Config.DB_PORT,
            dbname=Config.DB_NAME,
            user=Config.DB_USER,
            password=Config.DB_PASSWORD
        )
        pgvector.psycopg2.register_vector(conn)
        cur = conn.cursor()
        
        cur.execute(f"DELETE FROM {Config.ENTERPRISE_VECTOR_TABLE} WHERE source_id = 'test_insert'")
        cur.execute(f"""
            INSERT INTO {Config.ENTERPRISE_VECTOR_TABLE} (source_id, enterprise_name, address, vector)
            VALUES (%s, %s, %s, %s)
        """, ('test_insert', '测试企业', test_addr_local, vec))
        conn.commit()
        
        cur.execute(f"SELECT vector FROM {Config.ENTERPRISE_VECTOR_TABLE} WHERE source_id = 'test_insert'")
        row = cur.fetchone()
        stored_vec = np.array(row[0])
        
        st.write(f"存储后向量范数: {np.linalg.norm(stored_vec):.8f}")
        sim = np.dot(vec, stored_vec) / (np.linalg.norm(vec) * np.linalg.norm(stored_vec))
        st.write(f"原始与存储向量相似度: {sim:.8f}")
        
        cur.execute(f"DELETE FROM {Config.ENTERPRISE_VECTOR_TABLE} WHERE source_id = 'test_insert'")
        conn.commit()
        conn.close()
        
        if sim > 0.99:
            st.success("✅ 向量插入测试完成")
            add_result("向量插入", "✅ 通过", f"存储相似度={sim:.8f}")
        else:
            st.error("❌ 向量插入有问题")
            add_result("向量插入", "❌ 失败", f"存储相似度={sim:.8f}")
            
    except Exception as e:
        st.error(f"测试失败: {str(e)}")
        import traceback
        st.write(f"详细错误: {traceback.format_exc()}")
        add_result("向量插入", "❌ 失败", str(e))
    
    # 测试总结
    st.subheader("测试总结")
    for res in results:
        status_color = "green" if res["status"] == "✅ 通过" else "red"
        st.write(f"<span style='color:{status_color}; font-weight:bold;'>{res['status']}</span> {res['title']}: {res['details']}", unsafe_allow_html=True)

def main():
    st.set_page_config(
        page_title="中文地址语义匹配系统",
        page_icon="🏠",
        layout="wide",
        initial_sidebar_state="expanded"
    )
    
    init_session_state()
    
    with st.sidebar:
        st.markdown("""
        <div style='text-align: center; padding: 10px 0;'>
            <h2 style='color: #1e40af; margin: 0;'>🏠 地址匹配系统</h2>
            <p style='color: #64748b; font-size: 12px; margin: 5px 0 0 0;'>Chinese Address Semantic Matching</p>
        </div>
        """, unsafe_allow_html=True)
        
        st.divider()
        
        menu_options = {
            "⚙️ 数据库配置": "数据库配置",
            "📊 向量预处理": "向量预处理",
            "🔍 地址匹配": "地址匹配",
            "📋 结果管理": "结果管理",
            "📝 系统日志": "系统日志"
        }
        
        for display_name, menu_key in menu_options.items():
            if st.button(display_name, key=menu_key, use_container_width=True):
                st.session_state.selected_menu = menu_key
        
        st.divider()
        
        if st.session_state.get('connected'):
            st.success("✅ 数据库已连接")
        else:
            st.error("⚠️ 数据库未连接")
        
        st.divider()
        
        gpu_info = st.session_state.get('gpu_info', {})
        if gpu_info.get('cuda_available'):
            device_label = f"🖥️ GPU: {gpu_info.get('device_name', 'Unknown')}"
            st.success(device_label)
        elif gpu_info.get('has_gpu'):
            st.warning("⚠️ 检测到独立显卡但无法使用GPU")
            if gpu_info.get('warning'):
                st.caption(gpu_info['warning'])
        else:
            st.info("💻 CPU模式运行")
        
        st.caption("v1.0 | Powered by MGeo")
    
    st.markdown("""
    <div style='padding: 10px 0 5px 0;'>
        <h1 style='color: #1e40af; margin: 0; font-size: 28px;'>🏠 中文地址语义匹配系统</h1>
        <p style='color: #64748b; font-size: 14px; margin: 5px 0 0 0;'>
            企业地址与标准地址的智能匹配平台 — 向量粗召回 + MGeo精排
        </p>
    </div>
    """, unsafe_allow_html=True)
    
    st.divider()
    
    selected_menu = st.session_state.selected_menu
    
    if selected_menu == "数据库配置":
        show_db_config()
    elif selected_menu == "向量预处理":
        show_vector_preprocess()
    elif selected_menu == "地址匹配":
        show_address_matching()
    elif selected_menu == "结果管理":
        show_result_management()
    elif selected_menu == "系统日志":
        show_system_logs()

if __name__ == "__main__":
    main()