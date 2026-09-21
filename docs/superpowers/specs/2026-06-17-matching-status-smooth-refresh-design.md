# 地址匹配状态展示顺滑刷新改造设计文档

## 1. 背景与目标

### 1.1 当前问题

在 `pages/address_matching.py` 的匹配执行状态展示中，当 `matching_status['is_running']` 为 True 时，页面使用 `time.sleep(1) + st.rerun()` 每秒整体刷新一次：

```python
refresh_placeholder = st.empty()
refresh_placeholder.info("页面将自动刷新以监测完成状态...")

time.sleep(1)
st.rerun()

```

这导致：

- 整个 Streamlit 脚本每秒重新执行一次；
- 侧边栏、标签管理、向量表选择等静态区域跟着重绘；
- 用户能明显感知到"页面每秒闪一下"。

### 1.2 设计目标

在不改变匹配执行核心逻辑的前提下：

1. 将刷新范围从"整个页面"缩小到"状态卡片"；
2. 前端 JS 独立维护已运行时间，不再依赖 Python rerun；
3. 保留任务完成的及时检测；
4. 保留当前"切换页面再切回来不中断执行"的行为；
5. 不引入新的 Python 依赖；
6. 已运行时间视觉上仍与原来一样放在状态卡片内部。

---

## 2. 现状行为梳理

### 2.1 状态存储

所有匹配状态都保存在 `st.session_state` 中：

- `matching_status`：整体匹配状态；
- `recall_status`：粗召回阶段状态；
- `matcher`：粗召回阶段的后台匹配器实例；
- `running_ranking_status`：MGeo 精排阶段的后台状态对象。

### 2.2 后台线程

粗召回和 MGeo 精排都在 `daemon=True` 的后台线程中执行：

- 粗召回：`matcher.start_recall_async()`（`[matching/matcher.py:528-627](matching/matcher.py#L528-L627)`）
- 精排：`start_mgeo_ranking()` 内启动的 `ranking_thread`（`[pages/address_matching.py:260-496](pages/address_matching.py#L260-L496)`）

### 2.3 完成通知

- 粗召回完成后，后台回调 `on_recall_completed` 设置 `recall_finished_trigger = True`；
- 精排完成后，`running_ranking_status.is_running` 变为 False，`matching_status['ranking_completed']` 变为 True。

### 2.4 页面切换兼容性

由于状态对象和后台线程都不依赖当前页面实例，切换页面再切回来：

- 后台线程继续运行；
- `st.session_state` 中的状态保留；
- 重新渲染时可以恢复到正确的状态。

---

## 3. 设计方案

### 3.1 总体架构

采用 **C 方案**：`st.fragment` 局部刷新 + 前端 JS 秒表。

```
┌─────────────────────────────────────────────────────────────┐
│                     页面主体（不自动刷新）                     │
│  ┌───────────────────────────────────────────────────────┐  │
│  │            状态 Fragment（每 3 秒自刷新）               │  │
│  │                                                       │  │
│  │  Streamlit 原生组件：                                  │  │
│  │    - 标题、开始时间                                     │  │
│  │    - 当前阶段、进度条、速度、剩余时间                    │  │
│  │    - 取消按钮                                          │  │
│  │                                                       │  │
│  │  JS iframe（固定 key，不随 fragment 刷新重置）：        │  │
│  │    - 已运行时间（1 秒更新）                             │  │
│  └───────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘

```

### 3.2 关键改动

#### 3.2.1 新增：状态 Fragment

```python
POLL_INTERVAL = 3  # 秒

@st.fragment(run_every=POLL_INTERVAL)
def render_matching_status_fragment():
    """
    匹配状态实时展示 fragment。
    每 3 秒自刷新一次，只刷新状态卡片区域，不影响页面其他部分。
    """
    matching_status = st.session_state.matching_status

    # 1. 同步后台线程状态（保持现有逻辑）
    if matching_status.get('current_stage') == 'MGeo精确匹配' \
       and 'running_ranking_status' in st.session_state:
        stat = st.session_state.running_ranking_status.get_status()
        matching_status.update({
            'is_running': stat['is_running'],
            'processed_count': stat['processed_count'],
            'total_count': stat['total_count'],
            'current_stage': stat['current_stage'],
            'progress': stat['progress'],
            'speed': stat['speed'],
            'remaining_time': stat['remaining_time'],
            'status_message': stat['status_message'],
            'error_message': stat['error_message'],
            'ranking_completed': stat['ranking_completed'],
            'match_count': stat['match_count'],
        })
    elif 'matcher' in st.session_state:
        stat = st.session_state.matcher.get_status()
        matching_status.update({
            'is_running': stat['is_running'],
            'processed_count': stat['processed_count'],
            'total_count': stat['total_count'],
            'current_stage': stat['current_stage'],
            'progress': stat['progress'],
            'speed': stat['speed'],
            'remaining_time': stat['remaining_time'],
            'status_message': stat['status_message'],
            'error_message': stat['error_message'],
        })

    # 2. 渲染状态卡片
    _render_status_card(matching_status)

    # 3. 检测完成：切到完整页面刷新以显示完成 UI
    if not matching_status['is_running']:
        st.rerun()

```

#### 3.2.2 新增/重构：状态卡片渲染

```python
def _render_status_card(matching_status):
    """
    渲染匹配执行状态卡片。
    与原来视觉一致，但已运行时间由前端 JS 秒表渲染。
    """
    st.markdown("<div class='status-card status-card-warning'>", unsafe_allow_html=True)
    st.subheader("匹配执行状态")

    if matching_status['start_time']:
        start_time_str = time.strftime(
            '%Y-%m-%d %H:%M:%S',
            time.localtime(matching_status['start_time'])
        )
        st.write(f"**开始时间**: {start_time_str}")

        # 已运行时间：标签原生 + JS iframe 数值
        label_col, value_col = st.columns([1, 4])
        with label_col:
            st.write("**已运行时间**:")
        with value_col:
            _render_js_timer(matching_status['start_time'])

    st.write(f"**当前阶段**: {matching_status['current_stage']}")

    is_recall_stage = matching_status['current_stage'] == '数据粗召回'
    is_mgeo_stage = matching_status['current_stage'] == 'MGeo精确匹配'

    if is_recall_stage:
        st.progress(0)
        st.info("🔄 正在执行批量召回，请稍候...")
    else:
        st.progress(matching_status['progress'])
        st.write(
            f"**处理进度**: {matching_status['processed_count']:,}/"
            f"{matching_status['total_count']:,} "
            f"({matching_status['progress'] * 100:.1f}%)"
        )
        st.write(f"**处理速度**: {matching_status['speed']:.2f} 条/秒")
        st.write(f"**预计剩余时间**: {format_time(matching_status['remaining_time'])}")

    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button("⏹️ 取消匹配"):
            # 保持现有取消逻辑不变
            if 'matcher' in st.session_state and st.session_state.matcher:
                try:
                    st.session_state.matcher.stop()
                except Exception:
                    pass

            if 'running_ranking_status' in st.session_state and st.session_state.running_ranking_status:
                try:
                    st.session_state.running_ranking_status.is_running = False
                except Exception:
                    pass

            reset_matching_status()
            if 'running_ranking_status' in st.session_state:
                del st.session_state.running_ranking_status
            st.success("匹配已取消")
            st.rerun()

    with col2:
        st.info("🔄 匹配进行中...")

    st.markdown("</div>", unsafe_allow_html=True)

```

#### 3.2.3 新增：前端 JS 秒表

```python
def _render_js_timer(start_time: float, key: str = "matching_elapsed_timer"):
    """
    渲染前端 JS 秒表。

    使用固定 key，HTML 内容只依赖 start_time。
    在 fragment 每 3 秒刷新时，只要 start_time 不变，iframe 不会重新加载，
    JS 定时器持续运行，秒表不会重置。
    """
    html = f"""
    <div id="timer-root" style="
        font-family: inherit;
        font-size: 1rem;
        color: inherit;
        background: transparent;
        padding: 0;
        margin: 0;
        line-height: 1.6;
    ">
      <span id="elapsed">0.0 秒</span>
    </div>
    <script>
      (function() {{
        const startTime = {start_time};
        const el = document.getElementById('elapsed');
        if (!el) return;

        const fmt = function(s) {{
          if (s < 60) return s.toFixed(1) + ' 秒';
          const m = Math.floor(s / 60);
          const sec = Math.floor(s % 60);
          if (s < 3600) return m + ' 分 ' + sec + ' 秒';
          const h = Math.floor(s / 3600);
          const rem = Math.floor((s % 3600) / 60);
          return h + ' 小时 ' + rem + ' 分';
        }};

        const tick = function() {{
          const elapsed = Math.max(0, (Date.now() / 1000) - startTime);
          el.textContent = fmt(elapsed);
        }};

        tick();
        setInterval(tick, 1000);
      }})();
    </script>
    """
    st.components.v1.html(html, height=25, key=key)

```

#### 3.2.4 新增：进度条 CSS 过渡

在 `ui_theme.py` 的全局样式中追加：

```css
.stProgress > div > div > div {
    transition: width 0.5s ease-out !important;
}

```

效果：每 3 秒同步一次真实进度时，进度条平滑滑动，而不是瞬间跳变。

### 3.3 主流程调整

原主流程中：

```python
if matching_status['is_running']:
    # ... 同步状态 ...
    # ... 渲染状态卡片 ...
    # ... 取消按钮 ...
    time.sleep(1)
    st.rerun()

```

改造后：

```python
if matching_status['is_running']:
    # fragment 负责每 3 秒自刷新
    render_matching_status_fragment()

    # 配置区保持显示，但不可编辑
    st.subheader("地址匹配配置")
    with st.expander("参数配置（匹配进行中不可修改）", expanded=False):
        st.info("匹配正在进行中，参数配置暂时不可修改")
    return

```

### 3.4 完成检测逻辑调整

#### 3.4.1 粗召回完成触发器

保留现有逻辑：

```python
if st.session_state.get('recall_finished_trigger'):
    del st.session_state['recall_finished_trigger']
    st.rerun()

```

#### 3.4.2 粗召回兜底检测

保留现有数据库兜底检测，但**只在非运行状态、且 ****`recall_completed`**** 为 False 时执行一次**，避免每次 full rerun 都查询数据库：

```python
if not matching_status['is_running'] and not matching_status.get('recall_completed'):
    # 仅在当前阶段为粗召回相关阶段时执行数据库检测
    if matching_status.get('current_stage') in ['数据粗召回', '数据粗召回完成']:
        # ... 查询 recall_results 表 ...
        # 如果确认完成，更新 matching_status/recall_status 并 st.rerun()

```

#### 3.4.3 精排完成

由 fragment 内部检测 `matching_status['is_running']` 变为 False 后调用 `st.rerun()` 触发。

---

## 4. 兼容性保证

### 4.1 后台线程不受影响

- 不修改 `matching/matcher.py`；
- 不修改 `start_recall_matching()` 和 `start_mgeo_ranking()` 的后台线程启动逻辑；
- 后台线程仍然是 `daemon=True`，页面切换不中断。

### 4.2 状态对象仍在 session_state 中

- `matcher`、`running_ranking_status`、`matching_status`、`recall_status` 继续保存在 `st.session_state`；
- fragment 每次都从这些 session_state 对象读取最新状态；
- 页面重载或切换回来后，状态可恢复。

### 4.3 取消按钮行为不变

- 取消按钮仍在状态卡片内；
- 点击后调用 `matcher.stop()` 或设置 `running_ranking_status.is_running = False`；
- 重置 `matching_status` 后调用 `st.rerun()`。

### 4.4 完成 UI 切换不变

- 粗召回完成后仍显示"继续 MGeo 精确匹配"按钮；
- 精排完成后仍显示"查看匹配结果"等按钮。

---

## 5. 边界情况处理
| 边界情况 | 处理方式 |
| --- | --- |
| 任务完成后 fragment 继续刷新 | fragment 只在 `matching_status['is_running'] == True` 时被调用；检测到 `is_running == False` 后立即 `st.rerun()` 切换到静态完成 UI。 |
| JS 秒表 iframe 重置 | 使用固定 key，HTML 内容只依赖 `start_time`；一次匹配过程中 `start_time` 不变，iframe 不会重新加载。 |
| 页面切换后秒表归零 | iframe 重新加载时会根据 session_state 中的 `start_time` 重新计算已运行时间，自动恢复。 |
| 粗召回没有逐条进度 | 粗召回阶段仍显示 `st.progress(0)` 和"正在执行批量召回"，与当前行为一致。 |
| 取消后仍看到 fragment | 取消逻辑设置 `is_running=False` 并重置状态；fragment 下一次自刷新时检测到完成，调用 `st.rerun()` 切换到初始 UI。 |
| 多个 fragment 实例 | 使用唯一 key 和函数封装，确保全局只有一个状态 fragment。 |
| 浏览器标签页休眠 | JS 定时器在后台标签页可能被节流；切回后会立即校正为真实已运行时间。 |

---

## 6. 风险评估
| 风险 | 可能性 | 影响 | 缓解措施 |
| --- | --- | --- | --- |
| `st.fragment(run_every=3)` 与 Streamlit 1.38 兼容性 | 低 | 高 | Streamlit 1.38 已支持 `st.fragment` 和 `run_every`；改造前可先用最小代码验证。 |
| JS 秒表 iframe 仍被 Streamlit 重新加载 | 中 | 中 | 使用固定 key 和稳定内容；如仍重置，可改用 CSS 动画进度条 + 3 秒同步的方案作为回退。 |
| 完成检测延迟 3 秒 | 低 | 低 | 3 秒延迟在用户可接受范围内；如需要更快，可降到 2 秒。 |
| 取消按钮在 fragment 内行为异常 | 低 | 高 | 取消逻辑保持原样；按钮仍由 Streamlit 原生处理，不在 iframe 内。 |
| 页面切换后状态恢复异常 | 低 | 高 | 不改动 session_state 结构；改造后手动测试页面切换场景。 |

---

## 7. 回退策略

如果在测试中发现意外问题，可以迅速回退：

1. 移除 `@st.fragment(run_every=3)` 装饰器；
2. 在 `_render_status_card` 调用后恢复 `time.sleep(1); st.rerun()`；
3. 移除 `_render_js_timer` 调用，恢复原来的 `format_time(elapsed)` 显示。

回退改动集中在 `pages/address_matching.py` 内，影响范围可控。

---

## 8. 测试计划

### 8.1 功能测试

1. 启动粗召回，观察状态卡片是否每 3 秒轻微更新一次；
2. 观察已运行时间是否稳定每秒递增，无跳变；
3. 粗召回完成后，是否及时切换到"粗召回完成 UI"；
4. 点击"继续 MGeo 精确匹配"，观察精排进度是否每 3 秒更新；
5. 精排完成后，是否及时切换到"MGeo 精确匹配完成 UI"。

### 8.2 兼容性测试

1. 后台线程仍在运行；
2. 状态卡片恢复正确；
3. 已运行时间恢复正确。
4. 已运行时间恢复正确。
5. 匹配执行中刷新浏览器页面，确认状态恢复。

### 8.3 取消测试

1. 粗召回执行中点击"取消匹配"，确认任务停止、UI 恢复初始状态；
2. MGeo 精排执行中点击"取消匹配"，确认任务停止、UI 恢复初始状态。

### 8.4 边界测试

1. 粗召回结果为空时，完成 UI 是否正确显示；
2. 快速连续点击"启动"按钮，是否不会重复启动任务；
3. 切换标签后启动匹配，状态卡片是否正确关联当前标签。

---

## 9. 实现范围

### 9.1 修改文件

- `pages/address_matching.py`：主改造文件
- `ui_theme.py`：追加进度条 CSS 过渡样式

### 9.2 不修改文件

- `matching/matcher.py`
- `matching/ranking.py`
- `model/mgeo_model.py`
- `database/vector_store.py`
- `database/data_loader.py`
- `app_common.py`
- `app.py`

---

## 10. 验收标准

1. 匹配执行期间，整个页面不再每秒整体刷新；
2. 状态卡片区域每 3 秒更新一次进度，更新过程平滑；
3. 已运行时间每秒更新，视觉上仍在原位置；
4. 任务完成后能及时切换到完成 UI；
5. 页面切换/刷新后状态正确恢复；
6. 取消按钮行为与原来一致；
7. 不引入新的 Python 依赖。
