"""
结果管理页面
===========
匹配结果浏览、筛选、导出、人工纠正、统计分析。
"""

import streamlit as st
import time
import pandas as pd
from database.connection import DBConnection, quote_identifier
from database.data_loader import DataLoader
from database.tag_manager import TagManager
from config import Config
from ui_theme import Colors, card_style, status_container_style
from app_common import _goto_page, _prev_page, _next_page, _get_cached_db_connection, get_cached_all_tags, _tags_tuple_to_list, _restore_page_size, _make_page_size_persist_callback


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

    # 分页状态已在 app_common.init_session_state() 中统一初始化

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
        return

    data_loader = DataLoader(db_conn)

    # ========== 标签选择 ==========
    tag_mgr = TagManager(db_conn)
    # 使用缓存的标签列表查询（30秒TTL）
    all_tags = _tags_tuple_to_list(get_cached_all_tags(
        db_config['host'], db_config['port'], db_config['dbname'],
        db_config['user'], db_config['password'], db_config['schema']
    ))

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
                                _restore_page_size('recall_page_size')
                                page_size = st.selectbox("每页", options=[10, 20, 50, 100, 200], index=1, key='recall_page_size', on_change=_make_page_size_persist_callback('recall_page_size'), label_visibility="collapsed")
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
                            # 持久化恢复：避免人工纠正/人工选择跳转返回后 page_size 重置为默认 20
                            _restore_page_size('match_page_size')
                            page_size = st.selectbox("每页", options=[10, 20, 50, 100, 200], index=1, key='match_page_size', on_change=_make_page_size_persist_callback('match_page_size'), label_visibility="collapsed")
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
                    # key 包含 page 和 page_size：翻页或改变每页大小时显式重置 selection（语义清晰）
                    # 配合 ORDER BY 中添加 id 作为 tiebreaker，保证同页内行顺序稳定，避免点击行触发 rerun 时 selection 被误清
                    event = st.dataframe(results, use_container_width=True, on_select="rerun", selection_mode="multi-row", key=f'match_results_{result_match_table}_p{page}_s{page_size}')
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
                            _restore_page_size('sim_page_size')
                            sim_page_size = st.selectbox("每页", options=[10, 20, 50, 100, 200], index=1, key='sim_page_size', on_change=_make_page_size_persist_callback('sim_page_size'), label_visibility="collapsed")
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
                                        _restore_page_size('mgeo_copy_page_size')
                                        mgeo_page_size = st.selectbox(
                                            "每页", options=[10, 20, 50, 100], index=1,
                                            key='mgeo_copy_page_size', on_change=_make_page_size_persist_callback('mgeo_copy_page_size'),
                                            label_visibility="collapsed"
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
                    _restore_page_size('tagging_page_size')
                    tagging_page_size = st.selectbox(
                        "每页显示",
                        options=[10, 20, 50, 100, 200],
                        index=1,
                        key='tagging_page_size',
                        on_change=_make_page_size_persist_callback('tagging_page_size')
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
                    _restore_page_size('tagging_17_page_size')
                    tagging_17_page_size = st.selectbox(
                        "每页显示", options=[10, 20, 50, 100, 200],
                        index=1, key='tagging_17_page_size',
                        on_change=_make_page_size_persist_callback('tagging_17_page_size')
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
                    _restore_page_size('tagging_17_2_page_size')
                    tagging_17_2_page_size = st.selectbox(
                        "每页显示", options=[10, 20, 50, 100, 200],
                        index=1, key='tagging_17_2_page_size',
                        on_change=_make_page_size_persist_callback('tagging_17_2_page_size')
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

    # 注：db_conn 走缓存，不在此关闭，由 TTL 自然过期
