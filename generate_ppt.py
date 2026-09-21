"""
生成项目介绍PPT - 中文地址语义匹配系统
Nature风格：森林绿 + 大地色系，自然有机感
"""
from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE
import os

# ==================== Nature 色彩系统 ====================
# 森林绿主色调，搭配大地暖色，营造自然、沉稳的专业感
NATURE = {
    'forest_dark':  RGBColor(0x1B, 0x43, 0x32),   # 深森林绿 - 标题
    'forest_mid':   RGBColor(0x2D, 0x6A, 0x4F),   # 中森林绿 - 主色
    'sage':         RGBColor(0x52, 0xB7, 0x88),    # 鼠尾草绿 - 辅助
    'mint':         RGBColor(0xD8, 0xF3, 0xDC),    # 薄荷绿 - 浅背景
    'cream':        RGBColor(0xFA, 0xF9, 0xF6),    # 奶油白 - 主背景
    'earth':        RGBColor(0x8B, 0x69, 0x14),    # 大地棕 - 暖色点缀
    'terracotta':   RGBColor(0xC8, 0x79, 0x5C),    # 陶土橙 - 强调
    'stone':        RGBColor(0x6B, 0x70, 0x5C),    # 岩石灰 - 正文
    'dark':         RGBColor(0x1E, 0x1E, 0x1E),    # 深黑 - 正文
    'white':        RGBColor(0xFF, 0xFF, 0xFF),
    'leaf':         RGBColor(0x40, 0x9C, 0x61),    # 叶绿 - 图标色
    'sand':         RGBColor(0xF0, 0xEA, 0xD6),    # 沙色 - 卡片背景
    'bark':         RGBColor(0x3E, 0x27, 0x23),    # 树皮棕 - 强调文字
}

prs = Presentation()
prs.slide_width = Inches(13.333)   # 16:9 宽屏
prs.slide_height = Inches(7.5)

# ==================== 辅助函数 ====================

def add_bg(slide, color=NATURE['cream']):
    """设置幻灯片纯色背景"""
    bg = slide.background
    fill = bg.fill
    fill.solid()
    fill.fore_color.rgb = color

def add_rect(slide, left, top, width, height, color, opacity=None):
    """添加矩形色块"""
    shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, left, top, width, height)
    shape.fill.solid()
    shape.fill.fore_color.rgb = color
    shape.line.fill.background()
    if opacity is not None:
        shape.fill.fore_color.brightness = opacity
    return shape

def add_rounded_rect(slide, left, top, width, height, color):
    """添加圆角矩形"""
    shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, left, top, width, height)
    shape.fill.solid()
    shape.fill.fore_color.rgb = color
    shape.line.fill.background()
    return shape

def add_text_box(slide, left, top, width, height, text, font_size=18, color=None, bold=False, alignment=PP_ALIGN.LEFT, font_name='Microsoft YaHei'):
    """添加文本框"""
    txBox = slide.shapes.add_textbox(left, top, width, height)
    tf = txBox.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.text = text
    p.font.size = Pt(font_size)
    p.font.color.rgb = color or NATURE['dark']
    p.font.bold = bold
    p.font.name = font_name
    p.alignment = alignment
    return txBox

def add_multiline_box(slide, left, top, width, height, lines, default_size=16, default_color=None, line_spacing=1.5):
    """添加多行文本框，lines = [(text, size, color, bold), ...]"""
    txBox = slide.shapes.add_textbox(left, top, width, height)
    tf = txBox.text_frame
    tf.word_wrap = True
    for i, line_data in enumerate(lines):
        if isinstance(line_data, str):
            text, size, color, bold = line_data, default_size, default_color, False
        else:
            text = line_data[0]
            size = line_data[1] if len(line_data) > 1 else default_size
            color = line_data[2] if len(line_data) > 2 else default_color
            bold = line_data[3] if len(line_data) > 3 else False
        if i == 0:
            p = tf.paragraphs[0]
        else:
            p = tf.add_paragraph()
        p.text = text
        p.font.size = Pt(size)
        p.font.color.rgb = color or NATURE['dark']
        p.font.bold = bold
        p.font.name = 'Microsoft YaHei'
        p.space_after = Pt(size * (line_spacing - 1))
    return txBox

def add_left_accent_bar(slide, top, height, color=NATURE['forest_mid']):
    """添加左侧装饰条"""
    return add_rect(slide, Inches(0), top, Inches(0.08), height, color)

def add_bottom_bar(slide, color=NATURE['forest_mid']):
    """底部装饰条"""
    add_rect(slide, Inches(0), Inches(7.2), Inches(13.333), Inches(0.04), color)

def add_page_number(slide, num, total):
    """页码"""
    add_text_box(slide, Inches(12.3), Inches(7.1), Inches(0.8), Inches(0.3),
                 f'{num}/{total}', font_size=10, color=NATURE['stone'], alignment=PP_ALIGN.RIGHT)

def add_section_title(slide, title, subtitle=None):
    """统一的章节标题样式"""
    add_bottom_bar(slide)
    # 左上角森林绿装饰条
    add_rect(slide, Inches(0.6), Inches(0.6), Inches(0.06), Inches(0.6), NATURE['forest_mid'])
    add_text_box(slide, Inches(0.9), Inches(0.5), Inches(10), Inches(0.7),
                 title, font_size=32, color=NATURE['forest_dark'], bold=True)
    if subtitle:
        add_text_box(slide, Inches(0.9), Inches(1.1), Inches(10), Inches(0.4),
                     subtitle, font_size=14, color=NATURE['stone'])

def add_card(slide, left, top, width, height, title, content_lines, title_color=None, bg_color=None):
    """添加卡片组件"""
    # 卡片背景
    card = add_rounded_rect(slide, left, top, width, height, bg_color or NATURE['white'])
    # 阴影效果 - 用底部深色条模拟
    add_rect(slide, left + Inches(0.02), top + height, width - Inches(0.04), Inches(0.03), NATURE['mint'])
    # 顶部色条
    add_rect(slide, left, top, width, Inches(0.05), title_color or NATURE['forest_mid'])
    # 标题
    add_text_box(slide, left + Inches(0.25), top + Inches(0.2), width - Inches(0.5), Inches(0.4),
                 title, font_size=16, color=title_color or NATURE['forest_dark'], bold=True)
    # 内容
    add_multiline_box(slide, left + Inches(0.25), top + Inches(0.65), width - Inches(0.5),
                      height - Inches(0.85), content_lines, default_size=12, default_color=NATURE['stone'])


TOTAL_SLIDES = 12

# ==================== Slide 1: 封面 ====================
slide = prs.slides.add_slide(prs.slide_layouts[6])  # 空白布局
add_bg(slide, NATURE['cream'])

# 顶部森林绿大色块
add_rect(slide, Inches(0), Inches(0), Inches(13.333), Inches(3.2), NATURE['forest_dark'])
# 覆盖渐变效果 - 中层绿色
add_rect(slide, Inches(0), Inches(2.4), Inches(13.333), Inches(1.2), NATURE['forest_mid'])
# 装饰叶片色线
add_rect(slide, Inches(2), Inches(3.5), Inches(9.333), Inches(0.04), NATURE['sage'])

# 主标题
add_text_box(slide, Inches(1.5), Inches(0.8), Inches(10.333), Inches(1.0),
             '中文地址语义匹配系统', font_size=48, color=NATURE['white'], bold=True, alignment=PP_ALIGN.CENTER)
# 副标题
add_text_box(slide, Inches(1.5), Inches(1.8), Inches(10.333), Inches(0.6),
             'Address Semantic Matching System', font_size=22, color=NATURE['mint'], alignment=PP_ALIGN.CENTER)

# 项目定位
add_text_box(slide, Inches(1.5), Inches(4.0), Inches(10.333), Inches(0.6),
             '基于阿里 MGeo 模型的智能地址匹配解决方案', font_size=20, color=NATURE['forest_dark'], bold=True, alignment=PP_ALIGN.CENTER)
add_text_box(slide, Inches(1.5), Inches(4.6), Inches(10.333), Inches(0.8),
             '150万 企业数据 × 1300万 标准地址库 ｜ 两阶段匹配架构 ｜ Streamlit 交互式应用',
             font_size=16, color=NATURE['stone'], alignment=PP_ALIGN.CENTER)

# 底部信息
add_rect(slide, Inches(0), Inches(7.0), Inches(13.333), Inches(0.5), NATURE['forest_dark'])
add_text_box(slide, Inches(1.5), Inches(7.05), Inches(10.333), Inches(0.4),
             '技术栈：Python · PostgreSQL + pgvector · Streamlit · 阿里 MGeo ｜ 2026',
             font_size=12, color=NATURE['mint'], alignment=PP_ALIGN.CENTER)

# 装饰叶片图标 - 用几何圆形模拟
for i, (x, y, r, c) in enumerate([
    (Inches(11.5), Inches(5.5), Inches(0.3), NATURE['sage']),
    (Inches(11.0), Inches(5.8), Inches(0.2), NATURE['mint']),
    (Inches(1.5), Inches(5.5), Inches(0.25), NATURE['sage']),
    (Inches(1.0), Inches(5.8), Inches(0.15), NATURE['mint']),
]):
    circle = slide.shapes.add_shape(MSO_SHAPE.OVAL, x, y, r, r)
    circle.fill.solid()
    circle.fill.fore_color.rgb = c
    circle.line.fill.background()

add_page_number(slide, 1, TOTAL_SLIDES)

# ==================== Slide 2: 目录 ====================
slide = prs.slides.add_slide(prs.slide_layouts[6])
add_bg(slide, NATURE['cream'])
add_section_title(slide, '目录', 'CONTENTS')

agenda_items = [
    ('01', '项目概述', '项目目标、核心指标、业务价值'),
    ('02', '技术架构', '技术栈总览、系统分层设计'),
    ('03', '两阶段匹配流程', '粗召回 + 精排 核心算法'),
    ('04', '粗召回阶段', 'MGeo Backbone 向量化 + pgvector 检索'),
    ('05', '精排阶段', 'MGeo Entity Alignment 三分类预测'),
    ('06', '模型加载策略', '多路径回退、兼容性处理'),
    ('07', '数据库设计', 'PostgreSQL + pgvector 表结构'),
    ('08', '核心功能模块', 'Streamlit 应用功能一览'),
    ('09', '关键技术优化', '性能优化与工程实践'),
    ('10', '项目总结', '技术亮点与未来展望'),
]

for i, (num, title, desc) in enumerate(agenda_items):
    col = i % 2
    row = i // 2
    x = Inches(1.0 + col * 6.2)
    y = Inches(2.0 + row * 1.0)

    # 编号圆圈
    circle = slide.shapes.add_shape(MSO_SHAPE.OVAL, x, y + Inches(0.05), Inches(0.45), Inches(0.45))
    circle.fill.solid()
    circle.fill.fore_color.rgb = NATURE['forest_mid'] if col == 0 else NATURE['sage']
    circle.line.fill.background()
    tf = circle.text_frame
    tf.word_wrap = False
    p = tf.paragraphs[0]
    p.text = num
    p.font.size = Pt(14)
    p.font.color.rgb = NATURE['white']
    p.font.bold = True
    p.font.name = 'Microsoft YaHei'
    p.alignment = PP_ALIGN.CENTER

    add_text_box(slide, x + Inches(0.65), y, Inches(4.5), Inches(0.35),
                 title, font_size=18, color=NATURE['forest_dark'], bold=True)
    add_text_box(slide, x + Inches(0.65), y + Inches(0.35), Inches(4.5), Inches(0.3),
                 desc, font_size=12, color=NATURE['stone'])

add_page_number(slide, 2, TOTAL_SLIDES)

# ==================== Slide 3: 项目概述 ====================
slide = prs.slides.add_slide(prs.slide_layouts[6])
add_bg(slide, NATURE['cream'])
add_section_title(slide, '项目概述', 'PROJECT OVERVIEW')

# 左侧大数字
add_text_box(slide, Inches(0.9), Inches(2.0), Inches(3), Inches(0.6),
             '150万+', font_size=48, color=NATURE['forest_mid'], bold=True)
add_text_box(slide, Inches(0.9), Inches(2.6), Inches(3), Inches(0.3),
             '企业数据量', font_size=14, color=NATURE['stone'])
add_text_box(slide, Inches(0.9), Inches(3.2), Inches(3), Inches(0.6),
             '1300万+', font_size=48, color=NATURE['sage'], bold=True)
add_text_box(slide, Inches(0.9), Inches(3.8), Inches(3), Inches(0.3),
             '标准地址库', font_size=14, color=NATURE['stone'])
add_text_box(slide, Inches(0.9), Inches(4.4), Inches(3), Inches(0.6),
             '768维', font_size=48, color=NATURE['terracotta'], bold=True)
add_text_box(slide, Inches(0.9), Inches(5.0), Inches(3), Inches(0.3),
             '地址向量维度', font_size=14, color=NATURE['stone'])

# 右侧卡片
add_card(slide, Inches(4.5), Inches(2.0), Inches(8.0), Inches(1.6),
         '🎯 核心目标', [
             ('实现大规模企业地址数据与标准地址库的智能语义匹配，', 13, NATURE['stone']),
             ('自动获取标准地址的房号信息，提升地址数据质量和标准化水平。', 13, NATURE['stone']),
         ], title_color=NATURE['forest_mid'])

add_card(slide, Inches(4.5), Inches(3.9), Inches(3.8), Inches(1.8),
         '🏗️ 核心架构', [
             ('• 粗召回：向量相似度快速检索', 13, NATURE['stone']),
             ('• 精排：MGeo 模型精准匹配', 13, NATURE['stone']),
             ('• 两阶段分层，兼顾效率与精度', 13, NATURE['stone']),
         ], title_color=NATURE['sage'])

add_card(slide, Inches(8.6), Inches(3.9), Inches(3.9), Inches(1.8),
         '💡 技术亮点', [
             ('• pgvector 向量数据库检索', 13, NATURE['stone']),
             ('• 阿里 MGeo 中文地址预训练模型', 13, NATURE['stone']),
             ('• 多路径模型加载与设备自适应', 13, NATURE['stone']),
         ], title_color=NATURE['terracotta'])

add_page_number(slide, 3, TOTAL_SLIDES)

# ==================== Slide 4: 技术架构 ====================
slide = prs.slides.add_slide(prs.slide_layouts[6])
add_bg(slide, NATURE['cream'])
add_section_title(slide, '技术架构', 'TECHNICAL ARCHITECTURE')

# 分层架构图
layers = [
    ('Streamlit UI 层', '数据库配置 ｜ 向量预处理 ｜ 地址匹配 ｜ 结果管理 ｜ 系统日志', NATURE['forest_dark'], Inches(2.0)),
    ('匹配层 matching/', 'AddressMatcher 两阶段编排 ｜ MGeoSimilarityMatcher 独立匹配 ｜ RankingEngine 精排引擎', NATURE['forest_mid'], Inches(3.2)),
    ('模型层 model/', 'AddressEmbedder 粗召回向量化 (768维) ｜ MGeoModel 精排三分类预测 (3标签)', NATURE['sage'], Inches(4.4)),
    ('数据库层 database/', 'DBConnection 连接管理 ｜ VectorStore pgvector检索 ｜ DataLoader 批量加载 ｜ TagManager 标签管理', RGBColor(0x6B, 0x90, 0x80), Inches(5.6)),
]

for title, desc, color, y in layers:
    shape = add_rounded_rect(slide, Inches(1.5), y, Inches(10.3), Inches(1.0), color)
    tf = shape.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.text = title
    p.font.size = Pt(18)
    p.font.color.rgb = NATURE['white']
    p.font.bold = True
    p.font.name = 'Microsoft YaHei'
    p.alignment = PP_ALIGN.CENTER
    p2 = tf.add_paragraph()
    p2.text = desc
    p2.font.size = Pt(11)
    p2.font.color.rgb = NATURE['mint']
    p2.font.name = 'Microsoft YaHei'
    p2.alignment = PP_ALIGN.CENTER

# 箭头连接
for y in [Inches(3.05), Inches(4.25), Inches(5.45)]:
    arrow = slide.shapes.add_shape(MSO_SHAPE.DOWN_ARROW, Inches(6.4), y, Inches(0.5), Inches(0.25))
    arrow.fill.solid()
    arrow.fill.fore_color.rgb = NATURE['earth']
    arrow.line.fill.background()

# 底部技术栈
add_text_box(slide, Inches(1.5), Inches(6.9), Inches(10.3), Inches(0.3),
             '核心技术：Python · PostgreSQL + pgvector · Streamlit · PyTorch · ModelScope · HuggingFace Transformers',
             font_size=11, color=NATURE['stone'], alignment=PP_ALIGN.CENTER)

add_page_number(slide, 4, TOTAL_SLIDES)

# ==================== Slide 5: 两阶段匹配流程 ====================
slide = prs.slides.add_slide(prs.slide_layouts[6])
add_bg(slide, NATURE['cream'])
add_section_title(slide, '两阶段匹配流程', 'TWO-STAGE MATCHING PIPELINE')

# 流程图
# 阶段1
add_rounded_rect(slide, Inches(0.8), Inches(2.5), Inches(5.5), Inches(3.8), NATURE['mint'])
add_text_box(slide, Inches(1.1), Inches(2.7), Inches(5.0), Inches(0.4),
             '阶段一：粗召回', font_size=20, color=NATURE['forest_dark'], bold=True)

stage1_items = [
    '📊 企业地址数据输入',
    '🧠 MGeo Backbone 编码为 768维向量',
    '🔍 pgvector LATERAL JOIN 检索',
    '📋 返回 Top-50 相似候选地址',
    '⚡ SIMILARITY_THRESHOLD ≥ 0.8 过滤',
]
add_multiline_box(slide, Inches(1.3), Inches(3.3), Inches(4.8), Inches(2.8),
                  [(item, 13, NATURE['stone']) for item in stage1_items])

# 箭头
arrow = slide.shapes.add_shape(MSO_SHAPE.RIGHT_ARROW, Inches(6.4), Inches(4.1), Inches(0.6), Inches(0.4))
arrow.fill.solid()
arrow.fill.fore_color.rgb = NATURE['earth']
arrow.line.fill.background()

# 阶段2
add_rounded_rect(slide, Inches(7.1), Inches(2.5), Inches(5.5), Inches(3.8), NATURE['sand'])
add_text_box(slide, Inches(7.4), Inches(2.7), Inches(5.0), Inches(0.4),
             '阶段二：精排', font_size=20, color=NATURE['bark'], bold=True)

stage2_items = [
    '🤖 MGeo Entity Alignment 模型加载',
    '🔬 候选地址对两两比较',
    '📈 输出三分类概率 (exact/partial/not)',
    '🏆 按 exact_match 降序排序',
    '✅ 确定最终匹配状态',
]
add_multiline_box(slide, Inches(7.6), Inches(3.3), Inches(4.8), Inches(2.8),
                  [(item, 13, NATURE['stone']) for item in stage2_items])

# 底部关键参数
add_rect(slide, Inches(0.8), Inches(6.6), Inches(11.8), Inches(0.45), NATURE['forest_dark'])
add_text_box(slide, Inches(1.0), Inches(6.65), Inches(11.4), Inches(0.35),
             '关键参数：SIMILARITY_THRESHOLD = 0.8 ｜ RECALL_TOP_N = 50 ｜ BATCH_SIZE_MODEL = 128 ｜ 双重阈值过滤（SQL + Python）',
             font_size=12, color=NATURE['mint'], alignment=PP_ALIGN.CENTER)

add_page_number(slide, 5, TOTAL_SLIDES)

# ==================== Slide 6: 粗召回阶段详解 ====================
slide = prs.slides.add_slide(prs.slide_layouts[6])
add_bg(slide, NATURE['cream'])
add_section_title(slide, '粗召回阶段详解', 'STAGE 1: COARSE RECALL')

add_card(slide, Inches(0.8), Inches(2.0), Inches(5.8), Inches(2.2),
         '🧠 MGeo Backbone 向量化', [
             ('模型：iic/mgeo_backbone_chinese_base', 13, NATURE['stone']),
             ('输出：768维语义向量', 13, NATURE['stone']),
             ('批处理：BATCH_SIZE_EMBEDDING = 256 (GPU)', 13, NATURE['stone']),
             ('设备自适应：GPU 自动检测与回退', 13, NATURE['stone']),
         ], title_color=NATURE['forest_mid'])

add_card(slide, Inches(7.0), Inches(2.0), Inches(5.8), Inches(2.2),
         '🗄️ pgvector 向量检索', [
             ('扩展：PostgreSQL pgvector 插件', 13, NATURE['stone']),
             ('索引：IVFFlat 向量索引加速检索', 13, NATURE['stone']),
             ('方法：LATERAL JOIN 批量检索', 13, NATURE['stone']),
             ('过滤：cosine similarity >= threshold', 13, NATURE['stone']),
         ], title_color=NATURE['sage'])

add_card(slide, Inches(0.8), Inches(4.5), Inches(5.8), Inches(2.2),
         '📋 召回结果存储', [
             ('存储表：recall_results', 13, NATURE['stone']),
             ('字段：企业ID、标准地址ID、相似度分数', 13, NATURE['stone']),
             ('每个企业召回 Top-N (默认50) 候选', 13, NATURE['stone']),
             ('支持自定义向量表名和多Schema隔离', 13, NATURE['stone']),
         ], title_color=NATURE['earth'])

add_card(slide, Inches(7.0), Inches(4.5), Inches(5.8), Inches(2.2),
         '⚡ 性能特性', [
             ('• 批量向量化：1000条/批次入库', 13, NATURE['stone']),
             ('• IVFFlat 索引加速相似度计算', 13, NATURE['stone']),
             ('• 支持多表并行向量化处理', 13, NATURE['stone']),
             ('• 向量表按创建时间倒序管理', 13, NATURE['stone']),
         ], title_color=NATURE['terracotta'])

add_page_number(slide, 6, TOTAL_SLIDES)

# ==================== Slide 7: 精排阶段详解 ====================
slide = prs.slides.add_slide(prs.slide_layouts[6])
add_bg(slide, NATURE['cream'])
add_section_title(slide, '精排阶段详解', 'STAGE 2: FINE RANKING')

add_card(slide, Inches(0.8), Inches(2.0), Inches(5.8), Inches(2.0),
         '🤖 MGeo 精排模型', [
             ('模型：iic/mgeo_geographic_entity_alignment_chinese_base', 13, NATURE['stone']),
             ('架构：BERT-based 序列分类模型', 13, NATURE['stone']),
             ('输出：3标签概率 (exact_match, partial_match, not_match)', 13, NATURE['stone']),
             ('约束：必须指定 num_labels=3，否则维度不匹配', 13, NATURE['terracotta'], True),
         ], title_color=NATURE['forest_mid'])

add_card(slide, Inches(7.0), Inches(2.0), Inches(5.8), Inches(2.0),
         '📊 排序与决策逻辑', [
             ('主排序：exact_match 概率降序', 13, NATURE['stone']),
             ('次排序：not_match 概率升序', 13, NATURE['stone']),
             ('匹配判定：取三个概率中最大值', 13, NATURE['stone']),
             ('无候选 → 直接判定为不匹配', 13, NATURE['stone']),
         ], title_color=NATURE['sage'])

add_card(slide, Inches(0.8), Inches(4.3), Inches(5.8), Inches(2.2),
         '🏷️ 标签映射关系', [
             ('索引 0 → exact_match (精确匹配概率)', 13, NATURE['forest_mid'], True),
             ('索引 1 → not_match (不匹配概率)', 13, NATURE['terracotta'], True),
             ('索引 2 → partial_match (部分匹配概率)', 13, NATURE['earth'], True),
             ('判定：取最大值所在索引确定匹配状态', 13, NATURE['stone']),
         ], title_color=NATURE['forest_dark'])

add_card(slide, Inches(7.0), Inches(4.3), Inches(5.8), Inches(2.2),
         '✅ 人工纠正机制', [
             ('correction_source 字段标识纠正来源', 13, NATURE['stone']),
             ('自动匹配 → "自动匹配"', 13, NATURE['stone']),
             ('人工纠正 → "人工纠正" + exact_match=1.0', 13, NATURE['stone']),
             ('系统启动时自动检测旧表并迁移', 13, NATURE['stone']),
         ], title_color=NATURE['bark'])

add_page_number(slide, 7, TOTAL_SLIDES)

# ==================== Slide 8: 模型加载策略 ====================
slide = prs.slides.add_slide(prs.slide_layouts[6])
add_bg(slide, NATURE['cream'])
add_section_title(slide, '模型加载策略', 'MODEL LOADING STRATEGY')

# 多路径回退
add_text_box(slide, Inches(0.9), Inches(2.0), Inches(5), Inches(0.4),
             '🔍 多路径自动搜索', font_size=20, color=NATURE['forest_dark'], bold=True)

paths = [
    ('优先级 1', '项目目录 models/iic/...', NATURE['forest_dark']),
    ('优先级 2', 'ModelScope 缓存 (~/.cache/modelscope/...)', NATURE['forest_mid']),
    ('优先级 3', 'HuggingFace 缓存 (~/.cache/huggingface/...)', NATURE['sage']),
    ('优先级 4', '在线下载 (ModelScope → Transformers)', NATURE['stone']),
]

for i, (label, desc, color) in enumerate(paths):
    y = Inches(2.6 + i * 0.7)
    add_rounded_rect(slide, Inches(1.0), y, Inches(1.8), Inches(0.45), color)
    add_text_box(slide, Inches(1.1), y + Inches(0.05), Inches(1.6), Inches(0.35),
                 label, font_size=13, color=NATURE['white'], bold=True, alignment=PP_ALIGN.CENTER)
    add_text_box(slide, Inches(3.0), y + Inches(0.05), Inches(9), Inches(0.35),
                 desc, font_size=13, color=NATURE['stone'])

# 右侧：GPU检测
add_card(slide, Inches(7.0), Inches(5.0), Inches(5.8), Inches(1.8),
         '🖥️ GPU 自动检测', [
             ('• torch.cuda.is_available() → PyTorch CUDA 检测', 13, NATURE['stone']),
             ('• nvidia-smi → 系统级 NVIDIA 驱动检测', 13, NATURE['stone']),
             ('• torch.backends.cuda.is_built() → 编译版本检测', 13, NATURE['stone']),
             ('• CPU 版本 + 独立显卡 → 警告提示安装 CUDA 版', 13, NATURE['terracotta']),
         ], title_color=NATURE['forest_mid'])

add_card(slide, Inches(0.8), Inches(5.0), Inches(5.8), Inches(1.8),
         '🔧 兼容性处理', [
             ('• 加载库优先级：modelscope → transformers', 13, NATURE['stone']),
             ('• HuggingFace 加载需 trust_remote_code=True', 13, NATURE['stone']),
             ('• BERT 编码器键名映射：bert.text_encoder.* → bert.*', 13, NATURE['stone']),
             ('• 多路径回退确保各类环境正常运行', 13, NATURE['stone']),
         ], title_color=NATURE['sage'])

add_page_number(slide, 8, TOTAL_SLIDES)

# ==================== Slide 9: 数据库设计 ====================
slide = prs.slides.add_slide(prs.slide_layouts[6])
add_bg(slide, NATURE['cream'])
add_section_title(slide, '数据库设计', 'DATABASE DESIGN')

tables_data = [
    ('enterprise_vectors', '企业地址向量表', '768维向量 + 企业地址字段', NATURE['forest_mid']),
    ('standard_address_vectors', '标准地址向量表', '768维向量 + 标准地址字段', NATURE['sage']),
    ('recall_results', '粗召回结果表', '企业ID、候选地址ID、相似度分数', NATURE['leaf']),
    ('match_results', '精排匹配结果表', '三分类概率、匹配状态、纠正来源', NATURE['terracotta']),
    ('mgeo_similarity_results', 'MGeo相似度结果表', '独立地址相似度匹配输出', NATURE['earth']),
    ('match_tags', '标签配置表', '多任务标签隔离管理', NATURE['stone']),
    ('app_log', '应用日志表', '系统运行日志持久化存储', RGBColor(0x8B, 0x73, 0x55)),
]

for i, (table, desc, detail, color) in enumerate(tables_data):
    y = Inches(2.0 + i * 0.72)
    # 色标
    add_rect(slide, Inches(0.8), y, Inches(0.08), Inches(0.5), color)
    # 表名
    add_text_box(slide, Inches(1.1), y, Inches(3.2), Inches(0.35),
                 table, font_size=14, color=NATURE['forest_dark'], bold=True)
    # 说明
    add_text_box(slide, Inches(1.1), y + Inches(0.3), Inches(3.2), Inches(0.25),
                 desc, font_size=11, color=NATURE['stone'])
    # 详情
    add_text_box(slide, Inches(4.5), y + Inches(0.1), Inches(5), Inches(0.35),
                 detail, font_size=12, color=NATURE['stone'])

# 右侧特性
add_card(slide, Inches(8.0), Inches(2.0), Inches(4.8), Inches(5.0),
         '⚙️ 数据库特性', [
             ('🔒 多Schema隔离', 13, NATURE['forest_mid'], True),
             ('  SET search_path TO "schema", public', 11, NATURE['stone']),
             ('  quote_identifier() 支持中文表名', 11, NATURE['stone']),
             ('', 8, NATURE['stone']),
             ('📊 pgvector 扩展', 13, NATURE['sage'], True),
             ('  IVFFlat 向量索引加速', 11, NATURE['stone']),
             ('  LATERAL JOIN 批量检索', 11, NATURE['stone']),
             ('  cosine_distance 相似度计算', 11, NATURE['stone']),
             ('', 8, NATURE['stone']),
             ('🔄 自动迁移', 13, NATURE['terracotta'], True),
             ('  启动时检测旧表自动添加新字段', 11, NATURE['stone']),
             ('  向量表按创建时间倒序管理', 11, NATURE['stone']),
         ], title_color=NATURE['forest_dark'])

add_page_number(slide, 9, TOTAL_SLIDES)

# ==================== Slide 10: 核心功能模块 ====================
slide = prs.slides.add_slide(prs.slide_layouts[6])
add_bg(slide, NATURE['cream'])
add_section_title(slide, 'Streamlit 核心功能模块', 'CORE FEATURES')

modules = [
    ('🗄️', '数据库配置', 'PostgreSQL连接参数配置\nSchema选择与管理\n连接状态检测', NATURE['forest_mid']),
    ('🔧', '向量预处理', '企业/标准地址表选择\n字段映射配置\n向量表创建与管理\n批量向量化执行', NATURE['sage']),
    ('🎯', '地址匹配', '两阶段匹配流程编排\n进度可视化跟踪\n批量匹配与结果存储\n匹配统计概览', NATURE['terracotta']),
    ('📋', '结果管理', '匹配结果分页展示\n多维度筛选搜索\n人工纠正与标签管理\n数据导出 (Excel/CSV)', NATURE['earth']),
    ('📝', '系统日志', '实时日志查看\n日志级别过滤\n向量调试测试\n系统运行监控', NATURE['stone']),
    ('🏷️', '标签管理', '多任务标签隔离\n拼音自动转换\n标签配置与切换', RGBColor(0x6B, 0x90, 0x80)),
]

for i, (icon, title, desc, color) in enumerate(modules):
    col = i % 3
    row = i // 3
    x = Inches(0.8 + col * 4.1)
    y = Inches(2.0 + row * 2.7)

    add_rounded_rect(slide, x, y, Inches(3.8), Inches(2.4), NATURE['white'])
    add_rect(slide, x, y, Inches(3.8), Inches(0.05), color)
    add_text_box(slide, x + Inches(0.2), y + Inches(0.2), Inches(3.4), Inches(0.4),
                 f'{icon} {title}', font_size=17, color=color, bold=True)
    add_multiline_box(slide, x + Inches(0.2), y + Inches(0.75), Inches(3.4), Inches(1.5),
                      [(line, 12, NATURE['stone']) for line in desc.split('\n')])

add_page_number(slide, 10, TOTAL_SLIDES)

# ==================== Slide 11: 关键技术优化 ====================
slide = prs.slides.add_slide(prs.slide_layouts[6])
add_bg(slide, NATURE['cream'])
add_section_title(slide, '关键技术优化', 'KEY OPTIMIZATIONS')

optimizations = [
    ('🔄', '配置状态恢复', '创建向量表后页面刷新不丢失配置。\n在 selectbox 渲染前从 vec_config 恢复 session_state，\n移除不必要的 st.rerun() 调用。', NATURE['forest_mid']),
    ('🎯', '双重阈值过滤', 'SIMILARITY_THRESHOLD 在粗召回(SQL)和精排(Python)\n两个阶段同时生效，确保低相似度候选不遗漏过滤。', NATURE['sage']),
    ('📊', '向量表管理', '按创建时间倒序 (pg_class.oid DESC)，\n分页显示每页6个，固定高度滚动容器防UI不对齐，\n支持搜索、详情查看、清空、删除、重命名。', NATURE['terracotta']),
    ('🔗', '翻页回调机制', 'Streamlit on_click 回调函数 (_goto_page, _prev_page,\n_next_page) 解决 session_state 绑定 widget 后\n无法直接修改的问题。', NATURE['earth']),
    ('📝', '批量数据处理', '数据库批量加载 (BATCH_SIZE_DB=1000)，\n向量化批处理 (BATCH_SIZE_EMBEDDING=256 GPU)，\n精排批处理 (BATCH_SIZE_MODEL=128 GPU)。', NATURE['stone']),
    ('🔤', '编码自动检测', 'CSV文件上传自动检测编码格式：\nutf-8-sig → utf-8 → gbk → gb2312 → gb18030 → latin1\n确保各类中文编码文件正常导入。', RGBColor(0x6B, 0x90, 0x80)),
]

for i, (icon, title, desc, color) in enumerate(optimizations):
    y = Inches(2.0 + i * 0.88)
    add_rect(slide, Inches(0.8), y, Inches(0.06), Inches(0.75), color)
    add_text_box(slide, Inches(1.1), y, Inches(3.2), Inches(0.3),
                 f'{icon} {title}', font_size=16, color=color, bold=True)
    add_multiline_box(slide, Inches(4.5), y, Inches(8.2), Inches(0.75),
                      [(line, 12, NATURE['stone']) for line in desc.split('\n')])

add_page_number(slide, 11, TOTAL_SLIDES)

# ==================== Slide 12: 总结 ====================
slide = prs.slides.add_slide(prs.slide_layouts[6])
add_bg(slide, NATURE['cream'])

# 顶部色块
add_rect(slide, Inches(0), Inches(0), Inches(13.333), Inches(2.5), NATURE['forest_dark'])
add_rect(slide, Inches(0), Inches(2.0), Inches(13.333), Inches(0.8), NATURE['forest_mid'])
add_rect(slide, Inches(2), Inches(2.7), Inches(9.333), Inches(0.03), NATURE['sage'])

add_text_box(slide, Inches(1.5), Inches(0.6), Inches(10.333), Inches(0.8),
             '总结与展望', font_size=40, color=NATURE['white'], bold=True, alignment=PP_ALIGN.CENTER)
add_text_box(slide, Inches(1.5), Inches(1.5), Inches(10.333), Inches(0.5),
             'SUMMARY & OUTLOOK', font_size=20, color=NATURE['mint'], alignment=PP_ALIGN.CENTER)

# 三列总结
summaries = [
    ('🏆', '技术成果', [
        '• 实现150万×1300万规模的',
        '  地址语义匹配',
        '• 两阶段架构兼顾效率精度',
        '• pgvector 高效向量检索',
        '• MGeo 精准中文地址理解',
    ], NATURE['forest_mid']),
    ('⚡', '工程实践', [
        '• Streamlit 交互式Web应用',
        '• 多Schema数据隔离',
        '• 人工纠正与结果管理',
        '• 完善的日志与监控体系',
    ], NATURE['sage']),
    ('🚀', '未来展望', [
        '• 支持更多地址匹配模型',
        '• 进一步提升批处理性能',
        '• 增加批量人工审核功能',
        '• API化服务接口扩展',
    ], NATURE['terracotta']),
]

for i, (icon, title, items, color) in enumerate(summaries):
    x = Inches(0.8 + i * 4.1)
    add_rounded_rect(slide, x, Inches(3.3), Inches(3.8), Inches(3.0), NATURE['white'])
    add_rect(slide, x, Inches(3.3), Inches(3.8), Inches(0.05), color)
    add_text_box(slide, x + Inches(0.3), Inches(3.5), Inches(3.2), Inches(0.4),
                 f'{icon} {title}', font_size=18, color=color, bold=True)
    add_multiline_box(slide, x + Inches(0.3), Inches(4.0), Inches(3.2), Inches(2.0),
                      [(item, 12, NATURE['stone']) for item in items])

# 底部
add_rect(slide, Inches(0), Inches(6.8), Inches(13.333), Inches(0.7), NATURE['forest_dark'])
add_text_box(slide, Inches(1.5), Inches(6.88), Inches(10.333), Inches(0.5),
             'Thanks  ·  GitHub: badwoo  ·  Python + PostgreSQL + Streamlit + MGeo',
             font_size=13, color=NATURE['mint'], alignment=PP_ALIGN.CENTER)

# 装饰
for i, (x, r, c) in enumerate([
    (Inches(11.5), Inches(0.25), NATURE['sage']),
    (Inches(11.0), Inches(0.3), NATURE['mint']),
    (Inches(1.2), Inches(0.25), NATURE['sage']),
    (Inches(1.0), Inches(0.35), NATURE['mint']),
]):
    circle = slide.shapes.add_shape(MSO_SHAPE.OVAL, x, Inches(0.3), r, r)
    circle.fill.solid()
    circle.fill.fore_color.rgb = c
    circle.line.fill.background()

add_page_number(slide, 12, TOTAL_SLIDES)

# ==================== 保存 ====================
output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '地址匹配系统项目介绍.pptx')
prs.save(output_path)
print(f'PPT已生成: {output_path}')
print(f'共 {len(prs.slides)} 页幻灯片')
