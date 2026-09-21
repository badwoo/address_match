# 匹配状态顺滑刷新改造实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将地址匹配页面的"每秒整体刷新"改造为"每 3 秒局部刷新 + 前端 JS 秒表"，消除页面闪烁，同时保留实时读秒、完成检测和页面切换兼容性。

**Architecture:** 使用 Streamlit 1.38 的 `st.fragment(run_every=3)` 把状态卡片封装为独立刷新单元；状态卡片内使用原生组件显示阶段/进度/速度/剩余时间，使用固定 key 的 `st.components.v1.html` iframe 渲染前端 JS 秒表；`ui_theme.py` 追加进度条 CSS 过渡；任务完成后 fragment 内触发整页 `st.rerun()` 切换到完成 UI。

**Tech Stack:** Python 3.12, Streamlit 1.38.0, PostgreSQL + pgvector

---

## 文件结构
| 文件 | 职责 | 改动类型 |
| --- | --- | --- |
| `pages/address_matching.py` | 新增 `render_matching_status_fragment`、`_render_status_card`、`_render_js_timer`；重构原匹配中状态展示分支；调整完成检测逻辑 | 修改 |
| `ui_theme.py` | 全局样式追加 `stProgress` 进度条 CSS 过渡 | 修改 |

---

## Task 1: 添加进度条 CSS 过渡样式

**Files:**

- Modify: `ui_theme.py`（全局样式注入函数内，通常是 `inject_global_styles` 或类似函数）
- [ ] **Step 1: 定位全局样式注入位置**打开 `ui_theme.py`，找到注入全局 CSS 的函数（如 `inject_global_styles`）。
- [ ] **Step 2: 追加进度条过渡 CSS**在全局样式字符串中追加以下内容（注意与前后 CSS 用大括号或换行分隔）：示例（假设使用 `st.markdown(..., unsafe_allow_html=True)` 注入）：
- [ ] **Step 3: 启动应用验证样式无语法错误**Run: `streamlit run app.py`Expected: 页面正常加载，无 CSS 报错；侧边栏和首页正常显示。
- [ ] **Step 4: Commit**

---

## Task 2: 在 address_matching.py 中新增 JS 秒表辅助函数

**Files:**

- Modify: `pages/address_matching.py`（在文件顶部 import 区域附近添加 `st.components.v1.html` 的 import）
- Modify: `pages/address_matching.py`（新增 `_render_js_timer` 函数）
- [ ] **Step 1: 添加 import**在 `pages/address_matching.py` 的 import 区域，现有 `import streamlit as st` 之后追加：
- [ ] **Step 2: 新增 ****`_render_js_timer`**** 函数**在 `reset_matching_status()` 函数之后（或文件顶部其他辅助函数附近）添加：
- [ ] **Step 3: 启动应用验证导入无错误**Run: `streamlit run app.py`Expected: 应用正常启动，无 import 错误。
- [ ] **Step 4: Commit**

---

## Task 3: 新增状态 Fragment 和重构状态卡片渲染

**Files:**

- Modify: `pages/address_matching.py`（新增 `render_matching_status_fragment` 和 `_render_status_card` 函数；重构 `show_address_matching` 中的 `matching_status['is_running']` 分支）
- [ ] **Step 1: 新增 ****`render_matching_status_fragment`**** 函数**在 `_render_js_timer` 之后添加：
- [ ] **Step 2: 新增 ****`_render_status_card`**** 函数**在 `render_matching_status_fragment` 之后添加：
- [ ] **Step 3: 重构 ****`show_address_matching`**** 中的运行中分支**找到 `show_address_matching` 中以下代码块（约第 777-905 行）：将其替换为：注意：原分支中所有状态同步逻辑已移到 `render_matching_status_fragment` 内部，因此替换后不需要保留原分支的状态同步代码。
- [ ] **Step 4: 调整完成检测逻辑的执行位置**确保以下完成检测逻辑仍然位于 `show_address_matching` 的主流程中，但在 `matching_status['is_running']` 分支之后（即保持原位置不变）：由于 `matching_status['is_running']` 分支现在会在运行时 `return`，这些完成检测逻辑只会在非运行状态下执行，符合预期。
- [ ] **Step 5: 启动应用验证无异常**Run: `streamlit run app.py`Expected: 页面正常加载；进入"地址匹配"页面后，状态卡片在未启动任务时不显示。
- [ ] **Step 6: Commit**

---

## Task 4: 运行回归测试

**Files:**

- Test: 现有 `tests/` 中与数据库、匹配流程相关的回归测试
- [ ] **Step 1: 运行与匹配页面相关的测试**Run: `pytest tests/ -v -k "matching or recall or vector"`Expected: 所有相关测试通过（或至少没有因为 `address_matching.py` 的改动而失败）。
- [ ] **Step 2: 运行全量测试**Run: `pytest tests/ -v`Expected: 全量测试通过或失败项与本次改动无关。
- [ ] **Step 3: Commit（如测试通过）**如测试全部通过：

---

## Task 5: 手动功能验证

**Files:**

- Test: 手动在浏览器中验证
- [ ] **Step 1: 启动应用并连接数据库**Run: `streamlit run app.py`在浏览器中访问 `http://localhost:8501`。 在"数据库配置"页面完成数据库连接。
- 选择或创建一个标签；
- 选择企业向量表和标准地址向量表；
- 点击"启动数据粗召回匹配"；
- 观察状态卡片：
- 粗召回完成后，应及时切换到"粗召回完成 UI"；
- 切换到"系统日志"页面，再切回"地址匹配"，确认后台仍在运行或状态已恢复。
- 切换到"系统日志"页面，再切回"地址匹配"，确认后台仍在运行或状态已恢复。
- 在粗召回完成后，点击"继续 MGeo 精确匹配"；
- 观察状态卡片：
- 精排完成后，应及时切换到"MGeo 精确匹配完成 UI"。
- 精排完成后，应及时切换到"MGeo 精确匹配完成 UI"。
- 在粗召回执行中点击"取消匹配"，确认任务停止并恢复初始 UI；
- 重新启动粗召回，完成后启动精排；
- 在精排执行中点击"取消匹配"，确认任务停止并恢复初始 UI。
- 在精排执行中点击"取消匹配"，确认任务停止并恢复初始 UI。
- [ ] **Step 5: Commit（如验证通过）**

---

## Task 6: 代码清理与最终审查

**Files:**

- Modify: `pages/address_matching.py`
- [ ] **Step 1: 检查是否遗留旧代码**在 `pages/address_matching.py` 中搜索：确认这些旧代码已被移除或替换。
- [ ] **Step 2: 检查代码格式与导入**确认：
- [ ] **Step 3: 最终提交**

---

## 自我审查

### Spec 覆盖检查
| 设计文档要求 | 对应任务 |
| --- | --- |
| `st.fragment(run_every=3)` 封装状态卡片 | Task 3 |
| JS 秒表渲染且视觉上在卡片内部 | Task 2 + Task 3 |
| 进度条 CSS 过渡 | Task 1 |
| 保留完成检测 | Task 3 Step 4 |
| 保留页面切换兼容性 | Task 3（不改动 session_state 和后台线程）+ Task 5 Step 2 |
| 不引入新依赖 | 所有任务均使用现有 Streamlit API |
| 取消按钮行为不变 | Task 3 Step 2 |

### Placeholder 检查

- 无 "TBD" / "TODO" / "implement later" / "fill in details"；
- 无 "Add appropriate error handling" 等模糊描述；
- 每个步骤包含具体代码、命令和预期结果；
- 文件路径使用相对路径或项目内绝对路径。

### 一致性检查

- `_render_js_timer` 的参数和调用位置一致；
- `render_matching_status_fragment` 中同步的状态字段与 `matching_status` 初始化的字段一致；
- `_render_status_card` 中的取消逻辑与原有取消逻辑一致。

---

## 执行交接

**Plan complete and saved to ****`docs/superpowers/plans/2026-06-17-matching-status-smooth-refresh-plan.md`****. Two execution options:**

**1. Subagent-Driven (recommended)** - Dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** - Execute tasks in this session using `superpowers:executing-plans`, batch execution with checkpoints.

**Which approach?**
