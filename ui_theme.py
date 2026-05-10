"""
UI 设计令牌系统
===============

为中文地址语义匹配系统提供统一的设计令牌，包括颜色、间距、排版和组件样式。

设计理念：
    - 专业数据工具风格，蓝色主色调
    - 8px 间距网格系统
    - 语义化颜色令牌（成功/警告/错误/信息）
    - 无障碍对比度合规

使用方式：
    from ui_theme import Colors, Spacing, card_style, status_style
"""


class Colors:
    """语义化颜色令牌"""

    # 主色调 - 专业蓝
    PRIMARY = '#1e40af'
    PRIMARY_LIGHT = '#3b82f6'
    PRIMARY_BG = '#eff6ff'

    # 语义状态色（确保 WCAG AA 对比度 >= 4.5:1）
    SUCCESS = '#166534'
    SUCCESS_BG = '#dcfce7'
    SUCCESS_BORDER = '#22c55e'

    WARNING = '#854d0e'
    WARNING_BG = '#fef9c3'
    WARNING_BORDER = '#eab308'

    ERROR = '#991b1b'
    ERROR_BG = '#fee2e2'
    ERROR_BORDER = '#ef4444'

    INFO = '#1e40af'
    INFO_BG = '#dbeafe'
    INFO_BORDER = '#3b82f6'

    # 中性色
    TEXT_PRIMARY = '#1e293b'
    TEXT_SECONDARY = '#64748b'
    TEXT_MUTED = '#94a3b8'

    SURFACE = '#ffffff'
    SURFACE_SECONDARY = '#f8fafc'
    BORDER = '#e2e8f0'
    DIVIDER = '#cbd5e1'

    # 页面分区色（匹配系统原有风格）
    SECTION_RECALL = '#f0fdf4'       # 绿 - 粗召回
    SECTION_MATCHING = '#fef9c3'     # 黄 - 匹配执行
    SECTION_RANKING = '#dbeafe'      # 蓝 - 精排完成
    SECTION_SIMILARITY = '#ede9fe'   # 紫 - MGeo相似度

    # 侧边栏
    SIDEBAR_TITLE = '#1e40af'
    SIDEBAR_BG = '#f8fafc'


class Spacing:
    """8px 基准间距系统"""
    XS = 4
    SM = 8
    MD = 16
    LG = 24
    XL = 32
    XXL = 48

    # 卡片内边距
    CARD_PADDING = 20
    # 分区间距
    SECTION_GAP = 24


class Typography:
    """排版令牌"""
    FONT_FAMILY = '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif'
    SIZE_H1 = '28px'
    SIZE_H2 = '22px'
    SIZE_H3 = '18px'
    SIZE_BODY = '14px'       # Streamlit 默认
    SIZE_SMALL = '12px'
    SIZE_CAPTION = '11px'

    WEIGHT_BOLD = '700'
    WEIGHT_SEMIBOLD = '600'
    WEIGHT_NORMAL = '400'

    LINE_HEIGHT = '1.6'


class Radius:
    """圆角令牌"""
    SM = '6px'
    MD = '10px'
    LG = '14px'
    FULL = '9999px'


class Shadow:
    """阴影令牌"""
    CARD = '0 1px 3px rgba(0, 0, 0, 0.08), 0 1px 2px rgba(0, 0, 0, 0.06)'
    ELEVATED = '0 4px 6px rgba(0, 0, 0, 0.07), 0 2px 4px rgba(0, 0, 0, 0.06)'


# ==================== 可复用的 CSS 样式组件 ====================

def card_style(bg_color=None, border_color=None, with_shadow=True):
    """
    生成卡片容器 CSS。

    Args:
        bg_color: 背景色，默认白色
        border_color: 左边框颜色（用于语义提示），默认无
        with_shadow: 是否使用阴影
    """
    bg = bg_color or Colors.SURFACE
    styles = [
        f'background-color: {bg}',
        f'padding: {Spacing.CARD_PADDING}px',
        f'border-radius: {Radius.MD}',
        f'margin-bottom: {Spacing.MD}px',
    ]
    if border_color:
        styles.insert(0, f'border-left: 4px solid {border_color}')
    if with_shadow:
        styles.append(f'box-shadow: {Shadow.CARD}')
    return '; '.join(styles)


def status_container_style(status_type='info'):
    """
    生成语义状态容器样式。

    Args:
        status_type: 'info', 'success', 'warning', 'error'
    """
    color_map = {
        'info': (Colors.INFO_BG, Colors.INFO_BORDER),
        'success': (Colors.SUCCESS_BG, Colors.SUCCESS_BORDER),
        'warning': (Colors.WARNING_BG, Colors.WARNING_BORDER),
        'error': (Colors.ERROR_BG, Colors.ERROR_BORDER),
    }
    bg, border = color_map.get(status_type, color_map['info'])
    return f'background-color: {bg}; padding: {Spacing.CARD_PADDING}px; border-radius: {Radius.MD}; border-left: 4px solid {border}; margin-bottom: {Spacing.MD}px;'


# ==================== 通用 CSS 注入 ====================

def inject_global_styles():
    """
    注入全局 Streamlit 自定义样式。
    应在 main() 开头调用一次。
    """
    import streamlit as st
    css = f"""
    <style>
    /* 主标题 */
    .app-title {{
        color: {Colors.PRIMARY};
        font-size: {Typography.SIZE_H1};
        font-weight: {Typography.WEIGHT_BOLD};
        font-family: {Typography.FONT_FAMILY};
        padding: 10px 0 5px 0;
        line-height: 1.3;
    }}

    /* 侧边栏标题 */
    .sidebar-title {{
        color: {Colors.SIDEBAR_TITLE};
        font-size: {Typography.SIZE_H2};
        font-weight: {Typography.WEIGHT_BOLD};
        font-family: {Typography.FONT_FAMILY};
        padding: 10px 0;
        text-align: center;
    }}

    /* 状态卡片 */
    .status-card {{
        padding: {Spacing.CARD_PADDING}px;
        border-radius: {Radius.MD};
        margin-bottom: {Spacing.MD}px;
    }}

    .status-card-info {{
        background-color: {Colors.INFO_BG};
        border-left: 4px solid {Colors.INFO_BORDER};
    }}

    .status-card-success {{
        background-color: {Colors.SUCCESS_BG};
        border-left: 4px solid {Colors.SUCCESS_BORDER};
    }}

    .status-card-warning {{
        background-color: {Colors.WARNING_BG};
        border-left: 4px solid {Colors.WARNING_BORDER};
    }}

    .status-card-error {{
        background-color: {Colors.ERROR_BG};
        border-left: 4px solid {Colors.ERROR_BORDER};
    }}

    /* 分区卡片 */
    .section-card {{
        background-color: {Colors.SURFACE};
        padding: {Spacing.CARD_PADDING}px;
        border-radius: {Radius.MD};
        box-shadow: {Shadow.CARD};
        margin-bottom: {Spacing.LG}px;
    }}

    /* 分页导航 */
    .pagination-info {{
        color: {Colors.TEXT_SECONDARY};
        font-size: {Typography.SIZE_SMALL};
        text-align: center;
        padding: 8px;
    }}

    /* 页脚 */
    .app-footer {{
        color: {Colors.TEXT_MUTED};
        font-size: {Typography.SIZE_CAPTION};
        text-align: center;
        padding-top: {Spacing.LG}px;
    }}

    /* 统计卡片 */
    .metric-label {{
        color: {Colors.TEXT_SECONDARY};
        font-size: {Typography.SIZE_SMALL};
        font-weight: {Typography.WEIGHT_NORMAL};
    }}

    .metric-value {{
        color: {Colors.TEXT_PRIMARY};
        font-size: {Typography.SIZE_H2};
        font-weight: {Typography.WEIGHT_BOLD};
    }}

    /* 覆盖 Streamlit 主按钮颜色：红 → 蓝 */
    button[kind="primary"] {{
        background-color: {Colors.PRIMARY_LIGHT} !important;
        border-color: {Colors.PRIMARY_LIGHT} !important;
        color: white !important;
    }}
    button[kind="primary"]:hover {{
        background-color: {Colors.PRIMARY} !important;
        border-color: {Colors.PRIMARY} !important;
    }}

    /* 侧边栏导航激活按钮 */
    [data-testid="stSidebar"] button[kind="primary"] {{
        background-color: {Colors.PRIMARY} !important;
        border-color: {Colors.PRIMARY} !important;
        font-weight: {Typography.WEIGHT_SEMIBOLD};
    }}

    /* 紧凑按钮（非全宽） */
    .compact-btn-container {{
        display: flex;
        gap: 8px;
    }}
    </style>
    """
    st.markdown(css, unsafe_allow_html=True)


# ==================== 标签文本常量（替代 emoji） ====================

class Icons:
    """语义标签（替代 emoji 作为界面元素）"""
    DATABASE = '&#9881;'        # ⚙ → 齿轮 Unicode 实体
    VECTOR = '&#9776;'          # 数据表符号
    MATCHING = '&#128269;'      # 搜索
    RESULTS = '&#128203;'       # 剪贴板
    LOGS = '&#128221;'          # 文档

    SUCCESS = '&#10003;'        # ✓
    ERROR = '&#10007;'          # ✗
    WARNING = '&#9888;'         # ⚠
    INFO = '&#8505;'            # ℹ

    GPU = '&#9889;'             # GPU = 闪电
    CPU = '&#9000;'             # CPU = 芯片

    START = '&#9654;'           # ▶
    STOP = '&#9632;'            # ■
    REFRESH = '&#8635;'         # ↻
    BACK = '&#8617;'            # ↩
