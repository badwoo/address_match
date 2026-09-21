# 首页功能设计文档

## 背景

系统目前没有独立的首页，默认进入"数据库配置"页面。用户需要在各功能页面之间自行切换，缺乏统一的工作流引导入口。

## 目标

新增一个"首页"页面，作为系统默认入口，以功能导航为核心，引导用户按步骤完成地址匹配工作流，同时提供全量功能入口。

## 设计方案

### 整体布局

页面采用左右分区布局：
- **左侧（约 1/3 宽度）**：主流程纵向步骤导航
- **右侧（约 2/3 宽度）**：功能入口卡片网格（2 行 × 3 列）

### 菜单系统调整

1. 侧边栏 `menu_options` 列表首项新增 `("首页", "首页")`
2. 默认选中菜单 `selected_menu` 从 `"数据库配置"` 改为 `"首页"`
3. 主内容区路由新增 `elif selected_menu == "首页": show_home_page()`

### 左侧：主流程步骤导航

4 个核心步骤纵向排列，体现地址匹配的完整工作流：

| 步骤 | 图标 | 名称 | 描述 | 点击跳转 |
|------|------|------|------|---------|
| 1 | 🗄️ | 数据库配置 | 连接 PostgreSQL 数据库，查看表结构 | 数据库配置页面 |
| 2 | 🔢 | 向量预处理 | 配置字段映射，生成地址向量，建立索引 | 向量预处理页面 |
| 3 | 🔍 | 地址匹配 | 执行粗召回与 MGeo 精排，获取匹配结果 | 地址匹配页面 |
| 4 | 📊 | 结果管理 | 查看、筛选、导出匹配结果，人工纠正 | 结果管理页面 |

**交互**：
- 每个步骤是可点击的卡片，点击后修改 `st.session_state.selected_menu` 并 `st.rerun()`
- 步骤之间用细线分隔，体现流程顺序
- 复用 `ui_theme.py` 中的颜色令牌保持风格一致

**实现**：
- 使用 `st.container(border=True)` 包裹每个步骤
- 卡片内布局：`st.columns([0.15, 0.85])`，左侧放 emoji，右侧放名称+描述

### 右侧：功能入口卡片网格

6 个功能入口卡片，2 行 × 3 列：

| 卡片 | 图标 | 名称 | 描述 |
|------|------|------|------|
| 1 | 🗄️ | 数据库配置 | 连接 PostgreSQL，查看数据表 |
| 2 | 🔢 | 向量预处理 | 地址向量化，建立向量索引 |
| 3 | 🔍 | 地址匹配 | 粗召回 + MGeo 精排匹配 |
| 4 | 📊 | 结果管理 | 浏览、筛选、导出、人工纠正 |
| 5 | 🏷️ | 地址结构化解析 | 地址 NER 分词，提取省市区街道 |
| 6 | 📝 | 系统日志 | 查看运行日志与向量调试 |

**交互**：
- 每个卡片可点击跳转对应页面
- 卡片 hover 效果通过 Streamlit 按钮或 `st.markdown` + CSS 实现

**实现**：
- 使用 `st.columns(3)` 创建网格
- 每列内用 `st.container(border=True)` 包裹
- 卡片内：emoji 图标（居中）+ 功能名称（加粗）+ 描述（小号灰色文字）

## 技术实现

### 新增函数

```python
def show_home_page():
    """
    首页：功能导航入口，左侧主流程步骤 + 右侧功能卡片网格
    """
    st.subheader("首页")
    st.caption("地址语义匹配系统 — 选择下方功能开始工作")

    left_col, right_col = st.columns([1, 2])

    with left_col:
        st.markdown("### 📋 主流程")
        _render_workflow_steps()

    with right_col:
        st.markdown("### 🧩 功能入口")
        _render_feature_cards()


def _render_workflow_steps():
    """渲染主流程步骤导航"""
    steps = [
        ("🗄️", "数据库配置", "连接 PostgreSQL 数据库，查看表结构", "数据库配置"),
        ("🔢", "向量预处理", "配置字段映射，生成地址向量", "向量预处理"),
        ("🔍", "地址匹配", "粗召回 + MGeo 精排，获取匹配结果", "地址匹配"),
        ("📊", "结果管理", "浏览、筛选、导出、人工纠正", "结果管理"),
    ]
    for icon, name, desc, menu in steps:
        with st.container(border=True):
            c1, c2 = st.columns([0.15, 0.85])
            with c1:
                st.markdown(f"<div style='font-size:1.5em;text-align:center'>{icon}</div>", unsafe_allow_html=True)
            with c2:
                if st.button(name, key=f"home_step_{name}", use_container_width=True):
                    st.session_state.selected_menu = menu
                    st.rerun()
                st.caption(desc)


def _render_feature_cards():
    """渲染功能入口卡片网格"""
    features = [
        ("🗄️", "数据库配置", "连接 PostgreSQL，查看数据表", "数据库配置"),
        ("🔢", "向量预处理", "地址向量化，建立向量索引", "向量预处理"),
        ("🔍", "地址匹配", "粗召回 + MGeo 精排匹配", "地址匹配"),
        ("📊", "结果管理", "浏览、筛选、导出、人工纠正", "结果管理"),
        ("🏷️", "地址结构化解析", "地址 NER 分词，提取省市区街道", "地址结构化解析"),
        ("📝", "系统日志", "查看运行日志与向量调试", "系统日志"),
    ]
    # 2行 x 3列
    for row_idx in range(0, len(features), 3):
        cols = st.columns(3)
        for col_idx, col in enumerate(cols):
            idx = row_idx + col_idx
            if idx < len(features):
                icon, name, desc, menu = features[idx]
                with col:
                    with st.container(border=True):
                        st.markdown(f"<div style='font-size:2em;text-align:center'>{icon}</div>", unsafe_allow_html=True)
                        if st.button(name, key=f"home_card_{name}", use_container_width=True):
                            st.session_state.selected_menu = menu
                            st.rerun()
                        st.caption(desc)
```

### 修改点

| 位置 | 改动 | 说明 |
|------|------|------|
| `app.py` ~5568 行 | `menu_options` 首项新增 `("首页", "首页")` | 侧边栏菜单增加首页入口 |
| `app.py` ~184 行 | `selected_menu` 默认值改为 `"首页"` | 默认打开首页 |
| `app.py` ~5627 行 | 路由新增 `elif selected_menu == "首页": show_home_page()` | 首页页面路由 |
| `app.py` 新增 | `show_home_page()` 函数 | 首页主函数 |
| `app.py` 新增 | `_render_workflow_steps()` 函数 | 左侧流程步骤 |
| `app.py` 新增 | `_render_feature_cards()` 函数 | 右侧功能卡片 |

## 边界情况

- **数据库未连接**：首页正常显示，点击功能卡片跳转到对应页面后自然提示连接数据库
- **无匹配数据**：首页不涉及数据查询，不受影响
- **Streamlit 刷新**：首页状态完全无状态依赖，每次刷新都是全新渲染

## 不涉及的改动

- 不展示任何数据指标（已确认）
- 不做快捷操作按钮（已确认）
- 不修改现有功能页面的任何逻辑
- 不新增数据库表
