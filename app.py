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
from ui_theme import Colors, Typography, inject_global_styles
from app_common import init_session_state
from pages.db_config import show_db_config
from pages.vector_preprocess import show_vector_preprocess
from pages.address_matching import show_address_matching
from pages.address_tagging import show_address_tagging
from pages.result_management import show_result_management
from pages.system_logs import show_system_logs


def main():
    st.set_page_config(
        page_title="中文地址语义匹配系统",
        page_icon="🔍",
        layout="wide",
        initial_sidebar_state="expanded"
    )

    init_session_state()
    # 注：st.markdown 注入的 CSS 在 st.rerun() 后会随页面清空而消失，
    # 因此每次 rerun 都需要重新注入，不能用 session_state 守卫跳过。
    # st.markdown 注入开销极小，不会导致页面闪烁。
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
