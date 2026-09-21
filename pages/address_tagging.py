"""
地址结构化解析页面
================
调用MGeo门址地址结构化要素解析模型，将地址拆分为结构化要素。
支持12级、17级、17_2三种模式。
"""

import streamlit as st
import time
import pandas as pd
from database.connection import DBConnection, quote_identifier
from utils.logger import logger
from ui_theme import Colors
from app_common import format_time, _render_device_selector, read_csv_with_encoding, _get_cached_db_connection


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
        'result_table': '',
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


TAGGING_POLL_INTERVAL = 2  # 秒


def _render_tagging_status_inner(mode):
    """
    地址结构化解析状态展示内部逻辑（供 fragment 调用）。

    包含：状态同步（从 parser 对象读取状态到 session_state）、渲染进度卡片、取消按钮、完成检测。
    完成（is_running=False）时直接调用 st.rerun() 触发整个脚本重新运行，
    由主线程根据 tagging_status['completed'] 进入完成/失败分支。

    Args:
        mode: '12' / '17' / '17_2'
    """
    if mode == '17_2':
        level_label = '17级（双字段）'
        status_prefix = 'address_tagging_17_2'
    elif mode == '17':
        level_label = '17级（MGeo）'
        status_prefix = 'address_tagging_17'
    else:
        level_label = '12级'
        status_prefix = 'address_tagging'

    status_key = f'{status_prefix}_status'
    results_key = f'{status_prefix}_results'
    parser_key = f'{status_prefix}_parser'

    tagging_status = st.session_state[status_key]

    # 状态同步：从 parser 对象读取最新状态
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
                            'copy_table': parser_stat['completion_copy_table'],
                            'result_table': parser_stat.get('completion_result_table', '')
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

    # 渲染进度卡片
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

    # 检测完成：is_running=False 时（解析完成/失败/取消），直接触发整个脚本 rerun，
    # 由主线程根据 tagging_status['completed'] 和 error_message 进入对应分支。
    # （Streamlit 1.37+ 中 fragment 内 st.rerun() 会触发整个脚本重新运行）
    if not tagging_status['is_running']:
        st.rerun()


@st.fragment(run_every=TAGGING_POLL_INTERVAL)
def render_tagging_status_fragment_17():
    """地址17级（MGeo）结构化解析状态 fragment，每 2 秒自刷新一次"""
    _render_tagging_status_inner('17')


@st.fragment(run_every=TAGGING_POLL_INTERVAL)
def render_tagging_status_fragment_12():
    """地址12级结构化解析状态 fragment，每 2 秒自刷新一次"""
    _render_tagging_status_inner('12')


@st.fragment(run_every=TAGGING_POLL_INTERVAL)
def render_tagging_status_fragment_17_2():
    """地址17级（双字段）结构化解析状态 fragment，每 2 秒自刷新一次"""
    _render_tagging_status_inner('17_2')


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

    if mode != '12':
        tag_device = _render_device_selector(key=f'address_tagging_{mode}_device_selector')
    else:
        tag_device = 'cpu'  # 12级规则引擎无GPU需求，固定CPU

    # address_tagging_*_status 已在 app_common.init_session_state() 中初始化
    tagging_status = st.session_state[status_key]

    # ---- 运行中 ----
    if tagging_status['is_running']:
        # 使用 fragment 局部刷新进度，避免 time.sleep+st.rerun 阻塞主线程
        if is_17:
            render_tagging_status_fragment_17()
        elif is_17_2:
            render_tagging_status_fragment_17_2()
        else:
            render_tagging_status_fragment_12()
        # 后备检查：fragment 同步执行时会从 parser 读取最新状态并更新 session_state。
        # 若 fragment 内 st.rerun() 在某些场景未触发整个脚本重新运行，
        # 这里重新读取 session_state：若 is_running 已被同步为 False（parser 已完成/失败），
        # 则不 return，继续走下面的完成/失败分支，避免卡在"运行中"页面。
        tagging_status = st.session_state[status_key]
        if tagging_status['is_running']:
            return

    # ---- 完成 ----
    if tagging_status['completed']:
        st.markdown(f"<div class='status-card status-card-success'>", unsafe_allow_html=True)
        st.subheader(f"地址{level_label}结构化解析完成")

        # ---- 执行时间信息 ----
        if tagging_status['start_time'] and tagging_status['end_time']:
            duration = tagging_status['end_time'] - tagging_status['start_time']
            st.write(f"**开始时间**: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(tagging_status['start_time']))}")
            st.write(f"**结束时间**: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(tagging_status['end_time']))}")
            st.write(f"**执行时长**: {format_time(duration)}")
        elif tagging_status['start_time']:
            st.write(f"**开始时间**: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(tagging_status['start_time']))}")

        # ---- 表数量信息 ----
        st.write(f"**解析结果数**: {tagging_status.get('result_count', 0):,}")
        if tagging_status.get('total_count', 0) > 0:
            st.write(f"**源表记录数**: {tagging_status['total_count']:,}")

        input_type = tagging_status.get('input_type', 'file')

        if input_type == 'file':
            # ---- 文件模式：显示表名信息 + 下载按钮 + 查看结果 ----
            if tagging_status.get('result_table'):
                st.write(f"**结果表**: `{tagging_status['result_table']}`")
            if tagging_status.get('copy_table'):
                st.write(f"**副本表**: `{tagging_status['copy_table']}`")

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

                # 文件模式也提供"查看分词结果"按钮，展开结果预览
                with st.expander("👁️ 查看分词结果", expanded=False):
                    st.dataframe(result_df, use_container_width=True)
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
            # ---- 数据库模式：显示表名信息 + 跳转查看分词结果按钮 ----
            if tagging_status.get('source_table'):
                st.write(f"**源表**: `{tagging_status['source_table']}`")
            if tagging_status.get('result_table'):
                st.write(f"**结果表**: `{tagging_status['result_table']}`")
            if tagging_status.get('copy_table'):
                st.write(f"**副本表**: `{tagging_status['copy_table']}`")

            st.divider()
            col1, col2, col3 = st.columns(3)
            with col1:
                if is_17_2:
                    result_tab_name = "地址17级双字段结构化解析结果"
                elif is_17:
                    result_tab_name = "地址17级结构化解析结果"
                else:
                    result_tab_name = "地址结构化解析结果"
                if st.button("📊 跳转查看分词结果", key=f'view_address_tagging_{mode}_result', type='primary'):
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

        st.markdown("</div>", unsafe_allow_html=True)
        return

    # ---- 失败 ----
    # 当 is_running=False 且 completed=False 且 error_message 非空时，说明解析中途失败
    # （如数据库查询超时、结果写入失败等）。原实现缺少此分支，直接落到"输入选择"，
    # 导致用户看不到错误信息，表现为"程序结束了但没跳到结束页面"。
    if (not tagging_status['is_running']
            and not tagging_status['completed']
            and tagging_status.get('error_message')):
        st.markdown(f"<div class='status-card status-card-error'>", unsafe_allow_html=True)
        st.subheader(f"地址{level_label}结构化解析失败")

        if tagging_status.get('start_time'):
            st.write(f"**开始时间**: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(tagging_status['start_time']))}")
        if tagging_status.get('end_time'):
            st.write(f"**结束时间**: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(tagging_status['end_time']))}")
            duration = tagging_status['end_time'] - tagging_status.get('start_time', tagging_status['end_time'])
            st.write(f"**耗时**: {format_time(duration)}")

        # 显示已处理进度，让用户了解失败发生在哪个阶段
        if tagging_status.get('total_count', 0) > 0:
            st.write(f"**已处理进度**: {tagging_status['processed_count']:,}/{tagging_status['total_count']:,} "
                     f"({tagging_status['progress'] * 100:.1f}%)")

        st.error(f"❌ 解析失败: {tagging_status['error_message']}")

        col1, col2 = st.columns(2)
        with col1:
            if st.button("🔄 重新解析", key=f'restart_address_tagging_{mode}_failed'):
                # 保留输入方式（file/database），仅重置运行状态
                prev_input_type = tagging_status.get('input_type', 'file')
                st.session_state[status_key] = _reset_address_tagging_status(prev_input_type)
                if results_key in st.session_state:
                    del st.session_state[results_key]
                st.rerun()
        with col2:
            if st.button("↩️ 返回", key=f'back_address_tagging_{mode}_failed'):
                prev_input_type = tagging_status.get('input_type', 'file')
                st.session_state[status_key] = _reset_address_tagging_status(prev_input_type)
                if results_key in st.session_state:
                    del st.session_state[results_key]
                st.rerun()

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
        db_conn = _get_cached_db_connection(
            host=db_config['host'], port=db_config['port'],
            schema=db_config['schema'], dbname=db_config['dbname'],
            user=db_config['user'], password=db_config['password']
        )

        if db_conn is None:
            st.error("无法连接数据库")
            return

        try:
            tables = db_conn.get_tables()
            if not tables:
                st.warning("数据库中没有可用的数据表")
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
        # 注：db_conn 走缓存，不在此关闭，由 TTL 自然过期

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
        # 关键：启动后台线程前先设置 parser 的 is_running=True，
        # 避免 fragment 第一次同步执行时读到 parser.is_running=False（后台线程还没来得及设置），
        # 触发误 st.rerun() 导致任务刚启动就被判定为"未运行"而回退到输入选择分支。
        parser._update_status(is_running=True, status_message='正在初始化...')
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
