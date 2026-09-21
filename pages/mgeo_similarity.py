"""
MGeo地址相似度匹配页面
=====================
独立的地址相似度匹配功能，支持文件上传和数据库表输入。
直接调用MGeo模型对地址A和地址B进行逐行匹配。
"""

import streamlit as st
import time
import pandas as pd
from database.connection import DBConnection, quote_identifier
from utils.logger import logger
from ui_theme import Colors
from app_common import format_time, _render_device_selector, read_csv_with_encoding, _get_cached_db_connection


MGEO_SIM_POLL_INTERVAL = 2  # 秒


@st.fragment(run_every=MGEO_SIM_POLL_INTERVAL)
def render_mgeo_sim_status_fragment():
    """
    MGeo相似度匹配状态实时展示 fragment。
    每 2 秒自刷新一次，只刷新进度区域，不触发整页 rerun。
    包含：状态同步（从 matcher 对象读取状态到 session_state）、渲染进度卡片、取消按钮、完成检测。
    完成时设置 mgeo_similarity_finished_trigger，由主线程下次 rerun 时处理切换到完成 UI。
    """
    mgeo_sim_status = st.session_state.mgeo_similarity_status

    # 状态同步：从 matcher 对象读取最新状态
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
                if matcher_stat.get('completion_success'):
                    st.session_state.mgeo_similarity_status.update({
                        'is_running': False,
                        'completed': True,
                        'end_time': end_time,
                        'result_count': matcher_stat.get('completion_result_count', 0),
                        'status_message': '匹配完成',
                        'progress': 1.0
                    })
                    # 文件输入：保存结果到内存供下载
                    if mgeo_sim_status.get('input_type') == 'file' and matcher_stat.get('completion_results'):
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

    # 渲染进度卡片
    st.markdown(f"<div class='status-card status-card-warning'>", unsafe_allow_html=True)
    st.subheader("MGeo相似度匹配执行状态")

    if mgeo_sim_status['start_time']:
        start_time_str = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(mgeo_sim_status['start_time']))
        elapsed = time.time() - mgeo_sim_status['start_time']
        st.write(f"**开始时间**: {start_time_str}")
        st.write(f"**已运行时间**: {format_time(elapsed)}")

    st.progress(mgeo_sim_status['progress'])
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

    # 检测完成：设置触发器，由主线程下次 rerun 时处理切换到完成 UI
    # 必须同时满足 is_running=False 和 completed=True，避免中间状态触发跳转
    if not mgeo_sim_status['is_running'] and mgeo_sim_status.get('completed'):
        st.session_state['mgeo_similarity_finished_trigger'] = True
        st.rerun()


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

    # mgeo_similarity_status 已在 app_common.init_session_state() 中初始化
    mgeo_sim_status = st.session_state.mgeo_similarity_status

    # 检测完成触发器
    if st.session_state.get('mgeo_similarity_finished_trigger'):
        logger.info("[MGeo相似度匹配] 检测到完成触发器，清除并刷新")
        del st.session_state['mgeo_similarity_finished_trigger']
        st.rerun()

    # 如果正在运行，显示进度
    if mgeo_sim_status['is_running']:
        # 使用 fragment 局部刷新进度，避免 time.sleep+st.rerun 阻塞主线程
        render_mgeo_sim_status_fragment()
        return

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
    extra_col = ''
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

        db_conn = _get_cached_db_connection(
            host=db_config['host'],
            port=db_config['port'],
            schema=db_config['schema'],
            dbname=db_config['dbname'],
            user=db_config['user'],
            password=db_config['password']
        )

        if db_conn is None:
            st.error("无法连接数据库")
            st.markdown("</div>", unsafe_allow_html=True)
            return

        try:
            tables = db_conn.get_tables()
            if not tables:
                st.warning("数据库中没有可用的数据表")
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

                extra_col = st.selectbox(
                    "选择其他字段（可选）",
                    options=[''] + columns,
                    key='mgeo_sim_extra_db',
                    help="选择需要附加到匹配结果中的其他字段，不选择则匹配结果中该字段为空"
                )

                st.session_state.mgeo_sim_selected_table = selected_table
                st.session_state.mgeo_sim_selected_addr_a = address_a_col
                st.session_state.mgeo_sim_selected_addr_b = address_b_col
                st.session_state.mgeo_sim_selected_id_col = id_col
                st.session_state.mgeo_sim_selected_extra_col = extra_col

                count_sql = f"SELECT COUNT(*) as count FROM {quote_identifier(selected_table)}"
                count_cursor = db_conn.execute(count_sql)
                if count_cursor:
                    total = count_cursor.fetchone()['count']
                    st.info(f"📊 表 {selected_table} 共 {total:,} 条记录")

        except Exception as e:
            st.error(f"获取表信息失败: {str(e)}")
        # 注：db_conn 走缓存，不在此关闭，由 TTL 自然过期

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
            start_mgeo_similarity_matching(db_config, device, input_type, address_a_col, address_b_col, id_col, extra_col)
    else:
        st.info("请先选择数据源和地址字段")

    st.markdown("</div>", unsafe_allow_html=True)


def start_mgeo_similarity_matching(db_config, device, input_type, address_a_col, address_b_col, id_col='', extra_col=''):
    """
    启动MGeo地址相似度匹配

    Args:
        db_config: 数据库配置字典
        device: 运行设备
        input_type: 输入类型 ('file' 或 'database')
        address_a_col: 地址A字段名
        address_b_col: 地址B字段名
        id_col: 可选的标识字段名
        extra_col: 可选的其他附加字段名
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
            # 数据库输入：不再预加载fetchall，由后台线程流式处理
            data_source = None
            table_name = st.session_state.mgeo_sim_selected_table
            db_conn = _get_cached_db_connection(
                host=db_config['host'],
                port=db_config['port'],
                schema=db_config['schema'],
                dbname=db_config['dbname'],
                user=db_config['user'],
                password=db_config['password']
            )
            if db_conn is None:
                st.error("无法连接数据库")
                return

            # 使用独立连接写入结果，避免服务端游标与写入操作冲突
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
            extra_col=extra_col if extra_col else None,
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
