import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
import numpy as np

plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False

fig, ax = plt.subplots(1, 1, figsize=(22, 32))
ax.set_xlim(0, 22)
ax.set_ylim(0, 32)
ax.axis('off')

# Color scheme - modern and beautiful
colors = {
    'stage1': '#1a5276',
    'stage1_light': '#d6eaf8',
    'stage2': '#2874a6',
    'stage2_light': '#d4e6f1',
    'stage3': '#3498db',
    'stage3_light': '#aed6f1',
    'stage3_lighter': '#ebf5fb',
    'stage3_sub': '#85c1e9',
    'stage4': '#27ae60',
    'stage4_light': '#d5f5e3',
    'stage5': '#e67e22',
    'stage5_light': '#fdebd0',
    'stage6': '#8e44ad',
    'stage6_light': '#e8daef',
    'end': '#2c3e50',
    'text_dark': '#2c3e50',
    'text_white': '#ffffff',
    'arrow': '#7f8c8d'
}

def draw_rounded_box(ax, x, y, width, height, color, text, fontsize=12, textcolor='white', radius=0.3, alpha=1.0):
    box = FancyBboxPatch((x - width/2, y - height/2), width, height,
                         boxstyle=f"round,pad=0.02,rounding_size={radius}",
                         facecolor=color, edgecolor='white', linewidth=2, alpha=alpha, zorder=2)
    ax.add_patch(box)
    ax.text(x, y, text, ha='center', va='center', fontsize=fontsize,
            color=textcolor, fontweight='bold', wrap=True, zorder=3)
    return box

def draw_arrow(ax, x1, y1, x2, y2, color='#7f8c8d'):
    ax.annotate('', xy=(x2, y2), xytext=(x1, y1),
                arrowprops=dict(arrowstyle='->', color=color, lw=2), zorder=1)

# Title
ax.text(11, 31, '深圳市市场监管局政务服务基础能力提升项目', ha='center', va='center',
        fontsize=22, color=colors['text_dark'], fontweight='bold')
ax.text(11, 30.2, '实施流程图', ha='center', va='center',
        fontsize=16, color='#7f8c8d')

# Stage 1
draw_rounded_box(ax, 11, 28.5, 18, 1.2, colors['stage1'], '第一阶段：数据准备', fontsize=16)
draw_rounded_box(ax, 11, 27, 16, 1.2, colors['stage1_light'],
                 '市监商事主体数据 (HA_MER_BASE) + 政法委网格数据\n+ 房屋编码数据 + 互联网接口数据',
                 fontsize=11, textcolor=colors['stage1'])

# Stage 2
draw_rounded_box(ax, 11, 24.8, 18, 1.2, colors['stage2'], '第二阶段：数据调研与规则制定', fontsize=16)
draw_rounded_box(ax, 6.5, 23.2, 8, 1.2, colors['stage2_light'],
                 '字段完整性 / 唯一性\n/ 规范性调研', fontsize=11, textcolor=colors['stage2'])
draw_rounded_box(ax, 15.5, 23.2, 8, 1.2, colors['stage2_light'],
                 '定义分类标签规则\n(匹配策略/可信度)', fontsize=11, textcolor=colors['stage2'])

# Stage 3
draw_rounded_box(ax, 11, 20.8, 18, 1.2, colors['stage3'], '第三阶段：数据治理实施', fontsize=16)

# 3.1 and 3.2 side by side
draw_rounded_box(ax, 6.5, 19, 8, 0.9, colors['stage3_light'], '3.1 规则匹配', fontsize=13, textcolor=colors['stage1'])
draw_rounded_box(ax, 6.5, 17.6, 8, 1.4, colors['stage3_lighter'],
                 '地址分词\nL1-L5级由粗到细匹配\n(全地址→省市区街道)', fontsize=10, textcolor=colors['stage1'])

draw_rounded_box(ax, 15.5, 19, 8, 0.9, colors['stage3_light'], '3.2 MGeo方案匹配', fontsize=13, textcolor=colors['stage1'])
draw_rounded_box(ax, 15.5, 17.6, 8, 1.4, colors['stage3_lighter'],
                 '阿里MGeo开源模型\n数据拼召回 + 精排架构\n地址进一步匹配验证', fontsize=10, textcolor=colors['stage1'])

# 3.3
draw_rounded_box(ax, 11, 15.8, 10, 0.9, colors['stage3_sub'], '3.3 互联网方案', fontsize=13)
draw_rounded_box(ax, 7.5, 14.4, 7, 1.0, colors['stage3_lighter'],
                 '百度/高德接口\n地址获取+地理编码', fontsize=10, textcolor=colors['stage1'])
draw_rounded_box(ax, 14.5, 14.4, 7, 1.0, colors['stage3_lighter'],
                 '地址地理四配\n坐标转换', fontsize=10, textcolor=colors['stage1'])

# Stage 4
draw_rounded_box(ax, 11, 12.5, 18, 1.2, colors['stage4'], '第四阶段：质量检核与人工复核', fontsize=16)
draw_rounded_box(ax, 6.5, 10.9, 8, 1.2, colors['stage4_light'],
                 'MGeo多轮验证\n(不同阈值)', fontsize=11, textcolor=colors['stage4'])
draw_rounded_box(ax, 15.5, 10.9, 8, 1.2, colors['stage4_light'],
                 '人工抽样检查\n质量把关', fontsize=11, textcolor=colors['stage4'])

# Stage 5
draw_rounded_box(ax, 11, 8.7, 18, 1.2, colors['stage5'], '第五阶段：效果评估 + 数据分类分级打标签', fontsize=16)
# 6 sub-items in 2 rows
sub_items = ['黑牌经济单', '灰名单经济单', '片区经济单', '绿通数据清单', '灭失数据清单', '深汕数据清单']
positions = [(4.5, 7.3), (8.5, 7.3), (12.5, 7.3), (16.5, 7.3), (6.5, 5.9), (14.5, 5.9)]
for item, pos in zip(sub_items, positions):
    draw_rounded_box(ax, pos[0], pos[1], 3.8, 0.9, colors['stage5_light'], item, fontsize=11, textcolor='#b9770e')

# Stage 6
draw_rounded_box(ax, 11, 4.2, 18, 1.2, colors['stage6'], '第六阶段：数据入库', fontsize=16)
draw_rounded_box(ax, 6.5, 2.6, 8, 1.2, colors['stage6_light'],
                 '标签化数据整理\n关联房屋编码', fontsize=11, textcolor=colors['stage6'])
draw_rounded_box(ax, 15.5, 2.6, 8, 1.2, colors['stage6_light'],
                 '数据融合\n汇总生成成果表', fontsize=11, textcolor=colors['stage6'])

# End
draw_rounded_box(ax, 11, 0.8, 10, 1.0, colors['end'], '项目完成', fontsize=18)

# Draw arrows
arrow_color = '#95a5a6'
arrow_lw = 2.5

# Title to Stage 1
ax.annotate('', xy=(11, 29.1), xytext=(11, 29.8),
            arrowprops=dict(arrowstyle='->', color=arrow_color, lw=arrow_lw))

# Stage 1 to detail
ax.annotate('', xy=(11, 27.6), xytext=(11, 27.9),
            arrowprops=dict(arrowstyle='->', color=arrow_color, lw=arrow_lw))

# Detail to Stage 2
ax.annotate('', xy=(11, 25.4), xytext=(11, 26.4),
            arrowprops=dict(arrowstyle='->', color=arrow_color, lw=arrow_lw))

# Stage 2 to details
ax.annotate('', xy=(6.5, 23.8), xytext=(6.5, 24.2),
            arrowprops=dict(arrowstyle='->', color=arrow_color, lw=arrow_lw))
ax.annotate('', xy=(15.5, 23.8), xytext=(15.5, 24.2),
            arrowprops=dict(arrowstyle='->', color=arrow_color, lw=arrow_lw))

# Details to Stage 3
ax.annotate('', xy=(11, 21.4), xytext=(6.5, 22.6),
            arrowprops=dict(arrowstyle='->', color=arrow_color, lw=arrow_lw,
                           connectionstyle="arc3,rad=0.1"))
ax.annotate('', xy=(11, 21.4), xytext=(15.5, 22.6),
            arrowprops=dict(arrowstyle='->', color=arrow_color, lw=arrow_lw,
                           connectionstyle="arc3,rad=-0.1"))

# Stage 3 to 3.1/3.2
ax.annotate('', xy=(6.5, 19.45), xytext=(9, 20.2),
            arrowprops=dict(arrowstyle='->', color=arrow_color, lw=arrow_lw,
                           connectionstyle="arc3,rad=0.1"))
ax.annotate('', xy=(15.5, 19.45), xytext=(13, 20.2),
            arrowprops=dict(arrowstyle='->', color=arrow_color, lw=arrow_lw,
                           connectionstyle="arc3,rad=-0.1"))

# 3.1/3.2 to their details
ax.annotate('', xy=(6.5, 18.3), xytext=(6.5, 18.55),
            arrowprops=dict(arrowstyle='->', color=arrow_color, lw=arrow_lw))
ax.annotate('', xy=(15.5, 18.3), xytext=(15.5, 18.55),
            arrowprops=dict(arrowstyle='->', color=arrow_color, lw=arrow_lw))

# 3.1/3.2 details to 3.3
ax.annotate('', xy=(9, 15.8), xytext=(6.5, 16.9),
            arrowprops=dict(arrowstyle='->', color=arrow_color, lw=arrow_lw,
                           connectionstyle="arc3,rad=0.1"))
ax.annotate('', xy=(13, 15.8), xytext=(15.5, 16.9),
            arrowprops=dict(arrowstyle='->', color=arrow_color, lw=arrow_lw,
                           connectionstyle="arc3,rad=-0.1"))

# 3.3 to its details
ax.annotate('', xy=(7.5, 14.9), xytext=(9.5, 15.35),
            arrowprops=dict(arrowstyle='->', color=arrow_color, lw=arrow_lw,
                           connectionstyle="arc3,rad=0.1"))
ax.annotate('', xy=(14.5, 14.9), xytext=(12.5, 15.35),
            arrowprops=dict(arrowstyle='->', color=arrow_color, lw=arrow_lw,
                           connectionstyle="arc3,rad=-0.1"))

# 3.3 details to Stage 4
ax.annotate('', xy=(11, 13.1), xytext=(7.5, 13.9),
            arrowprops=dict(arrowstyle='->', color=arrow_color, lw=arrow_lw,
                           connectionstyle="arc3,rad=0.1"))
ax.annotate('', xy=(11, 13.1), xytext=(14.5, 13.9),
            arrowprops=dict(arrowstyle='->', color=arrow_color, lw=arrow_lw,
                           connectionstyle="arc3,rad=-0.1"))

# Stage 4 to details
ax.annotate('', xy=(6.5, 11.5), xytext=(6.5, 11.9),
            arrowprops=dict(arrowstyle='->', color=arrow_color, lw=arrow_lw))
ax.annotate('', xy=(15.5, 11.5), xytext=(15.5, 11.9),
            arrowprops=dict(arrowstyle='->', color=arrow_color, lw=arrow_lw))

# Details to Stage 5
ax.annotate('', xy=(11, 9.3), xytext=(6.5, 10.3),
            arrowprops=dict(arrowstyle='->', color=arrow_color, lw=arrow_lw,
                           connectionstyle="arc3,rad=0.1"))
ax.annotate('', xy=(11, 9.3), xytext=(15.5, 10.3),
            arrowprops=dict(arrowstyle='->', color=arrow_color, lw=arrow_lw,
                           connectionstyle="arc3,rad=-0.1"))

# Stage 5 to sub items
for pos in [(4.5, 7.7), (8.5, 7.7), (12.5, 7.7), (16.5, 7.7)]:
    ax.annotate('', xy=(pos[0], pos[1]), xytext=(pos[0], 8.1),
                arrowprops=dict(arrowstyle='->', color=arrow_color, lw=arrow_lw))

# Sub items row 1 to row 2
ax.annotate('', xy=(6.5, 6.35), xytext=(4.5, 6.85),
            arrowprops=dict(arrowstyle='->', color=arrow_color, lw=arrow_lw,
                           connectionstyle="arc3,rad=0.1"))
ax.annotate('', xy=(6.5, 6.35), xytext=(8.5, 6.85),
            arrowprops=dict(arrowstyle='->', color=arrow_color, lw=arrow_lw,
                           connectionstyle="arc3,rad=-0.1"))
ax.annotate('', xy=(14.5, 6.35), xytext=(12.5, 6.85),
            arrowprops=dict(arrowstyle='->', color=arrow_color, lw=arrow_lw,
                           connectionstyle="arc3,rad=0.1"))
ax.annotate('', xy=(14.5, 6.35), xytext=(16.5, 6.85),
            arrowprops=dict(arrowstyle='->', color=arrow_color, lw=arrow_lw,
                           connectionstyle="arc3,rad=-0.1"))

# Stage 5 sub items to Stage 6
ax.annotate('', xy=(11, 4.8), xytext=(6.5, 5.45),
            arrowprops=dict(arrowstyle='->', color=arrow_color, lw=arrow_lw,
                           connectionstyle="arc3,rad=0.1"))
ax.annotate('', xy=(11, 4.8), xytext=(14.5, 5.45),
            arrowprops=dict(arrowstyle='->', color=arrow_color, lw=arrow_lw,
                           connectionstyle="arc3,rad=-0.1"))

# Stage 6 to details
ax.annotate('', xy=(6.5, 3.2), xytext=(6.5, 3.6),
            arrowprops=dict(arrowstyle='->', color=arrow_color, lw=arrow_lw))
ax.annotate('', xy=(15.5, 3.2), xytext=(15.5, 3.6),
            arrowprops=dict(arrowstyle='->', color=arrow_color, lw=arrow_lw))

# Details to End
ax.annotate('', xy=(11, 1.3), xytext=(6.5, 2.0),
            arrowprops=dict(arrowstyle='->', color=arrow_color, lw=arrow_lw,
                           connectionstyle="arc3,rad=0.1"))
ax.annotate('', xy=(11, 1.3), xytext=(15.5, 2.0),
            arrowprops=dict(arrowstyle='->', color=arrow_color, lw=arrow_lw,
                           connectionstyle="arc3,rad=-0.1"))

plt.tight_layout()
plt.savefig('d:\\pythonProject\\address_match\\flowchart_beautified.png', dpi=200, bbox_inches='tight',
            facecolor='white', edgecolor='none')
plt.savefig('d:\\pythonProject\\address_match\\flowchart_beautified.pdf', bbox_inches='tight',
            facecolor='white', edgecolor='none')
print("图片已保存到 flowchart_beautified.png")
