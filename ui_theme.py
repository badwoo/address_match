"""
UI 设计令牌系统
===============

为中文地址语义匹配系统提供统一的设计令牌，包括颜色、间距、排版和组件样式。

设计理念：
    - 现代简约风格，采用深蓝灰主色调
    - 8px 间距网格系统
    - 语义化颜色令牌（成功/警告/错误/信息）
    - 低饱和度配色，专业沉稳
    - 无障碍对比度合规

使用方式：
    from ui_theme import Colors, Spacing, card_style, status_style
"""


class Colors:
    """语义化颜色令牌 - 现代简约风格"""

    # 主色调 - 深蓝灰（沉稳专业）
    PRIMARY = '#2563eb'           # 明亮蓝 - 主操作
    PRIMARY_DARK = '#1d4ed8'      # 深蓝 - hover状态
    PRIMARY_LIGHT = '#3b82f6'     # 浅蓝 - 次要强调
    PRIMARY_BG = '#eff6ff'        # 极浅蓝 - 背景

    # 辅助色
    SECONDARY = '#475569'         # 蓝灰 - 次要操作
    SECONDARY_DARK = '#334155'    # 深蓝灰 - hover
    SECONDARY_LIGHT = '#64748b'   # 浅蓝灰
    SECONDARY_BG = '#f1f5f9'      # 极浅灰蓝 - 背景

    # 语义状态色（确保 WCAG AA 对比度 >= 4.5:1）
    SUCCESS = '#059669'
    SUCCESS_BG = '#d1fae5'
    SUCCESS_BORDER = '#10b981'
    SUCCESS_LIGHT = '#34d399'

    WARNING = '#d97706'
    WARNING_BG = '#fef3c7'
    WARNING_BORDER = '#f59e0b'
    WARNING_LIGHT = '#fbbf24'

    ERROR = '#dc2626'
    ERROR_BG = '#fee2e2'
    ERROR_BORDER = '#ef4444'
    ERROR_LIGHT = '#f87171'

    INFO = '#2563eb'
    INFO_BG = '#dbeafe'
    INFO_BORDER = '#3b82f6'
    INFO_LIGHT = '#60a5fa'

    # 中性色 - 现代灰阶
    TEXT_PRIMARY = '#0f172a'      # 近黑 - 主标题
    TEXT_SECONDARY = '#475569'    # 深灰 - 副标题
    TEXT_MUTED = '#94a3b8'        # 浅灰 - 辅助文字
    TEXT_DISABLED = '#cbd5e1'     # 更浅灰 - 禁用

    SURFACE = '#ffffff'           # 纯白 - 卡片表面
    SURFACE_SECONDARY = '#f8fafc' # 极浅灰 - 次级表面
    SURFACE_TERTIARY = '#f1f5f9'  # 浅灰 - 第三级表面
    BORDER = '#e2e8f0'            # 边框色
    BORDER_LIGHT = '#f1f5f9'      # 浅色边框
    DIVIDER = '#cbd5e1'           # 分割线

    # 页面分区色（低饱和度，与主色调协调）
    SECTION_RECALL = '#f0fdf4'       # 淡绿 - 粗召回
    SECTION_MATCHING = '#fef9c3'     # 淡黄 - 匹配执行
    SECTION_RANKING = '#eff6ff'      # 淡蓝 - 精排完成
    SECTION_SIMILARITY = '#f5f3ff'   # 淡紫 - MGeo相似度

    # 侧边栏
    SIDEBAR_TITLE = '#1e293b'
    SIDEBAR_BG = '#f8fafc'
    SIDEBAR_ACTIVE = '#2563eb'
    SIDEBAR_ACTIVE_BG = '#eff6ff'


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
    FONT_FAMILY = '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, "Noto Sans SC", sans-serif'
    SIZE_H1 = '28px'
    SIZE_H2 = '22px'
    SIZE_H3 = '18px'
    SIZE_BODY = '14px'
    SIZE_SMALL = '12px'
    SIZE_CAPTION = '11px'

    WEIGHT_BOLD = '700'
    WEIGHT_SEMIBOLD = '600'
    WEIGHT_MEDIUM = '500'
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
    SM = '0 1px 2px rgba(0, 0, 0, 0.05)'
    CARD = '0 1px 3px rgba(0, 0, 0, 0.08), 0 1px 2px rgba(0, 0, 0, 0.06)'
    ELEVATED = '0 4px 6px rgba(0, 0, 0, 0.07), 0 2px 4px rgba(0, 0, 0, 0.06)'
    BUTTON = '0 1px 2px rgba(37, 99, 235, 0.15)'
    BUTTON_HOVER = '0 4px 12px rgba(37, 99, 235, 0.25)'


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
    /* ===== 基础重置 ===== */
    .stApp {{
        background-color: {Colors.SURFACE_SECONDARY};
    }}

    /* ===== 主标题 ===== */
    .app-title {{
        color: {Colors.TEXT_PRIMARY};
        font-size: {Typography.SIZE_H1};
        font-weight: {Typography.WEIGHT_BOLD};
        font-family: {Typography.FONT_FAMILY};
        padding: 10px 0 5px 0;
        line-height: 1.3;
        letter-spacing: -0.5px;
    }}

    /* ===== 侧边栏 ===== */
    [data-testid="stSidebar"] {{
        background-color: {Colors.SIDEBAR_BG} !important;
    }}

    .sidebar-title {{
        color: {Colors.SIDEBAR_TITLE};
        font-size: {Typography.SIZE_H2};
        font-weight: {Typography.WEIGHT_BOLD};
        font-family: {Typography.FONT_FAMILY};
        padding: 10px 0;
        text-align: center;
        letter-spacing: -0.3px;
    }}

    /* 侧边栏导航按钮 */
    [data-testid="stSidebar"] button {{
        border-radius: {Radius.SM} !important;
        font-weight: {Typography.WEIGHT_MEDIUM} !important;
        font-size: {Typography.SIZE_BODY} !important;
        transition: all 0.2s ease !important;
    }}

    [data-testid="stSidebar"] button[kind="primary"] {{
        background-color: {Colors.SIDEBAR_ACTIVE} !important;
        border-color: {Colors.SIDEBAR_ACTIVE} !important;
        color: white !important;
        font-weight: {Typography.WEIGHT_SEMIBOLD} !important;
    }}

    [data-testid="stSidebar"] button[kind="secondary"] {{
        background-color: transparent !important;
        border-color: transparent !important;
        color: {Colors.TEXT_SECONDARY} !important;
    }}

    [data-testid="stSidebar"] button[kind="secondary"]:hover {{
        background-color: {Colors.SIDEBAR_ACTIVE_BG} !important;
        color: {Colors.SIDEBAR_ACTIVE} !important;
    }}

    /* ===== 状态卡片 ===== */
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

    /* ===== 分区卡片 ===== */
    .section-card {{
        background-color: {Colors.SURFACE};
        padding: {Spacing.CARD_PADDING}px;
        border-radius: {Radius.MD};
        box-shadow: {Shadow.CARD};
        margin-bottom: {Spacing.LG}px;
        border: 1px solid {Colors.BORDER};
    }}

    /* ===== 分页导航 ===== */
    .pagination-info {{
        color: {Colors.TEXT_SECONDARY};
        font-size: {Typography.SIZE_SMALL};
        text-align: center;
        padding: 8px;
    }}

    /* ===== 页脚 ===== */
    .app-footer {{
        color: {Colors.TEXT_MUTED};
        font-size: {Typography.SIZE_CAPTION};
        text-align: center;
        padding-top: {Spacing.LG}px;
    }}

    /* ===== 统计卡片 ===== */
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

    /* ===== 按钮全局优化 ===== */
    button[kind="primary"] {{
        background-color: {Colors.PRIMARY} !important;
        border-color: {Colors.PRIMARY} !important;
        color: white !important;
        font-weight: {Typography.WEIGHT_MEDIUM} !important;
        border-radius: {Radius.SM} !important;
        box-shadow: {Shadow.BUTTON} !important;
        transition: all 0.2s ease !important;
    }}

    button[kind="primary"]:hover {{
        background-color: {Colors.PRIMARY_DARK} !important;
        border-color: {Colors.PRIMARY_DARK} !important;
        box-shadow: {Shadow.BUTTON_HOVER} !important;
        transform: translateY(-1px);
    }}

    button[kind="primary"]:active {{
        transform: translateY(0);
        box-shadow: {Shadow.BUTTON} !important;
    }}

    button[kind="secondary"] {{
        background-color: {Colors.SURFACE} !important;
        border-color: {Colors.BORDER} !important;
        color: {Colors.TEXT_SECONDARY} !important;
        font-weight: {Typography.WEIGHT_MEDIUM} !important;
        border-radius: {Radius.SM} !important;
        transition: all 0.2s ease !important;
    }}

    button[kind="secondary"]:hover {{
        background-color: {Colors.SURFACE_SECONDARY} !important;
        border-color: {Colors.TEXT_MUTED} !important;
        color: {Colors.TEXT_PRIMARY} !important;
    }}

    /* ===== 输入框优化 ===== */
    .stTextInput input, .stNumberInput input, .stSelectbox select {{
        border-radius: {Radius.SM} !important;
        border-color: {Colors.BORDER} !important;
        transition: border-color 0.2s ease, box-shadow 0.2s ease !important;
    }}

    .stTextInput input:focus, .stNumberInput input:focus {{
        border-color: {Colors.PRIMARY} !important;
        box-shadow: 0 0 0 3px {Colors.PRIMARY_BG} !important;
    }}

    /* ===== 分割线优化 ===== */
    hr {{
        border-color: {Colors.BORDER} !important;
        margin: {Spacing.LG}px 0 !important;
    }}

    /* ===== 信息提示框优化 ===== */
    .stAlert {{
        border-radius: {Radius.MD} !important;
        border-left-width: 4px !important;
    }}

    /* ===== 进度条优化 ===== */
    .stProgress > div > div {{
        background-color: {Colors.PRIMARY} !important;
        border-radius: {Radius.FULL} !important;
    }}

    /* ===== 标签页优化 ===== */
    .stTabs [data-baseweb="tab-list"] {{
        gap: 4px;
    }}

    .stTabs [data-baseweb="tab"] {{
        border-radius: {Radius.SM} {Radius.SM} 0 0 !important;
        padding: 8px 16px !important;
        font-weight: {Typography.WEIGHT_MEDIUM} !important;
    }}

    .stTabs [aria-selected="true"] {{
        background-color: {Colors.PRIMARY_BG} !important;
        color: {Colors.PRIMARY} !important;
    }}

    /* ===== 紧凑按钮（非全宽） ===== */
    .compact-btn-container {{
        display: flex;
        gap: 8px;
    }}

    /* ===== 翻页工具栏垂直对齐 ===== */
    [data-testid="stVerticalBlockBorderWrapper"] [data-testid="stWidgetLabel"] {{
        margin-bottom: 0 !important;
    }}
    [data-testid="stVerticalBlockBorderWrapper"] [data-testid="stWidgetLabel"] p {{
        margin-top: 0 !important;
        margin-bottom: 2px !important;
        font-size: 0.8rem !important;
        line-height: 1.2 !important;
    }}

    /* ===== 表格优化 ===== */
    .dataframe {{
        border-radius: {Radius.MD} !important;
        border: 1px solid {Colors.BORDER} !important;
        overflow: hidden;
    }}

    .dataframe th {{
        background-color: {Colors.SURFACE_SECONDARY} !important;
        color: {Colors.TEXT_PRIMARY} !important;
        font-weight: {Typography.WEIGHT_SEMIBOLD} !important;
        border-bottom: 2px solid {Colors.BORDER} !important;
    }}

    .dataframe td {{
        border-bottom: 1px solid {Colors.BORDER_LIGHT} !important;
    }}

    .dataframe tr:hover td {{
        background-color: {Colors.PRIMARY_BG} !important;
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
