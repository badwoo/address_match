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
from database.connection import DBConnection, quote_identifier
from database.data_loader import DataLoader
from database.vector_store import VectorStore
from config import Config
from utils.logger import logger, setup_db_logging
from utils.pinyin_utils import tag_to_prefix, get_tag_tables
from database.tag_manager import TagManager
from ui_theme import Colors, Spacing, Typography, Radius, Shadow, card_style, status_container_style, inject_global_styles

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

def _next_page(key, total_pages_key_or_val):
    """翻页回调：下一页。total_pages_key_or_val 可以是 session_state key 或直接的总页数值"""
    if isinstance(total_pages_key_or_val, int):
        total = total_pages_key_or_val
    else:
        total = st.session_state.get(total_pages_key_or_val, 1)
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

    # 地址结构化解析状态
    if 'address_tagging_status' not in st.session_state:
        st.session_state.address_tagging_status = {
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

    # 地址17级结构化解析状态
    if 'address_tagging_17_status' not in st.session_state:
        st.session_state.address_tagging_17_status = {
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

    # 地址17级双字段结构化解析状态
    if 'address_tagging_17_2_status' not in st.session_state:
        st.session_state.address_tagging_17_2_status = {
            'is_running': False, 'progress': 0.0,
            'processed_count': 0, 'total_count': 0,
            'speed': 0.0, 'remaining_time': 0.0,
            'status_message': '', 'error_message': '',
            'start_time': None, 'end_time': None,
            'completed': False, 'result_count': 0,
            'input_type': 'file', 'source_table': '', 'copy_table': ''
        }

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
                setup_db_logging(db_conn)
                logger.warning("Database connection established")
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

def _reset_address_tagging_status(input_type='file'):
    """重置地址结构化解析状态"""
    return {
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

def show_address_tagging():
    """
    地址结构化解析页面（含两个页签）

    - 左页签：地址17级分词（MGeo）— 使用MGeo模型原始17级NER标签
    - 右页签：地址12级分词 — 使用合并映射后的12级结构化输出
    """
    st.markdown(f"<div class='status-card status-card-info'>", unsafe_allow_html=True)
    st.subheader("地址结构化解析")
    st.caption("调用MGeo门址地址结构化要素解析模型，将地址拆分为结构化要素")

    tab_17, tab_12, tab_17_2 = st.tabs(["地址17级分词（MGeo）", "地址12级分词", "地址17级分词（MGeo）2"])
    with tab_17:
        _show_address_tagging_panel(mode='17')
    with tab_12:
        _show_address_tagging_panel(mode='12')
    with tab_17_2:
        _show_address_tagging_panel(mode='17_2')

    st.markdown("</div>", unsafe_allow_html=True)


def _show_address_tagging_panel(mode='12'):
    """
    地址结构化解析面板（参数化，支持12级、17级、17_2模式）

    Args:
        mode: '12' / '17' / '17_2'
    """
    is_17 = (mode == '17')
    is_17_2 = (mode == '17_2')

    if is_17_2:
        level_label = '17级（双字段）'
        status_prefix = 'address_tagging_17_2'
    elif is_17:
        level_label = '17级（MGeo）'
        status_prefix = 'address_tagging_17'
    else:
        level_label = '12级'
        status_prefix = 'address_tagging'

    status_key = f'{status_prefix}_status'
    results_key = f'{status_prefix}_results'
    parser_key = f'{status_prefix}_parser'
    uploaded_df_key = f'{status_prefix}_uploaded_df'
    selected_table_key = f'{status_prefix}_selected_table'
    selected_addr_key = f'{status_prefix}_selected_addr_col'
    finished_trigger_key = f'{status_prefix}_finished_trigger'

    from model.address_tagging_model import (
        OUTPUT_FIELDS, OUTPUT_FIELD_LABELS,
        OUTPUT_FIELDS_17, OUTPUT_FIELD_LABELS_17,
        OUTPUT_FIELDS_17_2, OUTPUT_FIELD_LABELS_17_2
    )
    if is_17_2:
        fields = OUTPUT_FIELDS_17_2
        field_labels = OUTPUT_FIELD_LABELS_17_2
    elif is_17:
        fields = OUTPUT_FIELDS_17
        field_labels = OUTPUT_FIELD_LABELS_17
    else:
        fields = OUTPUT_FIELDS
        field_labels = OUTPUT_FIELD_LABELS

    tag_device = _render_device_selector(key=f'address_tagging_{mode}_device_selector')

    if status_key not in st.session_state:
        st.session_state[status_key] = _reset_address_tagging_status()

    tagging_status = st.session_state[status_key]

    if st.session_state.get(finished_trigger_key):
        logger.info(f"[地址{level_label}结构化解析] 检测到完成触发器，清除并刷新")
        del st.session_state[finished_trigger_key]
        st.rerun()

    # ---- 运行中 ----
    if tagging_status['is_running']:
        if parser_key in st.session_state and st.session_state[parser_key]:
            try:
                parser_stat = st.session_state[parser_key].get_status()
                st.session_state[status_key].update({
                    'is_running': parser_stat['is_running'],
                    'progress': parser_stat['progress'],
                    'processed_count': parser_stat['processed_count'],
                    'total_count': parser_stat['total_count'],
                    'speed': parser_stat['speed'],
                    'remaining_time': parser_stat['remaining_time'],
                    'status_message': parser_stat['status_message'],
                    'error_message': parser_stat['error_message']
                })

                if parser_stat.get('completed'):
                    end_time = parser_stat.get('completion_end_time', time.time())
                    if parser_stat.get('completion_success'):
                        # 流式模式下 completion_results 为 None，用 processed_count 作为 result_count
                        result_count = len(parser_stat['completion_results']) if parser_stat.get('completion_results') else parser_stat.get('processed_count', 0)
                        st.session_state[status_key].update({
                            'is_running': False,
                            'completed': True,
                            'end_time': end_time,
                            'result_count': result_count,
                            'status_message': '解析完成',
                            'progress': 1.0
                        })
                        if tagging_status.get('input_type') == 'file' and parser_stat.get('completion_results'):
                            st.session_state[results_key] = parser_stat['completion_results']
                        if parser_stat.get('completion_source_table'):
                            st.session_state[status_key].update({
                                'source_table': parser_stat['completion_source_table'],
                                'copy_table': parser_stat['completion_copy_table']
                            })
                    else:
                        st.session_state[status_key].update({
                            'is_running': False,
                            'completed': False,
                            'end_time': end_time,
                            'error_message': parser_stat.get('completion_message', ''),
                            'status_message': f"解析失败: {parser_stat.get('completion_message', '')}"
                        })

                tagging_status = st.session_state[status_key]
            except Exception as e:
                logger.error(f"获取地址{level_label}结构化解析状态失败: {e}")

        st.markdown(f"<div class='status-card status-card-warning'>", unsafe_allow_html=True)
        st.subheader(f"地址{level_label}结构化解析执行状态")

        if tagging_status['start_time']:
            start_time_str = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(tagging_status['start_time']))
            elapsed = time.time() - tagging_status['start_time']
            st.write(f"**开始时间**: {start_time_str}")
            st.write(f"**已运行时间**: {format_time(elapsed)}")

        st.progress(tagging_status['progress'])
        st.write(f"**处理进度**: {tagging_status['processed_count']:,}/{tagging_status['total_count']:,} ({tagging_status['progress'] * 100:.1f}%)")
        st.write(f"**处理速度**: {tagging_status['speed']:.2f} 条/秒")
        st.write(f"**预计剩余时间**: {format_time(tagging_status['remaining_time'])}")
        st.write(f"**状态**: {tagging_status['status_message']}")

        if st.button("⏹️ 取消解析", key=f'cancel_address_tagging_{mode}'):
            if parser_key in st.session_state:
                st.session_state[parser_key].stop()
            st.session_state[status_key].update({
                'is_running': False, 'progress': 0.0,
                'status_message': '已取消', 'error_message': ''
            })
            st.success("解析已取消")
            st.rerun()

        st.markdown("</div>", unsafe_allow_html=True)
        time.sleep(1)
        st.rerun()

    # ---- 完成 ----
    if tagging_status['completed']:
        st.markdown(f"<div class='status-card status-card-success'>", unsafe_allow_html=True)
        st.subheader(f"地址{level_label}结构化解析完成")

        if tagging_status['start_time'] and tagging_status['end_time']:
            duration = tagging_status['end_time'] - tagging_status['start_time']
            st.write(f"**开始时间**: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(tagging_status['start_time']))}")
            st.write(f"**结束时间**: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(tagging_status['end_time']))}")
            st.write(f"**耗时**: {format_time(duration)}")

        st.write(f"**解析结果数**: {tagging_status['result_count']:,}")

        input_type = tagging_status.get('input_type', 'file')

        if input_type == 'file':
            if results_key in st.session_state and st.session_state[results_key]:
                result_df = pd.DataFrame(st.session_state[results_key])
                st.subheader("结果下载")
                dl_col1, dl_col2 = st.columns(2)
                with dl_col1:
                    try:
                        import io
                        excel_buffer = io.BytesIO()
                        with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
                            result_df.to_excel(writer, index=False, sheet_name='解析结果')
                        st.download_button(
                            label="📥 下载Excel格式",
                            data=excel_buffer.getvalue(),
                            file_name=f"地址{level_label}结构化解析结果_{time.strftime('%Y%m%d_%H%M%S')}.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            key=f'download_tagging_{mode}_result_excel'
                        )
                    except ImportError:
                        st.warning("导出Excel需要openpyxl库")
                with dl_col2:
                    try:
                        import io
                        csv_buffer = io.StringIO()
                        result_df.to_csv(csv_buffer, index=False, encoding='utf-8-sig')
                        st.download_button(
                            label="📥 下载CSV格式",
                            data=csv_buffer.getvalue(),
                            file_name=f"地址{level_label}结构化解析结果_{time.strftime('%Y%m%d_%H%M%S')}.csv",
                            mime="text/csv",
                            key=f'download_tagging_{mode}_result_csv'
                        )
                    except Exception as e:
                        st.warning(f"导出CSV失败: {str(e)}")
            else:
                st.info("结果数据不可用")

            st.divider()
            col1, col2 = st.columns(2)
            with col1:
                if st.button("🔄 重新解析", key=f'restart_address_tagging_{mode}'):
                    st.session_state[status_key] = _reset_address_tagging_status()
                    if results_key in st.session_state:
                        del st.session_state[results_key]
                    st.rerun()
            with col2:
                if st.button("↩️ 返回", key=f'back_address_tagging_{mode}_file'):
                    st.session_state[status_key] = _reset_address_tagging_status()
                    if results_key in st.session_state:
                        del st.session_state[results_key]
                    st.rerun()
        else:
            col1, col2, col3 = st.columns(3)
            with col1:
                if is_17_2:
                    result_tab_name = "地址17级双字段结构化解析结果"
                elif is_17:
                    result_tab_name = "地址17级结构化解析结果"
                else:
                    result_tab_name = "地址结构化解析结果"
                if st.button("📊 结果查看", key=f'view_address_tagging_{mode}_result'):
                    st.session_state.selected_menu = "结果管理"
                    st.session_state.result_management_active_tab = result_tab_name
                    st.rerun()
            with col2:
                if st.button("🔄 重新解析", key=f'restart_address_tagging_{mode}_db'):
                    st.session_state[status_key] = _reset_address_tagging_status('database')
                    st.rerun()
            with col3:
                if st.button("↩️ 返回", key=f'back_address_tagging_{mode}_db'):
                    st.session_state[status_key] = _reset_address_tagging_status('database')
                    st.rerun()

            if tagging_status.get('copy_table'):
                st.info(f"📋 副本表: {tagging_status['copy_table']}")

        st.markdown("</div>", unsafe_allow_html=True)
        return

    # ---- 输入选择 ----
    input_type = st.radio(
        "数据输入方式",
        options=['file', 'database'],
        format_func=lambda x: '📁 上传文件（CSV/Excel）' if x == 'file' else '🗄️ 数据库表',
        key=f'address_tagging_{mode}_input_type',
        horizontal=True
    )

    address_col = ''
    df_preview = None

    if input_type == 'file':
        uploaded_file = st.file_uploader(
            "上传数据文件",
            type=['csv', 'xlsx', 'xls'],
            key=f'address_tagging_{mode}_file_upload'
        )

        if uploaded_file is not None:
            try:
                if uploaded_file.name.endswith('.csv'):
                    df_preview, detected_encoding = read_csv_with_encoding(uploaded_file, nrows=5)
                    uploaded_file.seek(0)
                    st.session_state[uploaded_df_key], _ = read_csv_with_encoding(uploaded_file)
                    st.caption(f"检测到文件编码: {detected_encoding}")
                elif uploaded_file.name.endswith(('.xlsx', '.xls')):
                    df_preview = pd.read_excel(uploaded_file, nrows=5)
                    st.session_state[uploaded_df_key] = pd.read_excel(uploaded_file)

                if df_preview is not None:
                    st.success(f"✅ 文件加载成功：{uploaded_file.name}，共 {len(st.session_state[uploaded_df_key]):,} 行")
                    with st.expander("数据预览", expanded=False):
                        st.dataframe(df_preview, use_container_width=True)

                    columns = list(st.session_state[uploaded_df_key].columns)
                    address_col = st.selectbox(
                        "选择地址字段",
                        options=columns,
                        key=f'address_tagging_{mode}_addr_col_file'
                    )
                    # 17/17_2模式：额外选择标识字段
                    id_field = ''
                    if is_17 or is_17_2:
                        id_options = [''] + columns
                        id_field = st.selectbox(
                            "选择标识字段（可选，用于标识每条记录，如ID）",
                            options=id_options,
                            key=f'address_tagging_{mode}_id_col_file'
                        )
                        st.session_state[f'{status_prefix}_selected_id_field'] = id_field
            except Exception as e:
                st.error(f"文件加载失败: {str(e)}")
    else:
        if not st.session_state.connected:
            st.warning("⚠️ 请先在【数据库配置】页面连接数据库")
            return

        db_config = st.session_state.db_config
        db_conn = DBConnection(
            host=db_config['host'], port=db_config['port'],
            schema=db_config['schema'], dbname=db_config['dbname'],
            user=db_config['user'], password=db_config['password']
        )

        if not db_conn.connect():
            st.error("无法连接数据库")
            return

        try:
            tables = db_conn.get_tables()
            if not tables:
                st.warning("数据库中没有可用的数据表")
                db_conn.close()
                return

            selected_table = st.selectbox("选择数据表", options=tables, key=f'address_tagging_{mode}_db_table')

            if selected_table:
                columns = [col[0] for col in db_conn.get_columns(selected_table)]
                address_col = st.selectbox("选择地址字段", options=columns, key=f'address_tagging_{mode}_addr_col_db')

                st.session_state[selected_table_key] = selected_table
                st.session_state[selected_addr_key] = address_col

                # 17/17_2模式：额外选择标识字段
                id_field = ''
                if is_17 or is_17_2:
                    id_options = [''] + columns
                    id_field = st.selectbox(
                        "选择标识字段（可选，用于标识每条记录，如ID）",
                        options=id_options,
                        key=f'address_tagging_{mode}_id_col_db'
                    )
                    st.session_state[f'{status_prefix}_selected_id_field'] = id_field

                count_sql = f"SELECT COUNT(*) as count FROM {quote_identifier(selected_table)}"
                count_cursor = db_conn.execute(count_sql)
                if count_cursor:
                    total = count_cursor.fetchone()['count']
                    st.info(f"📊 表 {selected_table} 共 {total:,} 条记录")
        except Exception as e:
            st.error(f"获取表信息失败: {str(e)}")
        finally:
            db_conn.close()

    st.divider()

    can_start = False
    if input_type == 'file':
        can_start = (uploaded_df_key in st.session_state and address_col)
    else:
        can_start = (selected_table_key in st.session_state and address_col)

    if can_start:
        if st.button(f"🚀 启动地址{level_label}结构化解析", key=f'start_address_tagging_{mode}', type='primary'):
            _start_address_tagging(st.session_state.db_config, tag_device, input_type, address_col, mode)
    else:
        st.info("请先选择数据源和地址字段")


def _start_address_tagging(db_config, device, input_type, address_col, mode='12'):
    """启动地址结构化解析（支持12级、17级和17_2模式）"""
    is_17 = (mode == '17')
    is_17_2 = (mode == '17_2')

    if is_17_2:
        level_label = '17级（双字段）'
        status_prefix = 'address_tagging_17_2'
    elif is_17:
        level_label = '17级（MGeo）'
        status_prefix = 'address_tagging_17'
    else:
        level_label = '12级'
        status_prefix = 'address_tagging'

    status_key = f'{status_prefix}_status'
    results_key = f'{status_prefix}_results'
    parser_key = f'{status_prefix}_parser'
    uploaded_df_key = f'{status_prefix}_uploaded_df'
    selected_table_key = f'{status_prefix}_selected_table'

    # 获取17/17_2模式的标识字段
    id_field = ''
    if is_17 or is_17_2:
        id_field = st.session_state.get(f'{status_prefix}_selected_id_field', '')

    try:
        from matching.address_tagging import AddressTaggingParser, run_address_tagging_async

        if status_key not in st.session_state:
            st.session_state[status_key] = _reset_address_tagging_status()

        parser = AddressTaggingParser(device=device, mode=mode)
        st.session_state[parser_key] = parser

        start_time = time.time()

        st.session_state[status_key].update({
            'is_running': True, 'progress': 0.0,
            'processed_count': 0, 'total_count': 0,
            'speed': 0.0, 'remaining_time': 0.0,
            'status_message': '正在初始化...', 'error_message': '',
            'start_time': start_time, 'end_time': None,
            'completed': False, 'result_count': 0,
            'input_type': input_type
        })

        db_conn = None
        table_name = None

        if input_type == 'file':
            data_source = st.session_state[uploaded_df_key]
        else:
            data_source = None
            table_name = st.session_state[selected_table_key]

        # 建立数据库连接，用于结果持久化（库表模式必需，文件模式可选）
        if st.session_state.get('connected', False):
            db_conn = DBConnection(
                host=db_config['host'], port=db_config['port'],
                schema=db_config['schema'], dbname=db_config['dbname'],
                user=db_config['user'], password=db_config['password']
            )
            if not db_conn.connect():
                if input_type == 'database':
                    st.error("无法连接数据库，请检查数据库配置")
                    st.session_state[status_key].update({
                        'is_running': False, 'error_message': '无法连接数据库',
                        'status_message': '连接数据库失败'
                    })
                    return
                logger.warning(f"[地址{level_label}结构化解析] 数据库连接失败，结果将不会持久化")
                db_conn = None

        db_conn_ref = db_conn

        def on_completed(success, message, results):
            logger.info(f"[地址{level_label}结构化解析] 回调触发: success={success}, message={message}")
            if db_conn_ref:
                try:
                    db_conn_ref.close()
                except Exception:
                    pass

        run_address_tagging_async(
            parser=parser, data_source=data_source,
            address_col=address_col, db_conn=db_conn,
            table_name=table_name,
            completed_callback=on_completed, mode=mode, id_field=id_field
        )

        st.success(f"地址{level_label}结构化解析任务已启动！")
        st.rerun()

    except Exception as e:
        st.error(f"启动失败: {str(e)}")
        import traceback
        st.write(f"详细错误: {traceback.format_exc()}")
        logger.error(f"地址{level_label}结构化解析启动失败: {str(e)}")


@st.cache_resource(ttl=60, show_spinner=False)
def _get_cached_db_connection(host, port, dbname, user, password, schema):
    """缓存的 DB 连接，避免每次 st.rerun() 都重建 TCP 连接。TTL=60s。"""
    conn = DBConnection(host=host, port=port, schema=schema, dbname=dbname, user=user, password=password)
    if conn.connect():
        return conn
    return None

def show_vector_preprocess():
    """向量预处理页面：配置企业表和标准地址表的字段映射，执行向量化"""
    db_ready = True
    tables = []
    vector_store = None

    if not st.session_state.connected:
        st.warning("⚠️ 向量预处理功能需要数据库连接，请先在【数据库配置】页面配置并连接数据库")
        db_ready = False

    db_conn = None
    if db_ready:
        db_config = st.session_state.db_config
        db_conn = _get_cached_db_connection(
            host=db_config['host'],
            port=db_config['port'],
            schema=db_config['schema'],
            dbname=db_config['dbname'],
            user=db_config['user'],
            password=db_config['password']
        )
        if db_conn is None:
            st.error("无法连接数据库，请检查配置")
            db_ready = False

    if db_ready:
        try:
            tables = db_conn.get_tables()
            if not tables:
                st.warning("数据库中没有可用的数据表")
                db_ready = False
        except Exception as e:
            st.error(f"获取数据表列表失败: {str(e)}")
            db_ready = False

    if db_ready:
        vector_store = VectorStore(db_conn)

    # ========== 页面级统一按钮样式 ==========
    st.markdown(f"""
    <style>
    .vec-page-btn {{
        height: 36px !important;
        font-size: 14px !important;
        font-weight: 500 !important;
        border-radius: {Radius.SM} !important;
        border-width: 1px !important;
        border-style: solid !important;
        box-shadow: none !important;
        transition: all 0.15s ease !important;
        padding: 0 16px !important;
    }}
    .vec-page-btn:hover {{
        transform: translateY(-1px);
        box-shadow: 0 2px 4px rgba(0,0,0,0.08) !important;
    }}

    /* 主操作按钮 - 蓝色 */
    .vec-btn-primary {{
        background-color: {Colors.PRIMARY_LIGHT} !important;
        border-color: {Colors.PRIMARY_LIGHT} !important;
        color: white !important;
    }}
    .vec-btn-primary:hover {{
        background-color: {Colors.PRIMARY} !important;
        border-color: {Colors.PRIMARY} !important;
    }}

    /* 次要操作按钮 - 浅蓝 */
    .vec-btn-secondary {{
        background-color: {Colors.INFO_BG} !important;
        border-color: {Colors.INFO_BORDER} !important;
        color: {Colors.INFO} !important;
    }}
    .vec-btn-secondary:hover {{
        background-color: #bfdbfe !important;
        border-color: {Colors.PRIMARY} !important;
        color: {Colors.PRIMARY} !important;
    }}

    /* 警告操作按钮 - 浅黄 */
    .vec-btn-warning {{
        background-color: {Colors.WARNING_BG} !important;
        border-color: {Colors.WARNING_BORDER} !important;
        color: {Colors.WARNING} !important;
    }}
    .vec-btn-warning:hover {{
        background-color: #fde68a !important;
        border-color: #ca8a04 !important;
        color: #713f12 !important;
    }}

    /* 危险操作按钮 - 浅红 */
    .vec-btn-danger {{
        background-color: {Colors.ERROR_BG} !important;
        border-color: {Colors.ERROR_BORDER} !important;
        color: {Colors.ERROR} !important;
    }}
    .vec-btn-danger:hover {{
        background-color: #fecaca !important;
        border-color: #b91c1c !important;
        color: #7f1d1d !important;
    }}

    /* 模块标题样式 */
    .vec-module-title {{
        font-size: 16px;
        font-weight: {Typography.WEIGHT_SEMIBOLD};
        color: {Colors.TEXT_PRIMARY};
        margin: 0 0 12px 0;
        padding-bottom: 8px;
        border-bottom: 2px solid {Colors.PRIMARY};
        display: flex;
        align-items: center;
        gap: 8px;
    }}
    .vec-step-num {{
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 24px;
        height: 24px;
        border-radius: 50%;
        background: {Colors.PRIMARY};
        color: white;
        font-size: 12px;
        font-weight: 700;
        flex-shrink: 0;
    }}

    /* 小标签样式 */
    .vec-badge {{
        display: inline-flex;
        align-items: center;
        padding: 2px 8px;
        border-radius: {Radius.SM};
        font-size: 12px;
        font-weight: 500;
        margin-left: 8px;
    }}
    .vec-badge-blue {{
        background-color: {Colors.INFO_BG};
        color: {Colors.INFO};
    }}
    .vec-badge-green {{
        background-color: {Colors.SUCCESS_BG};
        color: {Colors.SUCCESS};
    }}
    .vec-badge-gray {{
        background-color: {Colors.SURFACE_SECONDARY};
        color: {Colors.TEXT_MUTED};
    }}

    </style>
    """, unsafe_allow_html=True)

    # ========== 步骤1：向量表创建与配置 ==========
    st.markdown('<div class="vec-module-title"><span class="vec-step-num">1</span> 向量表创建与字段配置</div>', unsafe_allow_html=True)

    # 创建向量表 + 向量表管理 左右布局
    create_col, manage_col = st.columns([3, 2])

    with create_col:
        # 企业表配置
        with st.container(border=True):
            ent_vec_table = st.session_state.vec_config.get('enterprise_vector_table', Config.ENTERPRISE_VECTOR_TABLE)
            ent_table_exists = vector_store.check_table_exists(ent_vec_table) if db_ready else False
            ent_count_in_table = vector_store.get_vector_count(ent_vec_table) if ent_table_exists else 0

            st.markdown(
                f'<div style="font-weight: {Typography.WEIGHT_SEMIBOLD}; font-size: 14px; margin-bottom: 10px;">'
                f'🏢 企业表配置'
                f'<span class="vec-badge vec-badge-{"green" if ent_count_in_table > 0 else "gray"}">'
                f'{ent_count_in_table:,} 条</span></div>',
                unsafe_allow_html=True
            )

            ent_col1, ent_col2 = st.columns([1, 1])
            with ent_col1:
                # 构建选项列表，始终包含已保存的值，防止 db 异常时 selectbox 被迫重置
                _ent_options = [''] + tables
                _saved_ent_table = st.session_state.vec_config.get('enterprise_table', '')
                if _saved_ent_table and _saved_ent_table not in _ent_options:
                    _ent_options.append(_saved_ent_table)

                # session_state 恢复机制：仅在 widget 值失效时从 vec_config 恢复
                _current_ent = st.session_state.get('enterprise_table_vec', '')
                if not _current_ent or _current_ent not in _ent_options:
                    if _saved_ent_table and _saved_ent_table in _ent_options:
                        st.session_state['enterprise_table_vec'] = _saved_ent_table

                enterprise_table = st.selectbox(
                    "选择企业表",
                    _ent_options,
                    key='enterprise_table_vec'
                )
                if enterprise_table and enterprise_table != st.session_state.vec_config.get('enterprise_table'):
                    st.session_state.vec_config['enterprise_id_col'] = ''
                    st.session_state.vec_config['enterprise_name_col'] = ''
                    st.session_state.vec_config['enterprise_address_col'] = ''
                    _mapping = st.session_state.vec_config.get('table_vec_mapping', {})
                    new_ent_vec_table = _mapping.get(enterprise_table, f"{enterprise_table}_vectors")
                    st.session_state.vec_config['enterprise_vector_table'] = new_ent_vec_table
                    # 清理旧表的字段选择状态
                    for key in ['enterprise_id_vec', 'enterprise_name_vec', 'enterprise_addr_vec']:
                        if key in st.session_state:
                            del st.session_state[key]
                if enterprise_table:
                    st.session_state.vec_config['enterprise_table'] = enterprise_table
                # 重新计算：selectbox change handler 可能已更新 vec_config，确保后续 text_input 使用最新值
                ent_vec_table = st.session_state.vec_config.get('enterprise_vector_table', Config.ENTERPRISE_VECTOR_TABLE)

            enterprise_columns = []
            if enterprise_table and db_conn:
                try:
                    enterprise_columns = [col[0] for col in db_conn.get_columns(enterprise_table)]
                except Exception as e:
                    st.error(f"获取企业表字段失败: {str(e)}")
                    enterprise_columns = []

            with ent_col2:
                if enterprise_columns:
                    # session_state 恢复机制：仅在 widget 值失效时从 vec_config 恢复
                    _current_id_val = st.session_state.get('enterprise_id_vec', '')
                    _current_name_val = st.session_state.get('enterprise_name_vec', '')
                    _current_addr_val = st.session_state.get('enterprise_addr_vec', '')
                    if _current_id_val not in enterprise_columns:
                        _saved_id = st.session_state.vec_config.get('enterprise_id_col', '')
                        if _saved_id and _saved_id in enterprise_columns:
                            st.session_state['enterprise_id_vec'] = _saved_id
                    if _current_name_val not in enterprise_columns:
                        _saved_name = st.session_state.vec_config.get('enterprise_name_col', '')
                        if _saved_name and _saved_name in enterprise_columns:
                            st.session_state['enterprise_name_vec'] = _saved_name
                    if _current_addr_val not in enterprise_columns:
                        _saved_addr = st.session_state.vec_config.get('enterprise_address_col', '')
                        if _saved_addr and _saved_addr in enterprise_columns:
                            st.session_state['enterprise_addr_vec'] = _saved_addr

                    st.session_state.vec_config['enterprise_id_col'] = st.selectbox(
                        "企业标识字段", enterprise_columns, key='enterprise_id_vec')
                    st.session_state.vec_config['enterprise_name_col'] = st.selectbox(
                        "企业名字段", enterprise_columns, key='enterprise_name_vec')
                    st.session_state.vec_config['enterprise_address_col'] = st.selectbox(
                        "企业地址字段", enterprise_columns, key='enterprise_addr_vec')
                else:
                    # 保留 widget key，避免 Streamlit 因 widget 未渲染而删除 session_state
                    # 优先从 session_state 取，为空则从 vec_config 恢复
                    _cur_id = st.session_state.get('enterprise_id_vec', '') or st.session_state.vec_config.get('enterprise_id_col', '')
                    _cur_name = st.session_state.get('enterprise_name_vec', '') or st.session_state.vec_config.get('enterprise_name_col', '')
                    _cur_addr = st.session_state.get('enterprise_addr_vec', '') or st.session_state.vec_config.get('enterprise_address_col', '')
                    st.selectbox("企业标识字段", [_cur_id] if _cur_id else ['请先选择企业表'],
                                disabled=True, key='enterprise_id_vec')
                    st.selectbox("企业名字段", [_cur_name] if _cur_name else ['请先选择企业表'],
                                disabled=True, key='enterprise_name_vec')
                    st.selectbox("企业地址字段", [_cur_addr] if _cur_addr else ['请先选择企业表'],
                                disabled=True, key='enterprise_addr_vec')

            # 自定义向量表名
            st.markdown('<div style="font-size: 12px; color: {Colors.TEXT_SECONDARY}; margin: 8px 0 4px 0;">向量表名</div>'.format(Colors=Colors), unsafe_allow_html=True)
            ent_name_col1, ent_name_col2 = st.columns([3, 1])
            with ent_name_col1:
                # 使用包含表名的动态 key，确保切换表时 widget 状态重置
                _ent_name_key = f'enterprise_vector_table_name_{enterprise_table}' if enterprise_table else 'enterprise_vector_table_name'
                ent_custom_name = st.text_input(
                    "企业向量表名",
                    value=ent_vec_table,
                    key=_ent_name_key,
                    label_visibility="collapsed",
                    help="可自定义企业向量表名称，默认为系统自动生成"
                )
                if ent_custom_name and ent_custom_name != ent_vec_table:
                    st.session_state.vec_config['enterprise_vector_table'] = ent_custom_name.strip()
            with ent_name_col2:
                if st.button("创建", key='create_ent_btn',
                            help="创建企业向量表（如已存在则跳过）", disabled=not db_ready):
                    if db_ready:
                        with st.spinner("正在创建..."):
                            target_name = st.session_state.vec_config.get('enterprise_vector_table', Config.ENTERPRISE_VECTOR_TABLE)
                            src_table = st.session_state.vec_config.get('enterprise_table', '')
                            if vector_store.check_table_exists(target_name):
                                st.info(f"企业向量表 {target_name} 已存在，无需重复创建")
                                if src_table:
                                    st.session_state.vec_config.setdefault('table_vec_mapping', {})[src_table] = target_name
                            elif vector_store.create_vector_table(target_name, table_type='enterprise'):
                                st.success(f"企业向量表 {target_name} 创建成功")
                                if src_table:
                                    st.session_state.vec_config.setdefault('table_vec_mapping', {})[src_table] = target_name
                            else:
                                st.error("创建失败，请查看日志")

        # 标准地址表配置
        with st.container(border=True):
            std_vec_table = st.session_state.vec_config.get('standard_vector_table', Config.STANDARD_VECTOR_TABLE)
            std_table_exists = vector_store.check_table_exists(std_vec_table) if db_ready else False
            std_count_in_table = vector_store.get_vector_count(std_vec_table) if std_table_exists else 0

            st.markdown(
                f'<div style="font-weight: {Typography.WEIGHT_SEMIBOLD}; font-size: 14px; margin-bottom: 10px;">'
                f'📍 标准地址表配置'
                f'<span class="vec-badge vec-badge-{"green" if std_count_in_table > 0 else "gray"}">'
                f'{std_count_in_table:,} 条</span></div>',
                unsafe_allow_html=True
            )

            std_col1, std_col2 = st.columns([1, 1])
            with std_col1:
                # 构建选项列表，始终包含已保存的值，防止 db 异常时 selectbox 被迫重置
                _std_options = [''] + tables
                _saved_std_table = st.session_state.vec_config.get('standard_table', '')
                if _saved_std_table and _saved_std_table not in _std_options:
                    _std_options.append(_saved_std_table)

                # session_state 恢复机制：仅在 widget 值失效时从 vec_config 恢复
                _current_std = st.session_state.get('standard_table_vec', '')
                if not _current_std or _current_std not in _std_options:
                    if _saved_std_table and _saved_std_table in _std_options:
                        st.session_state['standard_table_vec'] = _saved_std_table

                standard_table = st.selectbox(
                    "选择标准地址表",
                    _std_options,
                    key='standard_table_vec'
                )
                if standard_table and standard_table != st.session_state.vec_config.get('standard_table'):
                    st.session_state.vec_config['standard_id_col'] = ''
                    st.session_state.vec_config['standard_address_col'] = ''
                    st.session_state.vec_config['standard_room_col'] = ''
                    _mapping = st.session_state.vec_config.get('table_vec_mapping', {})
                    new_std_vec_table = _mapping.get(standard_table, f"{standard_table}_vectors")
                    st.session_state.vec_config['standard_vector_table'] = new_std_vec_table
                    # 清理旧表的字段选择状态
                    for key in ['standard_id_vec', 'standard_addr_vec', 'standard_room_vec']:
                        if key in st.session_state:
                            del st.session_state[key]
                if standard_table:
                    st.session_state.vec_config['standard_table'] = standard_table
                # 重新计算：selectbox change handler 可能已更新 vec_config，确保后续 text_input 使用最新值
                std_vec_table = st.session_state.vec_config.get('standard_vector_table', Config.STANDARD_VECTOR_TABLE)

            standard_columns = []
            if standard_table and db_conn:
                try:
                    standard_columns = [col[0] for col in db_conn.get_columns(standard_table)]
                except Exception as e:
                    st.error(f"获取标准地址表字段失败: {str(e)}")
                    standard_columns = []

            with std_col2:
                if standard_columns:
                    # session_state 恢复机制：仅在 widget 值失效时从 vec_config 恢复
                    _current_std_id = st.session_state.get('standard_id_vec', '')
                    _current_std_addr = st.session_state.get('standard_addr_vec', '')
                    _current_std_room = st.session_state.get('standard_room_vec', '')
                    if _current_std_id not in standard_columns:
                        _saved_std_id = st.session_state.vec_config.get('standard_id_col', '')
                        if _saved_std_id and _saved_std_id in standard_columns:
                            st.session_state['standard_id_vec'] = _saved_std_id
                    if _current_std_addr not in standard_columns:
                        _saved_std_addr = st.session_state.vec_config.get('standard_address_col', '')
                        if _saved_std_addr and _saved_std_addr in standard_columns:
                            st.session_state['standard_addr_vec'] = _saved_std_addr
                    if _current_std_room not in standard_columns:
                        _saved_std_room = st.session_state.vec_config.get('standard_room_col', '')
                        if _saved_std_room and _saved_std_room in standard_columns:
                            st.session_state['standard_room_vec'] = _saved_std_room

                    st.session_state.vec_config['standard_id_col'] = st.selectbox(
                        "地址编码字段", standard_columns, key='standard_id_vec')
                    st.session_state.vec_config['standard_address_col'] = st.selectbox(
                        "标准地址字段", standard_columns, key='standard_addr_vec')
                    st.session_state.vec_config['standard_room_col'] = st.selectbox(
                        "房屋编码字段", standard_columns, key='standard_room_vec')
                else:
                    # 保留 widget key，避免 Streamlit 因 widget 未渲染而删除 session_state
                    # 优先从 session_state 取，为空则从 vec_config 恢复
                    _cur_std_id = st.session_state.get('standard_id_vec', '') or st.session_state.vec_config.get('standard_id_col', '')
                    _cur_std_addr = st.session_state.get('standard_addr_vec', '') or st.session_state.vec_config.get('standard_address_col', '')
                    _cur_std_room = st.session_state.get('standard_room_vec', '') or st.session_state.vec_config.get('standard_room_col', '')
                    st.selectbox("地址编码字段", [_cur_std_id] if _cur_std_id else ['请先选择标准地址表'],
                                disabled=True, key='standard_id_vec')
                    st.selectbox("标准地址字段", [_cur_std_addr] if _cur_std_addr else ['请先选择标准地址表'],
                                disabled=True, key='standard_addr_vec')
                    st.selectbox("房屋编码字段", [_cur_std_room] if _cur_std_room else ['请先选择标准地址表'],
                                disabled=True, key='standard_room_vec')

            # 自定义向量表名
            st.markdown('<div style="font-size: 12px; color: {Colors.TEXT_SECONDARY}; margin: 8px 0 4px 0;">向量表名</div>'.format(Colors=Colors), unsafe_allow_html=True)
            std_name_col1, std_name_col2 = st.columns([3, 1])
            with std_name_col1:
                # 使用包含表名的动态 key，确保切换表时 widget 状态重置
                _std_name_key = f'standard_vector_table_name_{standard_table}' if standard_table else 'standard_vector_table_name'
                std_custom_name = st.text_input(
                    "标准地址向量表名",
                    value=std_vec_table,
                    key=_std_name_key,
                    label_visibility="collapsed",
                    help="可自定义标准地址向量表名称，默认为系统自动生成"
                )
                if std_custom_name and std_custom_name != std_vec_table:
                    st.session_state.vec_config['standard_vector_table'] = std_custom_name.strip()
            with std_name_col2:
                if st.button("创建", key='create_std_btn',
                            help="创建标准地址向量表（如已存在则跳过）", disabled=not db_ready):
                    if db_ready:
                        with st.spinner("正在创建..."):
                            target_name = st.session_state.vec_config.get('standard_vector_table', Config.STANDARD_VECTOR_TABLE)
                            src_table = st.session_state.vec_config.get('standard_table', '')
                            if vector_store.check_table_exists(target_name):
                                st.info(f"标准地址向量表 {target_name} 已存在，无需重复创建")
                                if src_table:
                                    st.session_state.vec_config.setdefault('table_vec_mapping', {})[src_table] = target_name
                            elif vector_store.create_vector_table(target_name, table_type='standard'):
                                st.success(f"标准地址向量表 {target_name} 创建成功")
                                if src_table:
                                    st.session_state.vec_config.setdefault('table_vec_mapping', {})[src_table] = target_name
                            else:
                                st.error("创建失败，请查看日志")

    with manage_col:
        # 向量表管理
        with st.container(border=True):
            st.markdown(
                f'<div style="font-weight: {Typography.WEIGHT_SEMIBOLD}; font-size: 14px; margin-bottom: 10px;">'
                f'🗄 向量表管理</div>',
                unsafe_allow_html=True
            )

            vector_tables = vector_store.get_vector_tables() if db_ready else []

            if vector_tables:
                st.caption(f"当前共 {len(vector_tables)} 个向量表")

                # ========== 向量表列表展示（支持搜索、分页、详情）==========
                st.markdown('<div style="font-size: 13px; color: {Colors.TEXT_SECONDARY}; margin: 8px 0 4px 0;">📋 向量表列表</div>'.format(Colors=Colors), unsafe_allow_html=True)

                # 搜索框
                search_keyword = st.text_input("搜索向量表", placeholder="输入表名关键词过滤...", key='vector_table_search', label_visibility="collapsed")
                filtered_tables = [vt for vt in vector_tables if search_keyword.lower() in vt.lower()] if search_keyword else vector_tables

                # 分页状态初始化
                if 'vector_table_list_page' not in st.session_state:
                    st.session_state.vector_table_list_page = 1
                page_size = 6
                total_tables = len(filtered_tables)
                total_pages = max(1, (total_tables + page_size - 1) // page_size)
                current_page = min(st.session_state.vector_table_list_page, total_pages)
                start_idx = (current_page - 1) * page_size
                end_idx = min(start_idx + page_size, total_tables)
                page_tables = filtered_tables[start_idx:end_idx]

                # 向量表列表区域 - 固定高度，防止列表过长导致右栏与左栏不对齐
                with st.container(height=420):
                    # 展示当前页向量表
                    for i, vt in enumerate(page_tables):
                        cnt = vector_store.get_vector_count(vt)
                        dim = vector_store.check_vector_table_dimension(vt)
                        dim_str = f"{dim}维" if dim else "维度未知"

                        # 详情展开器
                        with st.expander(f"**{vt}**  |  {cnt:,}条  |  {dim_str}", expanded=False):
                            detail = vector_store.get_vector_table_detail(vt)
                            if detail:
                                # 基本信息
                                info_cols = st.columns(3)
                                with info_cols[0]:
                                    st.markdown(f"**数据量**: {detail['row_count']:,} 条")
                                with info_cols[1]:
                                    st.markdown(f"**向量维度**: {detail['vector_dim']} 维" if detail['vector_dim'] else "**向量维度**: 未知")
                                with info_cols[2]:
                                    st.markdown(f"**表大小**: {detail['table_size']}")
                                if detail['created_at']:
                                    st.markdown(f"**最早数据时间**: {detail['created_at']}")

                                # 字段信息
                                if detail['columns']:
                                    st.markdown("**字段结构**:")
                                    col_df_data = []
                                    for col_name, col_type in detail['columns']:
                                        col_df_data.append({"字段名": col_name, "数据类型": col_type})
                                    st.dataframe(col_df_data, use_container_width=True, hide_index=True)

                                # 索引信息
                                if detail['indexes']:
                                    st.markdown("**索引**:")
                                    idx_df_data = []
                                    for idx_name, idx_type in detail['indexes']:
                                        idx_df_data.append({"索引名": idx_name, "类型": idx_type})
                                    st.dataframe(idx_df_data, use_container_width=True, hide_index=True)
                                else:
                                    st.markdown("**索引**: 暂无")
                            else:
                                st.warning("获取表详情失败")

                # 分页控制（放在固定高度容器外面）
                if total_pages > 1:
                    page_col1, page_col2, page_col3, page_col4 = st.columns([1, 1, 2, 1])
                    with page_col1:
                        if st.button("⏮️ 首页", key='vt_first_page', disabled=current_page <= 1):
                            st.session_state.vector_table_list_page = 1
                            st.rerun()
                    with page_col2:
                        if st.button("◀️ 上一页", key='vt_prev_page', disabled=current_page <= 1):
                            st.session_state.vector_table_list_page = max(1, current_page - 1)
                            st.rerun()
                    with page_col3:
                        st.markdown(f'<div style="text-align: center; padding-top: 8px; font-size: 13px;">第 {current_page} / {total_pages} 页 (共 {total_tables} 个)</div>', unsafe_allow_html=True)
                    with page_col4:
                        if st.button("下一页 ▶️", key='vt_next_page', disabled=current_page >= total_pages):
                            st.session_state.vector_table_list_page = min(total_pages, current_page + 1)
                            st.rerun()

                st.divider()

                # 重命名向量表
                st.markdown('<div style="font-size: 13px; color: {Colors.TEXT_SECONDARY}; margin: 8px 0 4px 0;">✏️ 重命名向量表</div>'.format(Colors=Colors), unsafe_allow_html=True)
                rename_col1, rename_col2, rename_col3 = st.columns([2, 2, 1])
                with rename_col1:
                    rename_old = st.selectbox("选择要重命名的向量表", vector_tables, key='rename_table_select')
                with rename_col2:
                    rename_new = st.text_input("新表名", value=rename_old if rename_old else '', key='rename_new_name', label_visibility="collapsed")
                with rename_col3:
                    if st.button("重命名", key='rename_btn', help="重命名选中的向量表"):
                        if rename_new and rename_new != rename_old:
                            if vector_store.check_table_exists(rename_new):
                                st.error(f"表名 {rename_new} 已存在")
                            else:
                                if vector_store.rename_vector_table(rename_old, rename_new):
                                    st.success(f"已重命名为 {rename_new}")
                                    if st.session_state.vec_config.get('enterprise_vector_table') == rename_old:
                                        st.session_state.vec_config['enterprise_vector_table'] = rename_new
                                    if st.session_state.vec_config.get('standard_vector_table') == rename_old:
                                        st.session_state.vec_config['standard_vector_table'] = rename_new
                                    st.rerun()
                                else:
                                    st.error("重命名失败")
                        else:
                            st.warning("请输入不同的新表名")

                st.divider()

                # 清空向量表
                st.markdown('<div style="font-size: 13px; color: {Colors.TEXT_SECONDARY}; margin: 8px 0 4px 0;">🧹 清空向量表</div>'.format(Colors=Colors), unsafe_allow_html=True)
                trunc_col1, trunc_col2 = st.columns([3, 2])
                with trunc_col1:
                    trunc_table = st.selectbox("选择要清空的向量表", vector_tables, key='trunc_table_select')
                with trunc_col2:
                    if st.button("清空", key='trunc_btn', help="清空选中向量表的所有数据"):
                        if st.session_state.get('confirm_trunc') and st.session_state.get('confirm_trunc_table') == trunc_table:
                            if vector_store.truncate_vector_table(trunc_table):
                                st.success(f"{trunc_table} 已清空")
                                st.session_state.confirm_trunc = False
                                st.session_state.confirm_trunc_table = ''
                                st.rerun()
                        else:
                            st.warning(f"确定清空 {trunc_table}？再次点击确认")
                            st.session_state.confirm_trunc = True
                            st.session_state.confirm_trunc_table = trunc_table

                st.divider()

                # 删除向量表
                st.markdown('<div style="font-size: 13px; color: {Colors.TEXT_SECONDARY}; margin: 8px 0 4px 0;">🗑️ 删除向量表</div>'.format(Colors=Colors), unsafe_allow_html=True)
                del_col1, del_col2 = st.columns([3, 2])
                with del_col1:
                    del_table = st.selectbox("选择要删除的向量表", vector_tables, key='del_table_select')
                with del_col2:
                    if st.button("删除", key='delete_table_btn', help="彻底删除选中向量表（不可恢复）"):
                        if st.session_state.get('confirm_delete') and st.session_state.get('confirm_delete_table') == del_table:
                            if vector_store.drop_vector_table(del_table):
                                st.success(f"{del_table} 删除成功")
                                st.session_state.confirm_delete = False
                                st.session_state.confirm_delete_table = ''
                                st.rerun()
                        else:
                            st.warning(f"确定删除 {del_table}？再次点击确认")
                            st.session_state.confirm_delete = True
                            st.session_state.confirm_delete_table = del_table
            else:
                st.info("暂无向量表")

    st.divider()

    # 初始化向量化状态
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

    # ========== 步骤2：向量化执行 ==========
    st.markdown('<div class="vec-module-title"><span class="vec-step-num">2</span> 向量化执行</div>', unsafe_allow_html=True)

    vec_device = _render_device_selector(key='vec_device_selector')
    batch_size = st.number_input("处理批次大小", value=1000, min_value=100, max_value=10000, key='vec_batch_size')
    vec_mode = st.selectbox(
        "向量化模式",
        options=['全表向量化', '增量向量化'],
        index=0,
        help="全表向量化：重新向量化整张表的所有记录\n增量向量化：仅向量化尚未处理的记录（跳过已存在于向量表中的数据）"
    )

    vec_status = st.session_state.vec_status

    if vec_status['is_running']:
        progress_bar = st.progress(min(vec_status['progress'], 1.0))
        st.text(f"📦 已处理 {vec_status['processed_count']:,}/{vec_status['total_count']:,} ({vec_status['progress']*100:.1f}%)")
        st.text(f"⚡ 处理速度: {vec_status['speed']:.2f} 条/秒")
        st.text(f"⏱ 已执行时间: {format_time(vec_status['elapsed'])}")
        if vec_status['remaining'] > 0:
            st.text(f"⏳ 预计剩余时间: {format_time(vec_status['remaining'])}")
        st.info(vec_status['status_message'])

        if st.button("⏹ 取消向量化", type="primary"):
            st.session_state.vec_status['cancel_requested'] = True
            st.rerun()
        time.sleep(5)
        st.rerun()

    elif vec_status['completed']:
        st.success(f"✅ {vec_status['status_message']}")
        st.text(f"开始时间: {vec_status['start_datetime']}")
        st.text(f"结束时间: {vec_status['end_datetime']}")
        st.text(f"总耗时: {format_time(vec_status['execution_time'])}")
        st.text(f"平均速度: {vec_status['processed_count'] / vec_status['execution_time']:.2f} 条/秒" if vec_status['execution_time'] > 0 else "")
        if st.button("清除状态", key='vec_clear_completed'):
            st.session_state.vec_status = _init_vec_status()
            st.rerun()

    elif vec_status['cancelled']:
        st.warning(f"⚠️ 向量化已取消 - {vec_status['status_message']}")
        if st.button("清除状态", key='vec_clear_cancelled'):
            st.session_state.vec_status = _init_vec_status()
            st.rerun()

    elif vec_status['error_message']:
        st.error(f"❌ 向量化失败: {vec_status['error_message']}")
        if st.button("清除状态", key='vec_clear_error'):
            st.session_state.vec_status = _init_vec_status()
            st.rerun()

    else:
        # 向量化执行按钮 - 采用紧凑精致的卡片式布局
        st.markdown(f"""
        <style>
        .vec-action-container {{
            display: flex;
            gap: 16px;
            margin-top: 8px;
        }}
        .vec-action-card {{
            flex: 1;
            background: {Colors.SURFACE};
            border: 1px solid {Colors.BORDER};
            border-radius: {Radius.MD};
            padding: 20px;
            text-align: center;
            transition: all 0.2s ease;
            cursor: pointer;
        }}
        .vec-action-card:hover {{
            border-color: {Colors.PRIMARY};
            box-shadow: {Shadow.ELEVATED};
            transform: translateY(-2px);
        }}
        .vec-action-icon {{
            font-size: 24px;
            margin-bottom: 8px;
        }}
        .vec-action-title {{
            font-size: 15px;
            font-weight: {Typography.WEIGHT_SEMIBOLD};
            color: {Colors.TEXT_PRIMARY};
            margin-bottom: 4px;
        }}
        .vec-action-desc {{
            font-size: 12px;
            color: {Colors.TEXT_MUTED};
            margin-bottom: 16px;
        }}
        </style>
        """, unsafe_allow_html=True)

        # 获取当前配置的向量表名及存在状态
        ent_vec_table = st.session_state.vec_config.get('enterprise_vector_table', Config.ENTERPRISE_VECTOR_TABLE)
        std_vec_table = st.session_state.vec_config.get('standard_vector_table', Config.STANDARD_VECTOR_TABLE)
        ent_vec_exists = vector_store.check_table_exists(ent_vec_table) if db_ready else False
        std_vec_exists = vector_store.check_table_exists(std_vec_table) if db_ready else False

        # 获取当前配置的数据源信息
        _ent_src = st.session_state.vec_config
        _ent_table_ok = _ent_src['enterprise_table'] and _ent_src['enterprise_id_col'] and _ent_src['enterprise_name_col'] and _ent_src['enterprise_address_col']
        _std_table_ok = _ent_src['standard_table'] and _ent_src['standard_id_col'] and _ent_src['standard_address_col']

        vec_col1, vec_col2 = st.columns(2)
        with vec_col1:
            with st.container(border=True):
                st.markdown(
                    f'<div style="text-align: center; padding: 8px 0 4px 0;">'
                    f'<div style="font-size: 28px; margin-bottom: 8px;">🏢</div>'
                    f'<div style="font-size: 15px; font-weight: {Typography.WEIGHT_SEMIBOLD}; color: {Colors.TEXT_PRIMARY};">企业表向量化</div>'
                    f'</div>',
                    unsafe_allow_html=True
                )
                # 数据源信息
                if _ent_table_ok:
                    st.caption(f"源表: **{_ent_src['enterprise_table']}** | 标识: `{_ent_src['enterprise_id_col']}` | 名称: `{_ent_src['enterprise_name_col']}` | 地址: `{_ent_src['enterprise_address_col']}`")
                else:
                    st.caption("⚠️ 请先在步骤1中配置企业表及其字段映射")

                # 目标向量表状态
                ent_vec_count = vector_store.get_vector_count(ent_vec_table) if ent_vec_exists else 0
                if ent_vec_exists and ent_vec_count > 0:
                    st.markdown(f'<div style="text-align: center; font-size: 12px; color: {Colors.SUCCESS}; margin-bottom: 8px;">✅ 目标表 <code>{ent_vec_table}</code> 已有 {ent_vec_count:,} 条向量数据</div>', unsafe_allow_html=True)
                elif ent_vec_exists:
                    st.markdown(f'<div style="text-align: center; font-size: 12px; color: {Colors.WARNING}; margin-bottom: 8px;">⚠️ 目标表 <code>{ent_vec_table}</code> 已创建，尚无数据</div>', unsafe_allow_html=True)
                else:
                    st.markdown(f'<div style="text-align: center; font-size: 12px; color: {Colors.WARNING}; margin-bottom: 8px;">⚠️ 目标表 <code>{ent_vec_table}</code> 未创建</div>', unsafe_allow_html=True)

                _ent_btn_disabled = not db_ready or not _ent_table_ok
                _ent_btn_help = "请先在步骤1中配置企业表及字段" if not _ent_table_ok else "开始向量化"
                if st.button("开始企业表向量化", use_container_width=True, key='vec_enterprise_btn',
                            type="primary", disabled=_ent_btn_disabled, help=_ent_btn_help):
                    _start_vectorization('enterprise', batch_size, vec_device, vec_mode)
                    st.rerun()

        with vec_col2:
            with st.container(border=True):
                st.markdown(
                    f'<div style="text-align: center; padding: 8px 0 4px 0;">'
                    f'<div style="font-size: 28px; margin-bottom: 8px;">📍</div>'
                    f'<div style="font-size: 15px; font-weight: {Typography.WEIGHT_SEMIBOLD}; color: {Colors.TEXT_PRIMARY};">标准地址表向量化</div>'
                    f'</div>',
                    unsafe_allow_html=True
                )
                # 数据源信息
                if _std_table_ok:
                    st.caption(f"源表: **{_ent_src['standard_table']}** | 编码: `{_ent_src['standard_id_col']}` | 地址: `{_ent_src['standard_address_col']}` | 房号: `{_ent_src['standard_room_col']}`")
                else:
                    st.caption("⚠️ 请先在步骤1中配置标准地址表及其字段映射")

                # 目标向量表状态
                std_vec_count = vector_store.get_vector_count(std_vec_table) if std_vec_exists else 0
                if std_vec_exists and std_vec_count > 0:
                    st.markdown(f'<div style="text-align: center; font-size: 12px; color: {Colors.SUCCESS}; margin-bottom: 8px;">✅ 目标表 <code>{std_vec_table}</code> 已有 {std_vec_count:,} 条向量数据</div>', unsafe_allow_html=True)
                elif std_vec_exists:
                    st.markdown(f'<div style="text-align: center; font-size: 12px; color: {Colors.WARNING}; margin-bottom: 8px;">⚠️ 目标表 <code>{std_vec_table}</code> 已创建，尚无数据</div>', unsafe_allow_html=True)
                else:
                    st.markdown(f'<div style="text-align: center; font-size: 12px; color: {Colors.WARNING}; margin-bottom: 8px;">⚠️ 目标表 <code>{std_vec_table}</code> 未创建</div>', unsafe_allow_html=True)

                _std_btn_disabled = not db_ready or not _std_table_ok
                _std_btn_help = "请先在步骤1中配置标准地址表及字段" if not _std_table_ok else "开始向量化"
                if st.button("开始标准地址表向量化", use_container_width=True, key='vec_standard_btn',
                            type="primary", disabled=_std_btn_disabled, help=_std_btn_help):
                    _start_vectorization('standard', batch_size, vec_device, vec_mode)
                    st.rerun()

    st.divider()

    # ========== 步骤3：向量索引管理 ==========
    st.markdown('<div class="vec-module-title"><span class="vec-step-num">3</span> 向量索引管理</div>', unsafe_allow_html=True)

    # 动态获取所有有数据的向量表
    all_vector_tables = vector_store.get_vector_tables() if db_ready else []
    index_vec_tables = {}
    for vt in all_vector_tables:
        cnt = vector_store.get_vector_count(vt)
        if cnt > 0:
            # 自动生成索引名：表名 + _idx
            idx_name = f"idx_{vt}"
            index_vec_tables[vt] = (vt, idx_name)

    if not index_vec_tables:
        st.info("暂无已向量化的数据表，请先执行向量化")
    else:
        idx_col1, idx_col2 = st.columns([1, 1])
        with idx_col1:
            selected_label = st.selectbox("选择向量表", list(index_vec_tables.keys()), key='index_vec_table_selector')
        selected_table, selected_index = index_vec_tables[selected_label]
        row_count = vector_store.get_vector_count(selected_table)

        with idx_col2:
            st.markdown(f'<div style="padding-top: 32px; color: {Colors.TEXT_SECONDARY}; font-size: 14px;">数据量: {row_count:,} 条</div>', unsafe_allow_html=True)

        index_type = st.selectbox("索引类型", ['ivfflat', 'hnsw'], key='index_type_selector')

        # 自动计算默认参数
        if row_count <= 1_000_000:
            auto_lists = max(100, min(4000, row_count // 1000))
        else:
            auto_lists = max(100, min(4000, int(row_count ** 0.5)))

        maintenance_work_mem = st.text_input("maintenance_work_mem", value="1GB",
                                             help="索引创建时的维护内存，如 1GB、512MB")

        if index_type == 'ivfflat':
            lists = st.number_input("lists 参数", value=auto_lists, min_value=10, max_value=10000,
                                    help=f"自动计算值: {auto_lists}（基于 {row_count:,} 条数据）")
            m = None
            ef_construction = None
        else:
            lists = None
            m = st.number_input("m 参数", value=16, min_value=2, max_value=100,
                                help="连接数，默认16，值越大召回率越高但构建越慢")
            ef_construction = st.number_input("ef_construction 参数", value=200, min_value=40, max_value=2000,
                                              help="构建时搜索深度，默认200，值越大召回率越高但构建越慢")

        index_exists = vector_store.check_index_exists(selected_table, selected_index)

        idx_btn_col1, idx_btn_col2 = st.columns([1, 1])
        with idx_btn_col1:
            if index_exists:
                if st.button("删除现有索引", key='drop_index_btn'):
                    if vector_store.drop_vector_index(selected_index):
                        st.success(f"索引 {selected_index} 已删除")
                        st.rerun()
            else:
                st.markdown(f'<div style="color: {Colors.TEXT_MUTED}; font-size: 13px; padding-top: 8px;">索引 {selected_index} 不存在</div>', unsafe_allow_html=True)

        with idx_btn_col2:
            if st.button("创建索引", key='create_index_btn', type="primary"):
                if index_exists:
                    st.warning("索引已存在，请先删除再创建")
                else:
                    start_time = time.time()
                    start_datetime = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
                    st.info(f"⏱ 开始时间: {start_datetime}")
                    with st.spinner("正在创建索引..."):
                        success = vector_store.create_vector_index(
                            table_name=selected_table,
                            index_name=selected_index,
                            index_type=index_type,
                            lists=lists,
                            m=m,
                            ef_construction=ef_construction,
                            maintenance_work_mem=maintenance_work_mem
                        )
                    end_datetime = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
                    execution_time = time.time() - start_time

                    if success:
                        st.success(f"索引 {selected_index} 创建成功")
                        st.text(f"开始时间: {start_datetime}")
                        st.text(f"结束时间: {end_datetime}")
                        st.text(f"执行耗时: {format_time(execution_time)}")
                    else:
                        st.error("索引创建失败，请查看日志")

    if db_conn:
        db_conn.close()


def _init_vec_status():
    """初始化向量化状态"""
    return {
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


def _init_index_status():
    """初始化索引创建状态"""
    return {
        'is_running': False,
        'completed': False,
        'error_message': '',
        'start_datetime': '',
        'end_datetime': '',
        'execution_time': 0.0,
        'start_time': 0.0
    }


def _start_vectorization(table_type, batch_size, device, mode='全表向量化'):
    """启动向量化后台线程"""
    vec_status = _init_vec_status()
    vec_status['is_running'] = True
    vec_status['table_type'] = table_type
    st.session_state.vec_status = vec_status

    if table_type == 'enterprise':
        _src = st.session_state.vec_config.get('enterprise_table', '')
        _vec = st.session_state.vec_config.get('enterprise_vector_table', '')
    else:
        _src = st.session_state.vec_config.get('standard_table', '')
        _vec = st.session_state.vec_config.get('standard_vector_table', '')
    if _src and _vec:
        st.session_state.vec_config.setdefault('table_vec_mapping', {})[_src] = _vec

    # 将 vec_status 引用直接传给后台线程（线程中无法访问 st.session_state）
    thread = threading.Thread(
        target=run_vectorization_background,
        args=(vec_status, st.session_state.db_config.copy(), st.session_state.vec_config.copy(),
              table_type, batch_size, device, mode),
        daemon=True
    )
    thread.start()


def run_vectorization_background(vec_status, db_config, vec_config, table_type, batch_size, device, mode='全表向量化'):
    """后台运行向量化（vec_status 由主线程传入，线程内直接操作）"""
    working_conn = None
    start_time = time.time()

    try:
        vec_status['start_datetime'] = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
        vec_status['status_message'] = '正在连接数据库...'
        logger.info(f"[向量化] 启动: table_type={table_type}, batch_size={batch_size}, device={device}")

        working_conn = DBConnection(
            host=db_config['host'],
            port=db_config['port'],
            schema=db_config['schema'],
            dbname=db_config['dbname'],
            user=db_config['user'],
            password=db_config['password']
        )

        if not working_conn.connect():
            vec_status['error_message'] = '无法连接数据库'
            vec_status['is_running'] = False
            logger.error("[向量化] 数据库连接失败")
            return

        logger.info("[向量化] 数据库连接成功")
        working_data_loader = DataLoader(working_conn)

        if table_type == 'enterprise':
            source_table = vec_config['enterprise_table']
            id_col = vec_config['enterprise_id_col']
            name_col = vec_config['enterprise_name_col']
            addr_col = vec_config['enterprise_address_col']
            vec_table = vec_config.get('enterprise_vector_table', Config.ENTERPRISE_VECTOR_TABLE)
        else:
            source_table = vec_config['standard_table']
            id_col = vec_config['standard_id_col']
            addr_col = vec_config['standard_address_col']
            room_col = vec_config['standard_room_col']
            vec_table = vec_config.get('standard_vector_table', Config.STANDARD_VECTOR_TABLE)

        logger.info(f"[向量化] 源表={source_table}, 目标向量表={vec_table}")

        is_incremental = (mode == '增量向量化')

        vec_status['status_message'] = '正在加载向量化模型...'
        from model.embedding import AddressEmbedder
        import torch
        actual_device = device
        if device == 'cuda' and not torch.cuda.is_available():
            logger.warning("[向量化] GPU不可用，切换到CPU")
            actual_device = 'cpu'
        embedder = AddressEmbedder(device=actual_device)
        vector_dim = embedder.get_vector_dim()
        logger.info(f"[向量化] 模型加载完成, dim={vector_dim}, device={actual_device}")

        working_vector_store = VectorStore(working_conn)
        existing_dim = working_vector_store.check_vector_table_dimension(vec_table)
        if existing_dim is not None and existing_dim != vector_dim:
            logger.warning(f"[向量化] 维度不匹配: 现有={existing_dim}, 模型={vector_dim}, 重建表")
            working_vector_store.drop_vector_table(vec_table)

        working_vector_store.create_vector_table_with_dim(vec_table, vector_dim, table_type=table_type)
        logger.info(f"[向量化] 向量表 {vec_table} 就绪")

        # 增量模式：统计已向量化数量和待处理数量
        if is_incremental:
            already_vectorized = working_vector_store.get_vector_count(vec_table)
            total_count = working_data_loader.get_unvectorized_count(
                source_table, id_col, addr_col, vec_table
            )
            logger.info(f"[向量化] 增量模式, 已向量化: {already_vectorized}, 待处理: {total_count}")
        else:
            already_vectorized = 0
            total_count = working_data_loader.get_valid_address_count(source_table, addr_col)

        vec_status['total_count'] = total_count
        vec_status['status_message'] = f'共 {total_count:,} 条地址待处理'
        if is_incremental and already_vectorized > 0:
            vec_status['status_message'] += f'（跳过 {already_vectorized:,} 条已向量化）'
        logger.info(f"[向量化] 有效地址数: {total_count}")

        if total_count == 0:
            if is_incremental and already_vectorized > 0:
                vec_status['completed'] = True
                vec_status['is_running'] = False
                vec_status['end_datetime'] = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
                vec_status['execution_time'] = time.time() - start_time
                vec_status['status_message'] = f'增量向量化完成，所有 {already_vectorized:,} 条记录均已向量化'
                logger.info("[向量化] 增量模式：所有记录已向量化，无需处理")
                return
            vec_status['error_message'] = '没有有效的地址数据'
            vec_status['is_running'] = False
            logger.warning("[向量化] 无有效地址数据")
            return

        # ---- 批量导入优化：禁用 autovacuum 防止与 INSERT 争抢 I/O ----
        vec_status['status_message'] = '正在优化批量导入环境...'
        working_vector_store.disable_autovacuum(vec_table)

        # 删除已存在的向量索引（导入完成后重建），避免插入时维护索引开销
        # 索引名与 UI 创建索引时保持一致
        if table_type == 'enterprise':
            idx_name = 'idx_enterprise_vector'
        else:
            idx_name = 'idx_standard_vector'
        if working_vector_store.check_index_exists(vec_table, idx_name):
            logger.info(f"[向量化] 删除已有向量索引 {idx_name}，导入完成后重建")
            working_vector_store.drop_vector_index(idx_name)
        logger.info(f"[向量化] 批量导入环境就绪 (autovacuum=off, 无向量索引)")

        processed_count = 0
        batch_num = 0

        # 增量模式使用增量加载器
        if is_incremental:
            if table_type == 'enterprise':
                loader = working_data_loader.load_unvectorized_enterprise_data(
                    source_table, id_col, name_col, addr_col, vec_table, batch_size
                )
            else:
                loader = working_data_loader.load_unvectorized_standard_addresses(
                    source_table, id_col, addr_col, room_col, vec_table, batch_size
                )
        else:
            if table_type == 'enterprise':
                loader = working_data_loader.load_enterprise_data(
                    source_table, id_col, name_col, addr_col, batch_size
                )
            else:
                loader = working_data_loader.load_standard_addresses(
                    source_table, id_col, addr_col, room_col, batch_size
                )

        from concurrent.futures import ThreadPoolExecutor, Future
        _prefetch_executor = ThreadPoolExecutor(max_workers=1)
        _prefetch_future = None

        def _submit_prefetch(loader_iter):
            return _prefetch_executor.submit(lambda: next(loader_iter, None))

        loader_iter = iter(loader)
        _prefetch_future = _submit_prefetch(loader_iter)

        while True:
            try:
                if _prefetch_future is not None:
                    df = _prefetch_future.result()
                    _prefetch_future = None
                else:
                    df = next(loader_iter, None)
            except StopIteration:
                df = None

            if df is None:
                break

            _prefetch_future = _submit_prefetch(loader_iter)

            batch_num += 1
            if vec_status.get('cancel_requested'):
                logger.info(f"[向量化] 收到取消请求, 批次={batch_num}, 已处理={processed_count}")
                vec_status['status_message'] = '正在清空已写入数据...'
                working_vector_store.truncate_vector_table(vec_table)
                vec_status['cancelled'] = True
                vec_status['is_running'] = False
                vec_status['end_datetime'] = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
                vec_status['execution_time'] = time.time() - start_time
                vec_status['status_message'] = f'已取消，已清空 {vec_table} 表数据'
                logger.info(f"[向量化] 已取消, 清空了 {vec_table}")
                _prefetch_executor.shutdown(wait=False)
                return

            addresses = df['address'].tolist()
            source_ids = df['id'].tolist()

            if table_type == 'enterprise':
                extra = df['name'].tolist()
            else:
                extra = df.get('room_no', [''] * len(addresses)).tolist()

            vectors = embedder.encode(addresses)
            inserted = working_vector_store.insert_vectors(vectors, source_ids, addresses, vec_table, extra, table_type=table_type)

            processed_count += len(addresses)
            elapsed = time.time() - start_time
            speed = processed_count / elapsed if elapsed > 0 else 0

            vec_status['processed_count'] = processed_count
            vec_status['progress'] = processed_count / total_count
            vec_status['speed'] = speed
            vec_status['elapsed'] = elapsed
            vec_status['remaining'] = (total_count - processed_count) / speed if speed > 0 else 0
            vec_status['status_message'] = f'批次 {batch_num}: {processed_count:,}/{total_count:,}'

            if batch_num % 5 == 0:
                logger.info(f"[向量化] 批次={batch_num}, 进度={processed_count}/{total_count}")

        _prefetch_executor.shutdown(wait=True)

        # ---- 批量导入完成：回收空间并恢复 autovacuum ----
        vec_status['status_message'] = '正在 VACUUM ANALYZE...'
        working_vector_store.vacuum_table(vec_table, analyze=True)
        vec_status['status_message'] = '正在恢复 autovacuum...'
        working_vector_store.enable_autovacuum(vec_table)
        logger.info(f"[向量化] 表维护完成: VACUUM ANALYZE + autovacuum 已恢复")

        vec_status['completed'] = True
        vec_status['is_running'] = False
        vec_status['end_datetime'] = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
        vec_status['execution_time'] = time.time() - start_time
        vec_status['status_message'] = f'向量化完成，共处理 {processed_count:,} 条地址'
        logger.info(f"[向量化] 完成: {processed_count}条, 耗时{vec_status['execution_time']:.2f}s")

    except Exception as e:
        logger.error(f"[向量化] 异常: {e}")
        import traceback
        logger.error(f"[向量化] Traceback: {traceback.format_exc()}")
        # 尝试更新状态
        try:
            if vec_status is not None:
                vec_status['is_running'] = False
                vec_status['error_message'] = str(e)
        except Exception:
            pass
        # 回退：直接修改 session_state
        try:
            st.session_state.vec_status['is_running'] = False
            st.session_state.vec_status['error_message'] = str(e)
        except Exception:
            pass
    finally:
        if working_conn:
            try:
                # 确保 autovacuum 一定恢复（包括取消/异常路径）
                working_vector_store = VectorStore(working_conn)
                working_vector_store.enable_autovacuum(vec_table)
                logger.info(f"[向量化] finally: autovacuum 已恢复 ({vec_table})")
            except Exception:
                pass
            try:
                working_conn.close()
            except Exception:
                pass


def _start_index_creation(db_config, table_name, index_name, index_type,
                          lists, m, ef_construction, maintenance_work_mem):
    """启动索引创建后台线程"""
    st.session_state.index_status = _init_index_status()
    st.session_state.index_status['is_running'] = True
    st.session_state.index_status['start_datetime'] = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
    st.session_state.index_status['start_time'] = time.time()

    thread = threading.Thread(
        target=run_index_creation_background,
        args=(db_config.copy(), table_name, index_name, index_type,
              lists, m, ef_construction, maintenance_work_mem),
        daemon=True
    )
    thread.start()


def run_index_creation_background(db_config, table_name, index_name, index_type,
                                  lists, m, ef_construction, maintenance_work_mem):
    """后台运行索引创建"""
    index_status = st.session_state.index_status
    working_conn = None
    logger.info(f"[索引创建] 开始: table={table_name}, index={index_name}, type={index_type}")

    try:
        logger.info(f"[索引创建] 连接数据库 host={db_config.get('host')} dbname={db_config.get('dbname')}")
        working_conn = DBConnection(
            host=db_config['host'],
            port=db_config['port'],
            schema=db_config['schema'],
            dbname=db_config['dbname'],
            user=db_config['user'],
            password=db_config['password']
        )

        if not working_conn.connect():
            index_status['error_message'] = '无法连接数据库'
            index_status['is_running'] = False
            logger.error("[索引创建] 数据库连接失败")
            return

        logger.info("[索引创建] 数据库连接成功")
        working_vector_store = VectorStore(working_conn)
        row_count = working_vector_store.get_vector_count(table_name)
        logger.info(f"[索引创建] 表 {table_name} 数据量: {row_count}")

        success = working_vector_store.create_vector_index(
            table_name=table_name,
            index_name=index_name,
            index_type=index_type,
            lists=lists,
            m=m,
            ef_construction=ef_construction,
            maintenance_work_mem=maintenance_work_mem
        )

        if success:
            index_status['completed'] = True
            index_status['end_datetime'] = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
            index_status['execution_time'] = time.time() - index_status['start_time']
            logger.info(f"Index {index_name} created successfully in {index_status['execution_time']:.2f}s")
        else:
            index_status['error_message'] = '索引创建失败，请查看日志'
            logger.error(f"[索引创建] create_vector_index 返回 False")
    except Exception as e:
        index_status['error_message'] = str(e)
        logger.error(f"[索引创建] 异常: {e}")
        import traceback
        logger.error(f"[索引创建] Traceback: {traceback.format_exc()}")
    finally:
        index_status['is_running'] = False
        logger.info(f"[索引创建] 线程结束, is_running={index_status['is_running']}, completed={index_status.get('completed')}, error={index_status.get('error_message')}")
        if working_conn:
            working_conn.close()


def show_address_matching():
    db_config = st.session_state.db_config
    
    device = _render_device_selector(key='match_device_selector')

    # ========== 标签管理 ==========
    st.markdown(f"<div style='{card_style(bg_color=Colors.INFO_BG, border_color=Colors.INFO_BORDER)}'>", unsafe_allow_html=True)
    st.subheader("🏷 标签管理")

    if not st.session_state.connected:
        st.warning("请先在【数据库配置】页面连接数据库")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    tag_db_conn = DBConnection(
        host=db_config['host'], port=db_config['port'],
        schema=db_config['schema'], dbname=db_config['dbname'],
        user=db_config['user'], password=db_config['password']
    )
    if not tag_db_conn.connect():
        st.error("无法连接数据库")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    tag_mgr = TagManager(tag_db_conn)
    all_tags = tag_mgr.get_all_tags()

    # 当前选中标签信息
    if st.session_state.current_tag:
        st.markdown(f"""<div style='{card_style(bg_color=Colors.SURFACE_SECONDARY)}'>
            <b>当前标签</b>: {st.session_state.current_tag} |
            <b>召回表</b>: {st.session_state.current_recall_table} |
            <b>匹配表</b>: {st.session_state.current_match_table}
        </div>""", unsafe_allow_html=True)

    # 标签选择 + 新建按钮（对齐排列）
    tag_col1, tag_col2 = st.columns([4, 1])
    with tag_col1:
        if all_tags:
            current_prefix = st.session_state.get('current_tag_prefix', '')
            default_idx = 0
            for i, t in enumerate(all_tags):
                if t['prefix'] == current_prefix:
                    default_idx = i
                    break
            tag_names = [t['tag_name'] for t in all_tags]
            selected_tag_name = st.selectbox(
                "选择已有标签",
                tag_names,
                index=min(default_idx, len(tag_names) - 1),
                key='tag_selector'
            )
            if selected_tag_name and selected_tag_name != st.session_state.get('current_tag', ''):
                for t in all_tags:
                    if t['tag_name'] == selected_tag_name:
                        st.session_state.current_tag = t['tag_name']
                        st.session_state.current_tag_prefix = t['prefix']
                        st.session_state.current_recall_table = t['recall_table']
                        st.session_state.current_match_table = t['match_table']
                        st.rerun()
                        break
        else:
            st.info("暂无标签，请新建")

    with tag_col2:
        st.markdown("<div style='margin-top: 24px;'></div>", unsafe_allow_html=True)
        if st.button("新建标签", use_container_width=True, key='new_tag_btn',
                     help="创建一个新的匹配标签"):
            st.session_state.show_new_tag_input = True

    # 新建标签区域（输入框与按钮对齐）
    if st.session_state.get('show_new_tag_input', False):
        st.markdown(f"<div style='{card_style(bg_color=Colors.SURFACE_SECONDARY)} margin-top: 10px;'>", unsafe_allow_html=True)
        st.caption("创建新标签")
        new_col1, new_col2, new_col3 = st.columns([3, 1, 1])
        with new_col1:
            new_tag_name = st.text_input("标签名称", key='new_tag_input',
                                         placeholder="例如：福田 / 龙华 / batch1",
                                         label_visibility="collapsed")
        with new_col2:
            if st.button("确认创建", use_container_width=True, key='confirm_new_tag', type="primary"):
                if new_tag_name and new_tag_name.strip():
                    result = tag_mgr.create_tag(new_tag_name.strip())
                    if result:
                        st.session_state.current_tag = result['tag_name']
                        st.session_state.current_tag_prefix = result['prefix']
                        st.session_state.current_recall_table = result['recall_table']
                        st.session_state.current_match_table = result['match_table']
                        st.session_state.show_new_tag_input = False
                        st.success(f"标签已创建: {result['tag_name']}")
                    else:
                        st.error("创建失败，可能已存在同名标签")
                    st.rerun()
                else:
                    st.warning("请输入标签名称")
        with new_col3:
            if st.button("取消", use_container_width=True, key='cancel_new_tag'):
                st.session_state.show_new_tag_input = False
                st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)

    # 删除标签
    if all_tags:
        with st.expander("🗑 删除标签（含关联数据表）"):
            st.caption("删除标签将同时删除对应的召回结果表和匹配结果表")
            del_options = [t['tag_name'] for t in all_tags]
            del_col1, del_col2 = st.columns([2, 1])
            with del_col1:
                del_tag_name = st.selectbox("选择标签", del_options, key='del_tag_selector',
                                           label_visibility="collapsed")
            with del_col2:
                if st.button("删除标签", use_container_width=True, key='delete_tag_btn', type="secondary"):
                    del_prefix = None
                    for t in all_tags:
                        if t['tag_name'] == del_tag_name:
                            del_prefix = t['prefix']
                            break
                    if del_prefix:
                        try:
                            tag_mgr.delete_tag(del_prefix)
                            if st.session_state.current_tag_prefix == del_prefix:
                                st.session_state.current_tag = ''
                                st.session_state.current_tag_prefix = ''
                                st.session_state.current_recall_table = Config.RECALL_RESULTS_TABLE
                                st.session_state.current_match_table = Config.MATCH_RESULTS_TABLE
                            st.success(f"标签 '{del_tag_name}' 已删除")
                            st.rerun()
                        except Exception as e:
                            st.error(f"删除失败: {e}")

    tag_db_conn.close()
    st.markdown("</div>", unsafe_allow_html=True)

    # 未设置标签时不允许匹配
    if not st.session_state.current_tag:
        st.warning("请先选择或创建一个标签，再进行地址匹配")
        return

    # 使用标签对应的表名
    _recall_table = st.session_state.current_recall_table
    _match_table = st.session_state.current_match_table

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
                    recall_table = _recall_table
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
        
        st.markdown(f"<div class='status-card status-card-warning'>", unsafe_allow_html=True)
        st.subheader("匹配执行状态")
        
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
        st.markdown(f"<div class='status-card status-card-success'>", unsafe_allow_html=True)
        st.subheader("数据粗召回匹配完成")
        
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
                    data_loader.truncate_recall_table(_recall_table)
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
        st.markdown(f"<div class='status-card status-card-info'>", unsafe_allow_html=True)
        st.subheader("MGeo精确匹配完成")
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
    
    # 地址匹配功能页签
    match_tab1, match_tab2 = st.tabs(["📊 数据粗召回 & MGeo精确匹配", "🔄 MGeo地址相似度匹配"])

    with match_tab1:
        # 上部分：数据粗召回匹配
        st.markdown(f"<div class='status-card status-card-success'>", unsafe_allow_html=True)
        st.subheader("数据粗召回匹配")
    
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
                            key='enterprise_vector_match'
                        )
                        st.session_state.matching_config['enterprise_vector_table'] = enterprise_vector_table
                
                    with col2:
                        standard_vector_table = st.selectbox(
                            "选择标准地址向量表", 
                            [''] + vector_tables, 
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
                            max_value=500,
                            help="设置每个企业召回的候选地址数上限（实际返回可能因相似度阈值过滤而减少）"
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
        st.markdown(f"<div class='status-card status-card-warning'>", unsafe_allow_html=True)
        st.subheader("MGeo精确匹配")
    
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
                    recall_cursor = check_conn.execute(f"SELECT COUNT(*) FROM {_recall_table}")
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


    
    with match_tab2:
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
    st.markdown(f"<div class='status-card status-card-info'>", unsafe_allow_html=True)
    st.subheader("MGeo地址相似度匹配")
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

        st.markdown(f"<div class='status-card status-card-warning'>", unsafe_allow_html=True)
        st.subheader("MGeo相似度匹配执行状态")

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
        st.markdown(f"<div class='status-card status-card-success'>", unsafe_allow_html=True)
        st.subheader("MGeo地址相似度匹配完成")

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
                
                st.subheader("结果下载")
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
    id_col = ''
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
                    id_col = st.selectbox(
                        "选择标识字段（可选）",
                        options=[''] + columns,
                        key='mgeo_sim_id_file',
                        help="用于获取表的住建或相关唯一标识，不选择则匹配结果中不包含该字段"
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

                id_col = st.selectbox(
                    "选择标识字段（可选）",
                    options=[''] + columns,
                    key='mgeo_sim_id_db',
                    help="用于获取表的住建或相关唯一标识，不选择则匹配结果中不包含该字段"
                )

                st.session_state.mgeo_sim_selected_table = selected_table
                st.session_state.mgeo_sim_selected_addr_a = address_a_col
                st.session_state.mgeo_sim_selected_addr_b = address_b_col
                st.session_state.mgeo_sim_selected_id_col = id_col

                count_sql = f"SELECT COUNT(*) as count FROM {quote_identifier(selected_table)}"
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
            start_mgeo_similarity_matching(db_config, device, input_type, address_a_col, address_b_col, id_col)
    else:
        st.info("请先选择数据源和地址字段")

    st.markdown("</div>", unsafe_allow_html=True)


def start_mgeo_similarity_matching(db_config, device, input_type, address_a_col, address_b_col, id_col=''):
    """
    启动MGeo地址相似度匹配

    Args:
        db_config: 数据库配置字典
        device: 运行设备
        input_type: 输入类型 ('file' 或 'database')
        address_a_col: 地址A字段名
        address_b_col: 地址B字段名
        id_col: 可选的标识字段名
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
            # 按需选取列，避免加载无关字段
            cols = [address_a_col, address_b_col]
            if id_col:
                cols.append(id_col)
            cols_sql = ', '.join(quote_identifier(c) for c in cols)
            sql = f"SELECT {cols_sql} FROM {quote_identifier(table_name)}"
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
            id_col=id_col if id_col else None,
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
    # 防止重复启动
    if st.session_state.matching_status.get('is_running'):
        st.warning("匹配任务已在运行中，请等待完成")
        return
    if st.session_state.get('ranking_thread') and st.session_state.ranking_thread.is_alive():
        st.warning("精排任务正在运行中，请等待完成")
        return

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
            completed_callback=on_recall_completed,
            recall_table=st.session_state.current_recall_table
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
    # 防止重复启动
    if st.session_state.matching_status.get('is_running'):
        st.warning("匹配任务已在运行中，请等待完成")
        return
    if st.session_state.get('ranking_thread') and st.session_state.ranking_thread.is_alive():
        st.warning("精排任务已在运行中，请等待完成")
        return

    try:
        start_time = time.time()
        threshold = st.session_state.matching_config['similarity_threshold']
        # 获取标签对应的表名
        recall_table = st.session_state.current_recall_table
        match_table = st.session_state.current_match_table
        
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
        def ranking_thread_func(inner_db_config, inner_device, inner_threshold, inner_ranking_status, inner_start_time,
                                inner_recall_table, inner_match_table):
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
                data_loader.create_result_table(inner_match_table)
                data_loader.truncate_result_table(inner_match_table)
                logger.info(f"[ranking_thread_func] 已清空 {inner_match_table}")

                # 从recall_results表加载召回结果
                logger.info(f"[MGeo精排] 加载召回结果 {inner_recall_table}...")
                recall_results = data_loader.load_recall_results(inner_recall_table)
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
                        inserted = data_loader.insert_match_results(final_results, inner_match_table)
                        final_results = []

                if final_results:
                    inserted = data_loader.insert_match_results(final_results, inner_match_table)
                
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
        ranking_thread = threading.Thread(target=ranking_thread_func, args=(db_config, device, threshold, ranking_status, start_time, recall_table, match_table), daemon=True)
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

    # 初始化分页状态（避免 Session State API 警告）
    for pg_key in ['recall_page', 'match_page', 'sim_page', 'tagging_page',
                   'tagging_17_page', 'tagging_17_2_page',
                   'mgeo_copy_page', 'tagging_copy_page', 'tagging_17_copy_page',
                   'tagging_17_2_copy_page']:
        if pg_key not in st.session_state:
            st.session_state[pg_key] = 1

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

    # ========== 标签选择 ==========
    tag_mgr = TagManager(db_conn)
    all_tags = tag_mgr.get_all_tags()

    col_tag, col_space = st.columns([1, 2])
    with col_tag:
        tag_display_names = ['默认（无标签）'] + [t['tag_name'] for t in all_tags]
        result_tag_idx = 0
        current_tag_prefix = st.session_state.get('current_tag_prefix', '')
        for i, t in enumerate(all_tags):
            if t['prefix'] == current_tag_prefix:
                result_tag_idx = i + 1
                break

        selected_result_tag = st.selectbox(
            "选择标签（筛选粗召回和精排数据）",
            tag_display_names,
            index=min(result_tag_idx, len(tag_display_names) - 1),
            key='result_tag_selector',
            help="选择不同标签查看对应的匹配结果"
        )

    # 确定当前使用的表名
    if selected_result_tag == '默认（无标签）':
        result_recall_table = Config.RECALL_RESULTS_TABLE
        result_match_table = Config.MATCH_RESULTS_TABLE
    else:
        for t in all_tags:
            if t['tag_name'] == selected_result_tag:
                result_recall_table = t['recall_table']
                result_match_table = t['match_table']
                break
        else:
            result_recall_table = Config.RECALL_RESULTS_TABLE
            result_match_table = Config.MATCH_RESULTS_TABLE

    # 确保标签对应的表存在
    data_loader.create_recall_table(result_recall_table)
    data_loader.create_result_table(result_match_table)
    
    active_tab_name = st.session_state.get('result_management_active_tab', None)
    if 'result_management_active_tab' in st.session_state:
        del st.session_state['result_management_active_tab']
    
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(["粗召回数据", "精排匹配结果", "MGeo地址相似度匹配结果", "地址结构化解析结果", "地址17级结构化解析结果", "地址17级双字段结构化解析结果"])
    
    if active_tab_name:
        tab_index_map = {"粗召回数据": 0, "精排匹配结果": 1, "MGeo地址相似度匹配结果": 2, "地址结构化解析结果": 3, "地址17级结构化解析结果": 4, "地址17级双字段结构化解析结果": 5}
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
            <div class='status-card status-card-warning'>
                <strong>⚠️ 人工纠正模式</strong>：请选择需要更改的数据，勾选后点击"标记为精确匹配"按钮
            </div>
            """, unsafe_allow_html=True)
            
            enterprise_ids = st.session_state.manual_correction_enterprise_ids
            
            try:
                recall_df = data_loader.get_recall_results_by_enterprise_ids(enterprise_ids, table_name=result_recall_table)
                
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
                        <div class='status-card status-card-info'>
                            <strong>🔔 确认操作</strong>：将 {count} 条数据标记为精确匹配，此操作将更新精排匹配结果中对应企业的匹配数据。
                        </div>
                        """.format(count=len(correction_data)), unsafe_allow_html=True)
                        
                        confirm_btn_col1, confirm_btn_col2 = st.columns(2)
                        with confirm_btn_col1:
                            if st.button("✔️ 确认提交", key='confirm_correction_submit', type="primary"):
                                success_count = data_loader.batch_update_match_results_with_correction(correction_data, table_name=result_match_table)
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
                total = data_loader.get_recall_results_count(table_name=result_recall_table, filters=recall_filters)
                
                if total > 0:
                    with st.container(border=True):
                        pc1, pc2, pc3, pc4, pc5, pc6, pc7 = st.columns([1.0, 0.35, 0.35, 0.85, 0.35, 0.35, 0.9], vertical_alignment="center")
                        with pc1:
                            l1, w1 = st.columns([0.35, 0.65], vertical_alignment="center")
                            with l1:
                                st.caption("每页")
                            with w1:
                                page_size = st.selectbox("每页", options=[10, 20, 50, 100, 200], index=1, key='recall_page_size', label_visibility="collapsed")
                        with pc2:
                            st.button("⏮", key='recall_first', on_click=_goto_page, args=('recall_page', 1), help="首页")
                        with pc3:
                            st.button("◀", key='recall_prev', on_click=_prev_page, args=('recall_page',), help="上一页")
                        with pc4:
                            l2, w2 = st.columns([0.38, 0.62], vertical_alignment="center")
                            with l2:
                                st.caption("页码")
                            with w2:
                                total_pages = max(1, (total + page_size - 1) // page_size)
                                if st.session_state.get('recall_page', 1) > total_pages:
                                    st.session_state['recall_page'] = total_pages
                                page = st.number_input("页码", min_value=1, max_value=total_pages, key='recall_page', label_visibility="collapsed")
                        with pc5:
                            st.button("▶", key='recall_next', on_click=_next_page, args=('recall_page', total_pages), help="下一页")
                        with pc6:
                            st.button("⏭", key='recall_last', on_click=_goto_page, args=('recall_page', total_pages), help="末页")
                        with pc7:
                            st.caption(f"共 {total_pages} 页 / {total:,} 条")
                    
                    offset = (page - 1) * page_size
                    results = data_loader.get_recall_results_paginated(
                        table_name=result_recall_table,
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
                                for batch_df in data_loader.export_recall_results_batch(batch_size=5000, table_name=result_recall_table):
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
                                    for batch_df in data_loader.export_recall_results_batch(batch_size=5000, table_name=result_recall_table):
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

        # 初始化持久化筛选状态
        if 'match_filters_persist' not in st.session_state:
            st.session_state.match_filters_persist = {
                'match_status': '全部', 'correction_source': '全部', 'keyword': '',
                'min_exact': 0.0, 'max_exact': 1.0, 'min_partial': 0.0,
                'max_partial': 1.0, 'min_not': 0.0, 'max_not': 1.0
            }
        fp = st.session_state.match_filters_persist

        # 筛选栏：紧凑排列（每排4个）
        filter_col1, filter_col2, filter_col3, filter_col4 = st.columns(4)
        with filter_col1:
            fp['match_status'] = st.selectbox("匹配状态", ['全部', '精确匹配', '部分匹配', '不匹配'],
                                               index=['全部', '精确匹配', '部分匹配', '不匹配'].index(fp['match_status'])
                                               if fp['match_status'] in ['全部', '精确匹配', '部分匹配', '不匹配'] else 0,
                                               key='match_status_filter')
        with filter_col2:
            fp['correction_source'] = st.selectbox("匹配类型", ['全部', '自动匹配', '人工选择', '人工匹配'],
                                                    index=['全部', '自动匹配', '人工选择', '人工匹配'].index(fp['correction_source'])
                                                    if fp['correction_source'] in ['全部', '自动匹配', '人工选择', '人工匹配'] else 0,
                                                    key='correction_source_filter')
        with filter_col3:
            fp['min_exact'] = st.number_input("最小精确匹配", value=fp['min_exact'], min_value=0.0, max_value=1.0, step=0.1, key='min_exact')
        with filter_col4:
            fp['max_exact'] = st.number_input("最大精确匹配", value=fp['max_exact'], min_value=0.0, max_value=1.0, step=0.1, key='max_exact')

        filter_col5, filter_col6, filter_col7, filter_col8 = st.columns(4)
        with filter_col5:
            fp['min_partial'] = st.number_input("最小部分匹配", value=fp['min_partial'], min_value=0.0, max_value=1.0, step=0.1, key='min_partial')
        with filter_col6:
            fp['max_partial'] = st.number_input("最大部分匹配", value=fp['max_partial'], min_value=0.0, max_value=1.0, step=0.1, key='max_partial')
        with filter_col7:
            fp['min_not'] = st.number_input("最小不匹配", value=fp['min_not'], min_value=0.0, max_value=1.0, step=0.1, key='min_not')
        with filter_col8:
            fp['max_not'] = st.number_input("最大不匹配", value=fp['max_not'], min_value=0.0, max_value=1.0, step=0.1, key='max_not')

        # 关键词放在筛选栏下方
        fp['keyword'] = st.text_input("关键词搜索", value=fp['keyword'], key='match_keyword',
                                       placeholder="按企业名/企业地址/标准地址搜索")

        # 从持久化状态构建 filters 字典
        filters = {}
        if fp['match_status'] != '全部':
            filters['match_status'] = fp['match_status']
        if fp['correction_source'] != '全部':
            source_map = {'自动匹配': '自动匹配', '人工选择': '人工纠正', '人工匹配': '人工匹配'}
            filters['correction_source'] = source_map[fp['correction_source']]
        if fp['min_exact'] > 0:
            filters['min_exact_match'] = fp['min_exact']
        if fp['max_exact'] < 1:
            filters['max_exact_match'] = fp['max_exact']
        if fp['min_partial'] > 0:
            filters['min_partial_match'] = fp['min_partial']
        if fp['max_partial'] < 1:
            filters['max_partial_match'] = fp['max_partial']
        if fp['min_not'] > 0:
            filters['min_not_match'] = fp['min_not']
        if fp['max_not'] < 1:
            filters['max_not_match'] = fp['max_not']
        if fp['keyword']:
            filters['keyword'] = fp['keyword']
        
        if st.session_state.get('direct_correction_mode', False):
            correction_df = st.session_state.get('direct_correction_data', pd.DataFrame())
            if not correction_df.empty:
                st.markdown("""
                <div class='status-card status-card-warning'>
                    <strong>⚠️ 人工纠正模式</strong>：您可以直接修改选中数据的地址信息，确认提交后将标记为精确匹配
                </div>
                """, unsafe_allow_html=True)
                
                editable_cols = ['address_id', 'standard_address', 'room_no']
                disabled_cols = [col for col in correction_df.columns if col not in editable_cols]
                
                edited_df = st.data_editor(
                    correction_df,
                    use_container_width=True,
                    disabled=disabled_cols,
                    key='direct_correction_editor'
                )
                
                btn_col1, btn_col2, btn_col3 = st.columns([2, 1, 1])
                with btn_col1:
                    st.info(f"已选中 {len(edited_df)} 条数据，可编辑地址编码、标准地址、房屋编码")
                
                with btn_col2:
                    if st.button("✔️ 确认纠正", key='confirm_direct_correction', type="primary"):
                        correction_data = []
                        for _, row in edited_df.iterrows():
                            correction_data.append({
                                'enterprise_id': row['enterprise_id'],
                                'address_id': row.get('address_id', ''),
                                'standard_address': row.get('standard_address', ''),
                                'room_no': row.get('room_no', '')
                            })
                        success_count = data_loader.batch_direct_correct_match_results(correction_data, table_name=result_match_table)
                        st.session_state.direct_correction_mode = False
                        st.session_state.direct_correction_data = pd.DataFrame()
                        st.session_state.direct_correction_success_count = success_count
                        st.rerun()
                
                with btn_col3:
                    if st.button("❌ 取消", key='cancel_direct_correction'):
                        st.session_state.direct_correction_mode = False
                        st.session_state.direct_correction_data = pd.DataFrame()
                        st.rerun()
            else:
                st.warning("未选择需要纠正的数据")
                st.session_state.direct_correction_mode = False
                st.rerun()
        else:
            if st.session_state.get('direct_correction_success_count', 0) > 0:
                count = st.session_state.direct_correction_success_count
                st.session_state.direct_correction_success_count = 0
                st.success(f"✅ 人工纠正完成！成功更新 {count} 条匹配结果")
        
        try:
            total = data_loader.get_match_results_count(table_name=result_match_table, filters=filters)
            
            if total > 0:
                with st.container(border=True):
                    pc1, pc2, pc3, pc4, pc5, pc6, pc7 = st.columns([1.0, 0.35, 0.35, 0.85, 0.35, 0.35, 0.9], vertical_alignment="center")
                    with pc1:
                        l1, w1 = st.columns([0.35, 0.65], vertical_alignment="center")
                        with l1:
                            st.caption("每页")
                        with w1:
                            page_size = st.selectbox("每页", options=[10, 20, 50, 100, 200], index=1, key='match_page_size', label_visibility="collapsed")
                    with pc2:
                        st.button("⏮", key='match_first', on_click=_goto_page, args=('match_page', 1), help="首页")
                    with pc3:
                        st.button("◀", key='match_prev', on_click=_prev_page, args=('match_page',), help="上一页")
                    with pc4:
                        l2, w2 = st.columns([0.38, 0.62], vertical_alignment="center")
                        with l2:
                            st.caption("页码")
                        with w2:
                            total_pages = max(1, (total + page_size - 1) // page_size)
                            if st.session_state.get('match_page', 1) > total_pages:
                                st.session_state['match_page'] = total_pages
                            page = st.number_input("页码", min_value=1, max_value=total_pages, key='match_page', label_visibility="collapsed")
                    with pc5:
                        st.button("▶", key='match_next', on_click=_next_page, args=('match_page', total_pages), help="下一页")
                    with pc6:
                        st.button("⏭", key='match_last', on_click=_goto_page, args=('match_page', total_pages), help="末页")
                    with pc7:
                        st.caption(f"共 {total_pages} 页 / {total:,} 条")
                
                offset = (page - 1) * page_size
                results = data_loader.get_match_results_paginated(
                    table_name=result_match_table,
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
                        selected_rows_data = results.iloc[[idx for idx in selected_indices if idx < len(results)]]
                        correction_col1, correction_col2, correction_col3 = st.columns([2, 1, 1])
                        with correction_col1:
                            st.warning(f"已选中 {len(selected_indices)} 条数据，涉及 {len(selected_enterprise_ids)} 个企业")
                        with correction_col2:
                            if st.button("📋 人工选择", key='manual_select_btn', type="primary"):
                                st.session_state.manual_correction_mode = True
                                st.session_state.manual_correction_enterprise_ids = selected_enterprise_ids
                                st.session_state.result_management_active_tab = "粗召回数据"
                                st.rerun()
                        with correction_col3:
                            if st.button("🔧 人工纠正", key='direct_correction_btn', type="primary"):
                                st.session_state.direct_correction_mode = True
                                st.session_state.direct_correction_data = selected_rows_data
                                st.rerun()
                
                st.divider()
                export_col1, export_col2 = st.columns(2)
                with export_col1:
                    if st.button("📥 导出 CSV", key='export_match_csv'):
                        try:
                            import io
                            buffer = io.StringIO()
                            first_batch = True
                            batch_count = 0
                            for batch_df in data_loader.export_match_results_batch(table_name=result_match_table, filters=filters, batch_size=5000):
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
                    if st.button("📥 导出 Excel", key='export_match_excel'):
                        try:
                            import io
                            buffer = io.BytesIO()
                            with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                                batch_idx = 0
                                for batch_df in data_loader.export_match_results_batch(table_name=result_match_table, filters=filters, batch_size=5000):
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
            st.subheader("📊 匹配统计")

            # 确保 stats 计算使用正确的表
            stats = data_loader.get_match_statistics(table_name=result_match_table)

            # 使用卡片样式包裹统计指标
            st.markdown(f"<div style='{status_container_style('info')}'>", unsafe_allow_html=True)
            stat_col1, stat_col2, stat_col3, stat_col4 = st.columns(4)
            stat_col1.metric("📋 总记录数", f"{stats['total_count']:,}")
            stat_col2.metric("✅ 精确匹配", f"{stats['exact_match_count']:,}",
                           f"{stats['exact_match_rate']:.1f}%")
            stat_col3.metric("⚠️ 部分匹配", f"{stats['partial_match_count']:,}",
                           f"{stats['partial_match_rate']:.1f}%")
            stat_col4.metric("❌ 不匹配", f"{stats['not_match_count']:,}",
                           f"{stats['not_match_rate']:.1f}%")
            st.markdown("</div>", unsafe_allow_html=True)

            st.markdown(f"<div style='{card_style(bg_color=Colors.SURFACE_SECONDARY)}'>", unsafe_allow_html=True)
            man_col1, man_col2, man_col3 = st.columns(3)
            man_col1.metric("🔧 人工选择", f"{stats['manual_select_count']:,}")
            man_col2.metric("✏️ 人工匹配", f"{stats['manual_match_count']:,}")
            man_col3.metric("🤖 自动匹配", f"{stats['auto_match_count']:,}")
            st.markdown("</div>", unsafe_allow_html=True)

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
                            '来源': ['自动匹配', '人工选择', '人工匹配'],
                            '数量': [stats['auto_match_count'], stats['manual_select_count'], stats['manual_match_count']]
                        }
                        fig_correction = px.pie(correction_data, values='数量', names='来源',
                                               title='匹配来源分布',
                                               color='来源',
                                               color_discrete_map={'自动匹配': '#3498db', '人工选择': '#9b59b6', '人工匹配': '#e67e22'})
                        st.plotly_chart(fig_correction, use_container_width=True)
                except ImportError:
                    st.info("安装plotly可显示统计图表: pip install plotly")
        except Exception as e:
            st.error(f"查询匹配结果出错: {e}")

    with tab3:
        st.subheader("MGeo地址相似度匹配结果")

        filter_col1, filter_col2, filter_col3, filter_col4 = st.columns(4)
        with filter_col1:
            sim_match_status = st.selectbox("匹配状态筛选", ['全部', '精确匹配', '部分匹配', '不匹配'], key='sim_match_status_filter')
        with filter_col2:
            sim_keyword = st.text_input("关键词搜索", key='sim_match_keyword')
        with filter_col3:
            sim_min_exact = st.number_input("最小精确匹配概率", min_value=0.0, max_value=1.0, value=0.0, step=0.1, key='sim_min_exact')
        with filter_col4:
            sim_max_exact = st.number_input("最大精确匹配概率", min_value=0.0, max_value=1.0, value=1.0, step=0.1, key='sim_max_exact')

        filter_col5, filter_col6, filter_col7, filter_col8 = st.columns(4)
        with filter_col5:
            sim_min_partial = st.number_input("最小部分匹配概率", min_value=0.0, max_value=1.0, value=0.0, step=0.1, key='sim_min_partial')
        with filter_col6:
            sim_max_partial = st.number_input("最大部分匹配概率", min_value=0.0, max_value=1.0, value=1.0, step=0.1, key='sim_max_partial')
        with filter_col7:
            sim_min_not = st.number_input("最小不匹配概率", min_value=0.0, max_value=1.0, value=0.0, step=0.1, key='sim_min_not')
        with filter_col8:
            sim_max_not = st.number_input("最大不匹配概率", min_value=0.0, max_value=1.0, value=1.0, step=0.1, key='sim_max_not')

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
                with st.container(border=True):
                    pc1, pc2, pc3, pc4, pc5, pc6, pc7 = st.columns([1.0, 0.35, 0.35, 0.85, 0.35, 0.35, 0.9], vertical_alignment="center")
                    with pc1:
                        l1, w1 = st.columns([0.35, 0.65], vertical_alignment="center")
                        with l1:
                            st.caption("每页")
                        with w1:
                            sim_page_size = st.selectbox("每页", options=[10, 20, 50, 100, 200], index=1, key='sim_page_size', label_visibility="collapsed")
                    with pc2:
                        st.button("⏮", key='sim_first', on_click=_goto_page, args=('sim_page', 1), help="首页")
                    with pc3:
                        st.button("◀", key='sim_prev', on_click=_prev_page, args=('sim_page',), help="上一页")
                    with pc4:
                        l2, w2 = st.columns([0.38, 0.62], vertical_alignment="center")
                        with l2:
                            st.caption("页码")
                        with w2:
                            sim_total_pages = max(1, (sim_total + sim_page_size - 1) // sim_page_size)
                            if st.session_state.get('sim_page', 1) > sim_total_pages:
                                st.session_state['sim_page'] = sim_total_pages
                            sim_page = st.number_input("页码", min_value=1, max_value=sim_total_pages, key='sim_page', label_visibility="collapsed")
                    with pc5:
                        st.button("▶", key='sim_next', on_click=_next_page, args=('sim_page', sim_total_pages), help="下一页")
                    with pc6:
                        st.button("⏭", key='sim_last', on_click=_goto_page, args=('sim_page', sim_total_pages), help="末页")
                    with pc7:
                        st.caption(f"共 {sim_total_pages} 页 / {sim_total:,} 条")

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
        st.subheader("MGeo副本表查看")
        try:
            all_tables = db_conn.get_tables() if hasattr(db_conn, 'get_tables') else []
            if not all_tables:
                all_tables = st.session_state.db_conn.get_tables() if st.session_state.get('connected') else []
            mgeo_tables = [t for t in all_tables if t.endswith('_mgeo')]
            if mgeo_tables:
                selected_mgeo_table = st.selectbox("选择MGeo副本表", mgeo_tables, key='mgeo_copy_table_select')
                if selected_mgeo_table:
                    try:
                        q_selected = quote_identifier(selected_mgeo_table)
                        count_sql = f"SELECT COUNT(*) as count FROM {q_selected}"
                        count_cursor = db_conn.execute(count_sql)
                        mgeo_table_total = count_cursor.fetchone()['count'] if count_cursor else 0

                        if mgeo_table_total > 0:
                            # 翻页控件
                            with st.container(border=True):
                                pc1, pc2, pc3, pc4, pc5, pc6, pc7 = st.columns(
                                    [1.0, 0.35, 0.35, 0.85, 0.35, 0.35, 0.9],
                                    vertical_alignment="center"
                                )
                                with pc1:
                                    l1, w1 = st.columns([0.35, 0.65], vertical_alignment="center")
                                    with l1:
                                        st.caption("每页")
                                    with w1:
                                        mgeo_page_size = st.selectbox(
                                            "每页", options=[10, 20, 50, 100], index=1,
                                            key='mgeo_copy_page_size', label_visibility="collapsed"
                                        )
                                mgeo_total_pages = max(1, (mgeo_table_total + mgeo_page_size - 1) // mgeo_page_size)
                                if 'mgeo_copy_page' not in st.session_state or st.session_state.get('mgeo_copy_page', 1) > mgeo_total_pages:
                                    st.session_state['mgeo_copy_page'] = 1
                                mgeo_page = st.session_state['mgeo_copy_page']
                                with pc2:
                                    st.button("⏮", key='mgeo_copy_first', on_click=_goto_page,
                                              args=('mgeo_copy_page', 1), help="首页")
                                with pc3:
                                    st.button("◀", key='mgeo_copy_prev', on_click=_prev_page,
                                              args=('mgeo_copy_page',), help="上一页")
                                with pc4:
                                    l2, w2 = st.columns([0.38, 0.62], vertical_alignment="center")
                                    with l2:
                                        st.caption("页码")
                                    with w2:
                                        st.number_input(
                                            "页码", min_value=1, max_value=mgeo_total_pages,
                                            key='mgeo_copy_page', label_visibility="collapsed"
                                        )
                                with pc5:
                                    st.button("▶", key='mgeo_copy_next', on_click=_next_page,
                                              args=('mgeo_copy_page', mgeo_total_pages), help="下一页")
                                with pc6:
                                    st.button("⏭", key='mgeo_copy_last', on_click=_goto_page,
                                              args=('mgeo_copy_page', mgeo_total_pages), help="末页")
                                with pc7:
                                    st.caption(f"共 {mgeo_total_pages} 页 / {mgeo_table_total:,} 条")

                            mgeo_page = st.session_state.get('mgeo_copy_page', 1)
                            mgeo_offset = (mgeo_page - 1) * mgeo_page_size
                            mgeo_sql = f"SELECT * FROM {q_selected} LIMIT {mgeo_page_size} OFFSET {mgeo_offset}"
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
                                            copy_sql = f"SELECT * FROM {q_selected} LIMIT {copy_batch} OFFSET {copy_offset}"
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
                                                copy_sql = f"SELECT * FROM {q_selected} LIMIT {copy_batch} OFFSET {copy_offset}"
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

    with tab4:
        st.subheader("地址结构化解析结果")

        tagging_filter_col1, tagging_filter_col2 = st.columns(2)
        with tagging_filter_col1:
            tagging_keyword = st.text_input("关键词搜索", key='tagging_keyword')
        with tagging_filter_col2:
            tagging_has_province = st.checkbox("仅显示有省份的记录", key='tagging_has_province')

        tagging_filters = {}
        if tagging_keyword:
            tagging_filters['keyword'] = tagging_keyword
        if tagging_has_province:
            tagging_filters['has_province'] = True

        try:
            tagging_total = data_loader.get_address_tagging_results_count(filters=tagging_filters)

            if tagging_total > 0:
                col1, col2, col3 = st.columns([2, 3, 2])

                with col1:
                    tagging_page_size = st.selectbox(
                        "每页显示",
                        options=[10, 20, 50, 100, 200],
                        index=1,
                        key='tagging_page_size'
                    )

                tagging_total_pages = (tagging_total + tagging_page_size - 1) // tagging_page_size
                st.session_state['tagging_total_pages'] = tagging_total_pages

                with col2:
                    tagging_page = st.number_input(
                        f"页码 (共{tagging_total_pages}页)",
                        min_value=1,
                        max_value=tagging_total_pages,
                        value=1,
                        key='tagging_page'
                    )

                with col3:
                    st.write("")
                    st.write(f"共 {tagging_total:,} 条记录")

                nav_col1, nav_col2, nav_col3, nav_col4, nav_col5 = st.columns(5)
                with nav_col1:
                    st.button("⏮️ 首页", key='tagging_first', on_click=_goto_page, args=('tagging_page', 1))
                with nav_col2:
                    st.button("◀️ 上一页", key='tagging_prev', on_click=_prev_page, args=('tagging_page',))
                with nav_col3:
                    st.markdown(f"<div style='text-align: center; padding: 8px;'>第 {tagging_page} / {tagging_total_pages} 页</div>", unsafe_allow_html=True)
                with nav_col4:
                    st.button("▶️ 下一页", key='tagging_next', on_click=_next_page, args=('tagging_page', 'tagging_total_pages'))
                with nav_col5:
                    st.button("⏭️ 末页", key='tagging_last', on_click=_goto_page, args=('tagging_page', tagging_total_pages))

                tagging_results = data_loader.get_address_tagging_results_paginated(
                    filters=tagging_filters,
                    page=tagging_page,
                    page_size=tagging_page_size
                )

                if not tagging_results.empty:
                    display_cols = ['original_address', 'province', 'city', 'district', 'street',
                                    'community', 'road', 'roadno', 'area', 'bldg', 'unit', 'floor', 'house']
                    avail_cols = [c for c in display_cols if c in tagging_results.columns]
                    st.dataframe(tagging_results[avail_cols], use_container_width=True)

                    tagging_offset = (tagging_page - 1) * tagging_page_size
                    tagging_start_idx = tagging_offset + 1
                    tagging_end_idx = min(tagging_offset + tagging_page_size, tagging_total)
                    st.info(f"显示第 {tagging_start_idx:,} - {tagging_end_idx:,} 条，共 {tagging_total:,} 条")

                st.divider()
                export_col1, export_col2 = st.columns(2)
                with export_col1:
                    if st.button("📥 导出解析结果 (CSV)", key='export_tagging_csv'):
                        try:
                            import io
                            buffer = io.StringIO()
                            first_batch = True
                            batch_count = 0
                            for batch_df in data_loader.export_address_tagging_results_batch(filters=tagging_filters, batch_size=5000):
                                batch_df.to_csv(buffer, index=False, header=first_batch, encoding='utf-8-sig')
                                first_batch = False
                                batch_count += 1
                            csv_data = buffer.getvalue()
                            st.download_button(
                                label="下载 CSV 文件",
                                data=csv_data,
                                file_name=f"地址结构化解析结果_{time.strftime('%Y%m%d_%H%M%S')}.csv",
                                mime="text/csv",
                                key='download_tagging_csv'
                            )
                            st.success(f"CSV文件已生成，共分 {batch_count} 批加载")
                        except Exception as e:
                            st.error(f"导出CSV失败: {str(e)}")
                with export_col2:
                    if st.button("📥 导出解析结果 (Excel)", key='export_tagging_excel'):
                        try:
                            import io
                            buffer = io.BytesIO()
                            with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                                batch_idx = 0
                                for batch_df in data_loader.export_address_tagging_results_batch(filters=tagging_filters, batch_size=5000):
                                    sheet_name = f'数据_{batch_idx + 1}' if batch_idx < 26 else f'S{batch_idx + 1}'
                                    batch_df.to_excel(writer, sheet_name=sheet_name, index=False)
                                    batch_idx += 1
                            excel_data = buffer.getvalue()
                            st.download_button(
                                label="下载 Excel 文件",
                                data=excel_data,
                                file_name=f"地址结构化解析结果_{time.strftime('%Y%m%d_%H%M%S')}.xlsx",
                                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                key='download_tagging_excel'
                            )
                            st.success(f"Excel文件已生成，共 {batch_idx} 个工作表")
                        except ImportError:
                            st.error("导出Excel需要安装openpyxl库，请运行: pip install openpyxl")
                        except Exception as e:
                            st.error(f"导出Excel失败: {str(e)}")

                st.divider()
                st.subheader("解析统计")
                tagging_stats = data_loader.get_address_tagging_statistics()

                from model.address_tagging_model import OUTPUT_FIELD_LABELS

                stat_col1, stat_col2, stat_col3, stat_col4 = st.columns(4)
                stat_col1.metric("总记录数", f"{tagging_stats['total_count']:,}")
                stat_col2.metric("有省份", f"{tagging_stats['province_count']:,}", f"{tagging_stats['province_rate']:.1f}%")
                stat_col3.metric("有城市", f"{tagging_stats['city_count']:,}", f"{tagging_stats['city_rate']:.1f}%")
                stat_col4.metric("有区划", f"{tagging_stats['district_count']:,}", f"{tagging_stats['district_rate']:.1f}%")

                stat_col5, stat_col6, stat_col7, stat_col8 = st.columns(4)
                stat_col5.metric("有街道", f"{tagging_stats['street_count']:,}", f"{tagging_stats['street_rate']:.1f}%")
                stat_col6.metric("有社区", f"{tagging_stats['community_count']:,}", f"{tagging_stats['community_rate']:.1f}%")
                stat_col7.metric("有道路", f"{tagging_stats['road_count']:,}", f"{tagging_stats['road_rate']:.1f}%")
                stat_col8.metric("有路号", f"{tagging_stats['roadno_count']:,}", f"{tagging_stats['roadno_rate']:.1f}%")

                stat_col9, stat_col10, stat_col11, stat_col12 = st.columns(4)
                stat_col9.metric("有片区", f"{tagging_stats['area_count']:,}", f"{tagging_stats['area_rate']:.1f}%")
                stat_col10.metric("有楼栋", f"{tagging_stats['bldg_count']:,}", f"{tagging_stats['bldg_rate']:.1f}%")
                stat_col11.metric("有单元", f"{tagging_stats['unit_count']:,}", f"{tagging_stats['unit_rate']:.1f}%")
                stat_col12.metric("有楼层", f"{tagging_stats['floor_count']:,}", f"{tagging_stats['floor_rate']:.1f}%")

                stat_col13, _, _, _ = st.columns(4)
                stat_col13.metric("有户室", f"{tagging_stats['house_count']:,}", f"{tagging_stats['house_rate']:.1f}%")

                try:
                    import plotly.express as px

                    fields = ['province', 'city', 'district', 'street', 'community',
                              'road', 'roadno', 'area', 'bldg', 'unit', 'floor', 'house']
                    chart_data = {
                        '要素': [OUTPUT_FIELD_LABELS.get(f, f) for f in fields],
                        '识别率(%)': [tagging_stats[f'{f}_rate'] for f in fields]
                    }
                    fig_tagging = px.bar(
                        chart_data, x='要素', y='识别率(%)',
                        title='地址结构化解析各要素识别率',
                        color='识别率(%)',
                        color_continuous_scale='Blues'
                    )
                    fig_tagging.update_layout(xaxis_tickangle=-45)
                    st.plotly_chart(fig_tagging, use_container_width=True)
                except ImportError:
                    st.info("安装plotly可显示统计图表: pip install plotly")

            else:
                st.info("暂无地址结构化解析结果，请先在【地址结构化解析】页面执行解析")
        except Exception as e:
            st.error(f"查询地址结构化解析结果出错: {e}")

    with tab5:
        st.subheader("地址17级结构化解析结果")

        from model.address_tagging_model import OUTPUT_FIELDS_17, OUTPUT_FIELD_LABELS_17

        tagging_17_filter_col1, _ = st.columns(2)
        with tagging_17_filter_col1:
            tagging_17_keyword = st.text_input("关键词搜索", key='tagging_17_keyword')

        tagging_17_filters = {}
        if tagging_17_keyword:
            tagging_17_filters['keyword'] = tagging_17_keyword

        try:
            tagging_17_total = data_loader.get_address_tagging_17_results_count(filters=tagging_17_filters)

            if tagging_17_total > 0:
                col1, col2, col3 = st.columns([2, 3, 2])
                with col1:
                    tagging_17_page_size = st.selectbox(
                        "每页显示", options=[10, 20, 50, 100, 200],
                        index=1, key='tagging_17_page_size'
                    )
                tagging_17_total_pages = (tagging_17_total + tagging_17_page_size - 1) // tagging_17_page_size
                st.session_state['tagging_17_total_pages'] = tagging_17_total_pages

                with col2:
                    tagging_17_page = st.number_input(
                        f"页码 (共{tagging_17_total_pages}页)",
                        min_value=1, max_value=tagging_17_total_pages,
                        value=1, key='tagging_17_page'
                    )
                with col3:
                    st.write("")
                    st.write(f"共 {tagging_17_total:,} 条记录")

                nav_col1, nav_col2, nav_col3, nav_col4, nav_col5 = st.columns(5)
                with nav_col1:
                    st.button("⏮️ 首页", key='tagging_17_first', on_click=_goto_page, args=('tagging_17_page', 1))
                with nav_col2:
                    st.button("◀️ 上一页", key='tagging_17_prev', on_click=_prev_page, args=('tagging_17_page',))
                with nav_col3:
                    st.markdown(f"<div style='text-align: center; padding: 8px;'>第 {tagging_17_page} / {tagging_17_total_pages} 页</div>", unsafe_allow_html=True)
                with nav_col4:
                    st.button("▶️ 下一页", key='tagging_17_next', on_click=_next_page, args=('tagging_17_page', 'tagging_17_total_pages'))
                with nav_col5:
                    st.button("⏭️ 末页", key='tagging_17_last', on_click=_goto_page, args=('tagging_17_page', tagging_17_total_pages))

                tagging_17_results = data_loader.get_address_tagging_17_results_paginated(
                    filters=tagging_17_filters, page=tagging_17_page, page_size=tagging_17_page_size
                )

                if not tagging_17_results.empty:
                    display_cols = ['_id_field', 'dom_json', 'original_address'] + OUTPUT_FIELDS_17
                    avail_cols = [c for c in display_cols if c in tagging_17_results.columns]
                    st.dataframe(tagging_17_results[avail_cols], use_container_width=True)

                    tagging_17_offset = (tagging_17_page - 1) * tagging_17_page_size
                    tagging_17_start = tagging_17_offset + 1
                    tagging_17_end = min(tagging_17_offset + tagging_17_page_size, tagging_17_total)
                    st.info(f"显示第 {tagging_17_start:,} - {tagging_17_end:,} 条，共 {tagging_17_total:,} 条")

                st.divider()
                export_17_col1, export_17_col2 = st.columns(2)
                with export_17_col1:
                    if st.button("📥 导出解析结果 (CSV)", key='export_tagging_17_csv'):
                        try:
                            import io
                            buffer = io.StringIO()
                            first_batch = True
                            batch_count = 0
                            for batch_df in data_loader.export_address_tagging_17_results_batch(filters=tagging_17_filters, batch_size=5000):
                                batch_df.to_csv(buffer, index=False, header=first_batch, encoding='utf-8-sig')
                                first_batch = False
                                batch_count += 1
                            st.download_button(
                                label="下载 CSV 文件",
                                data=buffer.getvalue(),
                                file_name=f"地址17级结构化解析结果_{time.strftime('%Y%m%d_%H%M%S')}.csv",
                                mime="text/csv",
                                key='download_tagging_17_csv'
                            )
                            st.success(f"CSV文件已生成，共分 {batch_count} 批加载")
                        except Exception as e:
                            st.error(f"导出CSV失败: {str(e)}")
                with export_17_col2:
                    if st.button("📥 导出解析结果 (Excel)", key='export_tagging_17_excel'):
                        try:
                            import io
                            buffer = io.BytesIO()
                            with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                                batch_idx = 0
                                for batch_df in data_loader.export_address_tagging_17_results_batch(filters=tagging_17_filters, batch_size=5000):
                                    sheet_name = f'数据_{batch_idx + 1}' if batch_idx < 26 else f'S{batch_idx + 1}'
                                    batch_df.to_excel(writer, sheet_name=sheet_name, index=False)
                                    batch_idx += 1
                            st.download_button(
                                label="下载 Excel 文件",
                                data=buffer.getvalue(),
                                file_name=f"地址17级结构化解析结果_{time.strftime('%Y%m%d_%H%M%S')}.xlsx",
                                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                key='download_tagging_17_excel'
                            )
                            st.success(f"Excel文件已生成，共 {batch_idx} 个工作表")
                        except ImportError:
                            st.error("导出Excel需要安装openpyxl库")
                        except Exception as e:
                            st.error(f"导出Excel失败: {str(e)}")

                st.divider()
                st.subheader("解析统计")
                tagging_17_stats = data_loader.get_address_tagging_17_statistics()

                fields_17 = OUTPUT_FIELDS_17
                # 第一行
                sc1, sc2, sc3, sc4 = st.columns(4)
                sc1.metric("总记录数", f"{tagging_17_stats['total_count']:,}")
                sc2.metric("有省(prov)", f"{tagging_17_stats['prov_count']:,}", f"{tagging_17_stats['prov_rate']:.1f}%")
                sc3.metric("有市(city)", f"{tagging_17_stats['city_count']:,}", f"{tagging_17_stats['city_rate']:.1f}%")
                sc4.metric("有区(district)", f"{tagging_17_stats['district_count']:,}", f"{tagging_17_stats['district_rate']:.1f}%")
                # 第二行
                sc5, sc6, sc7, sc8 = st.columns(4)
                sc5.metric("有乡镇(town)", f"{tagging_17_stats['town_count']:,}", f"{tagging_17_stats['town_rate']:.1f}%")
                sc6.metric("有道路(road)", f"{tagging_17_stats['road_count']:,}", f"{tagging_17_stats['road_rate']:.1f}%")
                sc7.metric("有路号(roadno)", f"{tagging_17_stats['roadno_count']:,}", f"{tagging_17_stats['roadno_rate']:.1f}%")
                sc8.metric("有路口(intersection)", f"{tagging_17_stats['intersection_count']:,}", f"{tagging_17_stats['intersection_rate']:.1f}%")
                # 第三行
                sc9, sc10, sc11, sc12 = st.columns(4)
                sc9.metric("有POI(poi)", f"{tagging_17_stats['poi_count']:,}", f"{tagging_17_stats['poi_rate']:.1f}%")
                sc10.metric("有子POI(subpoi)", f"{tagging_17_stats['subpoi_count']:,}", f"{tagging_17_stats['subpoi_rate']:.1f}%")
                sc11.metric("有门牌(houseno)", f"{tagging_17_stats['houseno_count']:,}", f"{tagging_17_stats['houseno_rate']:.1f}%")
                sc12.metric("有单元(cellno)", f"{tagging_17_stats['cellno_count']:,}", f"{tagging_17_stats['cellno_rate']:.1f}%")
                # 第四行
                sc13, sc14, sc15, sc16 = st.columns(4)
                sc13.metric("有楼层(floorno)", f"{tagging_17_stats['floorno_count']:,}", f"{tagging_17_stats['floorno_rate']:.1f}%")
                sc14.metric("有社区(community)", f"{tagging_17_stats['community_count']:,}", f"{tagging_17_stats['community_rate']:.1f}%")
                sc15.metric("有辅助(assist)", f"{tagging_17_stats['assist_count']:,}", f"{tagging_17_stats['assist_rate']:.1f}%")
                sc16.metric("有距离(distance)", f"{tagging_17_stats['distance_count']:,}", f"{tagging_17_stats['distance_rate']:.1f}%")
                # 第五行
                sc17, sc18, _, _ = st.columns(4)
                sc17.metric("有开发区(devzone)", f"{tagging_17_stats['devzone_count']:,}", f"{tagging_17_stats['devzone_rate']:.1f}%")
                sc18.metric("有村组(village_group)", f"{tagging_17_stats['village_group_count']:,}", f"{tagging_17_stats['village_group_rate']:.1f}%")

                try:
                    import plotly.express as px
                    chart_data = {
                        '要素': [OUTPUT_FIELD_LABELS_17.get(f, f) for f in fields_17],
                        '识别率(%)': [tagging_17_stats[f'{f}_rate'] for f in fields_17]
                    }
                    fig_tagging_17 = px.bar(
                        chart_data, x='要素', y='识别率(%)',
                        title='地址17级结构化解析各要素识别率',
                        color='识别率(%)', color_continuous_scale='Blues'
                    )
                    fig_tagging_17.update_layout(xaxis_tickangle=-45)
                    st.plotly_chart(fig_tagging_17, use_container_width=True)
                except ImportError:
                    st.info("安装plotly可显示统计图表: pip install plotly")

            else:
                st.info("暂无17级地址结构化解析结果，请先在【地址结构化解析】→【地址17级分词（MGeo）】页签执行解析")
        except Exception as e:
            st.error(f"查询17级地址结构化解析结果出错: {e}")

    with tab6:
        st.subheader("地址17级双字段结构化解析结果")

        from model.address_tagging_model import OUTPUT_FIELDS_17, OUTPUT_FIELDS_17_2, OUTPUT_FIELD_LABELS_17, OUTPUT_FIELD_LABELS_17_2

        tagging_17_2_filter_col1, _ = st.columns(2)
        with tagging_17_2_filter_col1:
            tagging_17_2_keyword = st.text_input("关键词搜索", key='tagging_17_2_keyword')

        tagging_17_2_filters = {}
        if tagging_17_2_keyword:
            tagging_17_2_filters['keyword'] = tagging_17_2_keyword

        try:
            tagging_17_2_total = data_loader.get_address_tagging_17_2_results_count(filters=tagging_17_2_filters)

            if tagging_17_2_total > 0:
                col1, col2, col3 = st.columns([2, 3, 2])
                with col1:
                    tagging_17_2_page_size = st.selectbox(
                        "每页显示", options=[10, 20, 50, 100, 200],
                        index=1, key='tagging_17_2_page_size'
                    )
                tagging_17_2_total_pages = (tagging_17_2_total + tagging_17_2_page_size - 1) // tagging_17_2_page_size
                st.session_state['tagging_17_2_total_pages'] = tagging_17_2_total_pages

                with col2:
                    tagging_17_2_page = st.number_input(
                        f"页码 (共{tagging_17_2_total_pages}页)",
                        min_value=1, max_value=tagging_17_2_total_pages,
                        value=1, key='tagging_17_2_page'
                    )
                with col3:
                    st.write("")
                    st.write(f"共 {tagging_17_2_total:,} 条记录")

                nav_col1, nav_col2, nav_col3, nav_col4, nav_col5 = st.columns(5)
                with nav_col1:
                    st.button("⏮️ 首页", key='tagging_17_2_first', on_click=_goto_page, args=('tagging_17_2_page', 1))
                with nav_col2:
                    st.button("◀️ 上一页", key='tagging_17_2_prev', on_click=_prev_page, args=('tagging_17_2_page',))
                with nav_col3:
                    st.markdown(f"<div style='text-align: center; padding: 8px;'>第 {tagging_17_2_page} / {tagging_17_2_total_pages} 页</div>", unsafe_allow_html=True)
                with nav_col4:
                    st.button("▶️ 下一页", key='tagging_17_2_next', on_click=_next_page, args=('tagging_17_2_page', 'tagging_17_2_total_pages'))
                with nav_col5:
                    st.button("⏭️ 末页", key='tagging_17_2_last', on_click=_goto_page, args=('tagging_17_2_page', tagging_17_2_total_pages))

                tagging_17_2_results = data_loader.get_address_tagging_17_2_results_paginated(
                    filters=tagging_17_2_filters, page=tagging_17_2_page, page_size=tagging_17_2_page_size
                )

                if not tagging_17_2_results.empty:
                    display_cols = ['_id_field', 'dom_json', 'original_address'] + OUTPUT_FIELDS_17_2
                    avail_cols = [c for c in display_cols if c in tagging_17_2_results.columns]
                    st.dataframe(tagging_17_2_results[avail_cols], use_container_width=True)

                    tagging_17_2_offset = (tagging_17_2_page - 1) * tagging_17_2_page_size
                    tagging_17_2_start = tagging_17_2_offset + 1
                    tagging_17_2_end = min(tagging_17_2_offset + tagging_17_2_page_size, tagging_17_2_total)
                    st.info(f"显示第 {tagging_17_2_start:,} - {tagging_17_2_end:,} 条，共 {tagging_17_2_total:,} 条")

                st.divider()
                export_17_2_col1, export_17_2_col2 = st.columns(2)
                with export_17_2_col1:
                    if st.button("📥 导出解析结果 (CSV)", key='export_tagging_17_2_csv'):
                        try:
                            import io
                            buffer = io.StringIO()
                            first_batch = True
                            batch_count = 0
                            for batch_df in data_loader.export_address_tagging_17_2_results_batch(filters=tagging_17_2_filters, batch_size=5000):
                                batch_df.to_csv(buffer, index=False, header=first_batch, encoding='utf-8-sig')
                                first_batch = False
                                batch_count += 1
                            st.download_button(
                                label="下载 CSV 文件",
                                data=buffer.getvalue(),
                                file_name=f"地址17级双字段解析结果_{time.strftime('%Y%m%d_%H%M%S')}.csv",
                                mime="text/csv", key='download_tagging_17_2_csv'
                            )
                            st.success(f"CSV文件已生成，共分 {batch_count} 批加载")
                        except Exception as e:
                            st.error(f"导出CSV失败: {str(e)}")
                with export_17_2_col2:
                    if st.button("📥 导出解析结果 (Excel)", key='export_tagging_17_2_excel'):
                        try:
                            import io
                            buffer = io.BytesIO()
                            with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                                batch_idx = 0
                                for batch_df in data_loader.export_address_tagging_17_2_results_batch(filters=tagging_17_2_filters, batch_size=5000):
                                    sheet_name = f'数据_{batch_idx + 1}' if batch_idx < 26 else f'S{batch_idx + 1}'
                                    batch_df.to_excel(writer, sheet_name=sheet_name, index=False)
                                    batch_idx += 1
                            st.download_button(
                                label="下载 Excel 文件",
                                data=buffer.getvalue(),
                                file_name=f"地址17级双字段解析结果_{time.strftime('%Y%m%d_%H%M%S')}.xlsx",
                                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                key='download_tagging_17_2_excel'
                            )
                            st.success(f"Excel文件已生成，共 {batch_idx} 个工作表")
                        except ImportError:
                            st.error("导出Excel需要安装openpyxl库")
                        except Exception as e:
                            st.error(f"导出Excel失败: {str(e)}")

                st.divider()
                st.subheader("解析统计")
                tagging_17_2_stats = data_loader.get_address_tagging_17_2_statistics()

                base_fields = OUTPUT_FIELDS_17
                # Row 1
                s1, s2, s3, s4 = st.columns(4)
                s1.metric("总记录数", f"{tagging_17_2_stats['total_count']:,}")
                s2.metric("有省(prov)", f"{tagging_17_2_stats['prov_count']:,}", f"{tagging_17_2_stats['prov_rate']:.1f}%")
                s3.metric("有市(city)", f"{tagging_17_2_stats['city_count']:,}", f"{tagging_17_2_stats['city_rate']:.1f}%")
                s4.metric("有区(district)", f"{tagging_17_2_stats['district_count']:,}", f"{tagging_17_2_stats['district_rate']:.1f}%")
                # Row 2
                s5, s6, s7, s8 = st.columns(4)
                s5.metric("有乡镇(town)", f"{tagging_17_2_stats['town_count']:,}", f"{tagging_17_2_stats['town_rate']:.1f}%")
                s6.metric("有道路(road)", f"{tagging_17_2_stats['road_count']:,}", f"{tagging_17_2_stats['road_rate']:.1f}%")
                s7.metric("有路号(roadno)", f"{tagging_17_2_stats['roadno_count']:,}", f"{tagging_17_2_stats['roadno_rate']:.1f}%")
                s8.metric("有路口(intersection)", f"{tagging_17_2_stats['intersection_count']:,}", f"{tagging_17_2_stats['intersection_rate']:.1f}%")
                # Row 3
                s9, s10, s11, s12 = st.columns(4)
                s9.metric("有POI(poi)", f"{tagging_17_2_stats['poi_count']:,}", f"{tagging_17_2_stats['poi_rate']:.1f}%")
                s10.metric("有子POI(subpoi)", f"{tagging_17_2_stats['subpoi_count']:,}", f"{tagging_17_2_stats['subpoi_rate']:.1f}%")
                s11.metric("有门牌(houseno)", f"{tagging_17_2_stats['houseno_count']:,}", f"{tagging_17_2_stats['houseno_rate']:.1f}%")
                s12.metric("有单元(cellno)", f"{tagging_17_2_stats['cellno_count']:,}", f"{tagging_17_2_stats['cellno_rate']:.1f}%")
                # Row 4
                s13, s14, s15, s16 = st.columns(4)
                s13.metric("有楼层(floorno)", f"{tagging_17_2_stats['floorno_count']:,}", f"{tagging_17_2_stats['floorno_rate']:.1f}%")
                s14.metric("有社区(community)", f"{tagging_17_2_stats['community_count']:,}", f"{tagging_17_2_stats['community_rate']:.1f}%")
                s15.metric("有辅助(assist)", f"{tagging_17_2_stats['assist_count']:,}", f"{tagging_17_2_stats['assist_rate']:.1f}%")
                s16.metric("有距离(distance)", f"{tagging_17_2_stats['distance_count']:,}", f"{tagging_17_2_stats['distance_rate']:.1f}%")
                # Row 5
                s17, s18, _, _ = st.columns(4)
                s17.metric("有开发区(devzone)", f"{tagging_17_2_stats['devzone_count']:,}", f"{tagging_17_2_stats['devzone_rate']:.1f}%")
                s18.metric("有村组(village_group)", f"{tagging_17_2_stats['village_group_count']:,}", f"{tagging_17_2_stats['village_group_rate']:.1f}%")

                try:
                    import plotly.express as px
                    chart_data = {
                        '要素': [OUTPUT_FIELD_LABELS_17.get(f, f) for f in base_fields],
                        '识别率(%)': [tagging_17_2_stats[f'{f}_rate'] for f in base_fields]
                    }
                    fig_17_2 = px.bar(
                        chart_data, x='要素', y='识别率(%)',
                        title='地址17级双字段解析各要素识别率（主字段）',
                        color='识别率(%)', color_continuous_scale='Blues'
                    )
                    fig_17_2.update_layout(xaxis_tickangle=-45)
                    st.plotly_chart(fig_17_2, use_container_width=True)
                except ImportError:
                    st.info("安装plotly可显示统计图表: pip install plotly")

            else:
                st.info("暂无17级双字段解析结果，请先在【地址结构化解析】→【地址17级分词（MGeo）2】页签执行解析")
        except Exception as e:
            st.error(f"查询17级双字段解析结果出错: {e}")

    db_conn.close()

def show_system_logs():
    st.subheader("系统日志")

    # 显示内存中的日志（实时）
    from utils.logger import get_log_messages, clear_logs, get_db_logs, clear_db_logs

    log_messages = get_log_messages()
    if log_messages:
        memory_logs = []
        for log in log_messages[-500:]:
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

    # 显示数据库日志
    st.subheader("数据库存储日志")
    if st.session_state.connected:
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
            col1, col2 = st.columns([1, 4])
            with col1:
                log_level_filter = st.selectbox("日志级别", ['全部', 'WARNING', 'ERROR'], key='db_log_level')
            with col2:
                st.write("")
                st.write("")
                if st.button("清空数据库日志"):
                    clear_db_logs(db_conn)
                    st.success("数据库日志已清空")
                    st.rerun()

            level = None if log_level_filter == '全部' else log_level_filter
            db_logs = get_db_logs(db_conn, limit=500, level=level)
            if db_logs:
                log_lines = []
                for log in db_logs:
                    t = log['created_at'].strftime('%Y-%m-%d %H:%M:%S') if hasattr(log['created_at'], 'strftime') else str(log['created_at'])
                    log_lines.append(f"{t} - {log['level']} - {log['message']}")
                st.text_area("数据库日志内容", '\n'.join(log_lines), height=300)
            else:
                st.info("暂无数据库日志")
            db_conn.close()
    else:
        st.info("请先连接数据库以查看数据库日志")

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
            SELECT c1.source_id, c1.address, 1 - ((c1.vector <-> c2.vector)^2 / 2.0) as similarity
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
        page_icon="🔍",
        layout="wide",
        initial_sidebar_state="expanded"
    )

    init_session_state()
    inject_global_styles()

    with st.sidebar:
        st.markdown(f"""
        <div class="sidebar-title">
            <h2 style="color: {Colors.PRIMARY}; margin: 0; font-family: {Typography.FONT_FAMILY};">地址匹配系统</h2>
            <p style="color: {Colors.TEXT_SECONDARY}; font-size: {Typography.SIZE_CAPTION}; margin: 5px 0 0 0;">Chinese Address Semantic Matching</p>
        </div>
        """, unsafe_allow_html=True)

        st.divider()

        menu_options = [
            ("首页", "首页"),
            ("数据库配置", "数据库配置"),
            ("地址结构化解析", "地址结构化解析"),
            ("向量预处理", "向量预处理"),
            ("地址匹配", "地址匹配"),
            ("结果管理", "结果管理"),
            ("系统日志", "系统日志"),
        ]

        def _navigate_to(mk):
            st.session_state.selected_menu = mk

        for display_name, menu_key in menu_options:
            is_active = st.session_state.selected_menu == menu_key
            btn_type = "primary" if is_active else "secondary"
            st.button(
                display_name,
                key=f"nav_{menu_key}",
                use_container_width=True,
                type=btn_type,
                on_click=_navigate_to,
                args=(menu_key,)
            )

        st.divider()

        if st.session_state.get('connected'):
            st.success("数据库已连接")
        else:
            st.warning("数据库未连接")

        st.divider()

        gpu_info = st.session_state.get('gpu_info', {})
        if gpu_info.get('cuda_available'):
            device_label = f"GPU: {gpu_info.get('device_name', 'Unknown')}"
            st.success(device_label)
        elif gpu_info.get('has_gpu'):
            st.warning("检测到独立显卡但无法使用GPU")
            if gpu_info.get('warning'):
                st.caption(gpu_info['warning'])
        else:
            st.info("CPU 模式运行")

        st.markdown(f"<p class='app-footer'>v1.0 | Powered by MGeo</p>", unsafe_allow_html=True)

    st.markdown(f"""
    <div class="app-title">
        中文地址语义匹配系统
    </div>
    <p style="color: {Colors.TEXT_SECONDARY}; font-size: {Typography.SIZE_BODY}; margin: 5px 0 0 0;">
        企业地址与标准地址的智能匹配平台 — 向量粗召回 + MGeo精排
    </p>
    """, unsafe_allow_html=True)

    st.divider()

    def show_home_page():
        """
        首页：功能导航入口

        布局：上方横向流程进度条 + 下方功能入口卡片网格
        """
        st.subheader("首页")
        st.caption("地址语义匹配系统 — 选择下方功能开始工作")

        st.markdown("### 📋 匹配工作流")
        _render_workflow_bar()

        st.divider()

        st.markdown("### 🧩 功能入口")
        _render_feature_cards()

    # ---- 内联 SVG 图标字典（24x24 viewBox, Lucide 风格） ----
    _ICON = {
        'db':     '<ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"/><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/>',
        'table':  '<rect x="3" y="3" width="18" height="18" rx="2"/><line x1="3" x2="21" y1="9" y2="9"/><line x1="9" x2="9" y1="3" y2="21"/>',
        'search': '<circle cx="11" cy="11" r="8"/><line x1="21" x2="16.65" y1="21" y2="16.65"/>',
        'result': '<path d="M9 5H7a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2h-2"/><rect x="9" y="3" width="6" height="4" rx="1"/><polyline points="9 14 11 16 15 12"/>',
        'edit':   '<path d="M17 3a2.83 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/><path d="m15 5 4 4"/>',
    }

    def _icon(name, size=24, color='#fff'):
        p = _ICON.get(name, '')
        return f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">{p}</svg>'

    def _render_workflow_bar():
        """匹配工作流形象展示 — 纯视觉引导，无交互按钮"""

        steps = [
            ("db",     "1", "数据库配置", "连接 PostgreSQL，配置数据源"),
            ("table",  "2", "向量预处理", "地址向量化，建立向量索引"),
            ("search", "3", "地址匹配",   "粗召回 + MGeo 精排匹配"),
            ("result", "4", "结果管理",   "浏览筛选，导出与人工纠正"),
            ("edit",   "5", "人工纠正",   "匹配偏差，手动修正结果"),
        ]
        N = len(steps)
        P = Colors.PRIMARY
        PL = Colors.PRIMARY_LIGHT
        T1 = Colors.TEXT_PRIMARY
        T2 = Colors.TEXT_SECONDARY
        B = Colors.BORDER

        # ==================== 上排：圆点 + 连接线 ====================
        step_pct = 100.0 / N
        dots_parts = []
        for i, (name, num, title, desc) in enumerate(steps):
            left = step_pct * i + step_pct / 2
            dots_parts.append(
                f'<div style="position:absolute;left:{left:.1f}%;'
                f'transform:translateX(-50%);top:0;">'
                f'<div style="'
                f'width:56px;height:56px;border-radius:50%;'
                f'background:{P};display:flex;align-items:center;'
                f'justify-content:center;'
                f'box-shadow:0 4px 14px rgba(37,99,235,.25);'
                f'z-index:2;position:relative;">'
                f'{_icon(name, 26, "#ffffff")}'
                f'</div></div>'
            )

        line_left = step_pct / 2
        line_width = 100 - step_pct

        row1 = (
            f'<div style="position:relative;height:66px;">'
            f'<div style="position:absolute;top:28px;'
            f'left:{line_left:.1f}%;width:{line_width:.1f}%;height:3px;'
            f'background:linear-gradient(90deg,{P},{PL});'
            f'border-radius:2px;z-index:1;"></div>'
            f'<div style="position:absolute;top:22px;'
            f'right:{step_pct / 2 - 1:.1f}%;'
            f'width:0;height:0;'
            f'border-top:7px solid transparent;'
            f'border-bottom:7px solid transparent;'
            f'border-left:12px solid {PL};z-index:1;"></div>'
            f'{"".join(dots_parts)}'
            f'</div>'
        )

        # ==================== 下排：步骤编号 + 标题 + 描述 ====================
        row2_parts = []
        for name, num, title, desc in steps:
            row2_parts.append(
                f'<div style="flex:1;text-align:center;padding:0 4px;">'
                f'<div style="font-size:11px;color:{T2};font-weight:500;'
                f'letter-spacing:2px;text-transform:uppercase;">'
                f'步骤 {num}</div>'
                f'<div style="font-size:15px;font-weight:700;color:{T1};'
                f'margin:4px 0 2px 0;">{title}</div>'
                f'<div style="font-size:12px;color:{T2};line-height:1.55;">'
                f'{desc}</div></div>'
            )

        row2 = (
            f'<div style="display:flex;gap:12px;margin:4px 0 14px 0;">'
            f'{"".join(row2_parts)}'
            f'</div>'
        )

        # ==================== 合并输出 ====================
        st.markdown(row1 + row2, unsafe_allow_html=True)

    def _render_feature_cards():
        """渲染右侧功能入口卡片网格（2行 x 3列）"""
        features = [
            ("🗄️", "数据库配置", "连接 PostgreSQL，查看数据表", "数据库配置"),
            ("🔢", "向量预处理", "地址向量化，建立向量索引", "向量预处理"),
            ("🔍", "地址匹配", "粗召回 + MGeo 精排匹配", "地址匹配"),
            ("📊", "结果管理", "浏览、筛选、导出、人工纠正", "结果管理"),
            ("🏷️", "地址结构化解析", "地址 NER 分词，提取省市区街道", "地址结构化解析"),
            ("📝", "系统日志", "查看运行日志与向量调试", "系统日志"),
        ]

        for row_idx in range(0, len(features), 3):
            cols = st.columns(3)
            for col_idx, col in enumerate(cols):
                idx = row_idx + col_idx
                if idx < len(features):
                    icon, name, desc, menu = features[idx]
                    with col:
                        with st.container(border=True):
                            st.markdown(
                                f"<div style='font-size:2em;text-align:center'>{icon}</div>",
                                unsafe_allow_html=True
                            )
                            if st.button(name, key=f"home_card_{name}", use_container_width=True):
                                st.session_state.selected_menu = menu
                                st.rerun()
                            st.caption(desc)

    selected_menu = st.session_state.selected_menu
    
    if selected_menu == "首页":
        show_home_page()
    elif selected_menu == "数据库配置":
        show_db_config()
    elif selected_menu == "地址结构化解析":
        show_address_tagging()
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