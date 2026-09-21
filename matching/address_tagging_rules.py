# -*- coding: utf-8 -*-
"""
地址12级规则拆分引擎
====================

将中文地址按12级结构进行纯规则拆分，不依赖 MGeo/PyTorch。

输出字段与 model.address_tagging_model.OUTPUT_FIELDS 保持一致：
    province, city, district, street, community,
    road, roadno, area, bldg, unit, floor, house

设计要点：
    1. 行政区划（province/city/district/street/community）顺序切分。
    2. street/community 采用"最长匹配"策略，优先匹配"街道"、"社区"。
    3. road 提取以 roadno 为锚点，从后向前定位道路关键字，并按 area/楼栋边界拆分，
       避免道路过度吞噬 area（如"怡心广场C座怡心街10号"）。
    4. area/bldg/unit/floor/house 在道路/门牌号之后的剩余文本中按优先级提取。
"""

import re
from typing import List, Dict, Any

from model.address_tagging_model import OUTPUT_FIELDS


CN_NUM = '一二三四五六七八九十百零〇'

# 道路关键字（用于 road 提取）
# 方向性复合后缀（如东路、南路、西路、北路）必须排在单独的“路”之前，
# 避免“侨城东路”被错误拆成 area=“侨城”、road=“东路”。
ROAD_KEYWORDS = (
    r'大道|大街|小路|胡同|'
    r'东路|南路|西路|北路|中路|前路|后路|上路|下路|新路|老路|大路|正路|'
    r'路|街|道|巷|弄'
)
ROAD_KEYWORD_PATTERN = re.compile(ROAD_KEYWORDS)

# 行政区划残留模式：用于清理 area 中意外包含的“广东省/深圳市/XX街道/XX社区”前缀
# 注意：去掉 [^区]+?区 分支，避免误切 POI 名（如"天骄校区"、"A区"、"工业区"）。
# district 残留由 province/city 切分时已处理，单独"XX区"残留较少且易与 POI 名混淆。
AREA_ADMIN_RESIDUE_PATTERN = re.compile(
    r'^(广东省|深圳市|[^街道]+?(?:街道|镇|乡)|[^社区村]+?(?:社区|居委会))'
)

# 硬边界：area/建筑物关键字，表示 area 结束、道路开始
HARD_BOUNDARY_KEYWORDS = (
    r'村|坊|区|新村|小区|花园|花苑|家园|鑫苑|名苑|雅苑|绿洲|华庭|豪庭|名庭|嘉园|华府|'
    r'苑|庭|园|居|墅|邨|庄|组|围|阁|府|湾|岸|岛|里|城|都|国际|壹号|一号|二期|三期|期|'
    r'公寓|大厦|广场|中心|商城|商场|商务|食堂|舎|宿|轩|堂|馆|棚|洲|'
    r'工业区|产业园|科技园|创业园|物流园|商贸城|大学城|学校|学院|医院|银行|酒店|'
    r'综合楼|办公楼|写字楼|厂房|仓库|商铺|门面|门店|营业部|分公司|总部|项目部|管理处|交汇处|'
    r'市场|综合市场|综合商业楼|商业楼|宿舍楼|宿舍|菜场|集装箱|板房|集团|地铁|'
    r'商业街|商业广场|商业城|商业中心|购物广场|购物中心|步行街'
)
HARD_BOUNDARY_PATTERN = re.compile(HARD_BOUNDARY_KEYWORDS)

# 软边界：结构关键字，前面通常是 area、后面是道路
SOFT_BOUNDARY_KEYWORDS = (
    r'号楼|塔楼|单元|栋|幢|座|层|楼|F|号'
)
SOFT_BOUNDARY_PATTERN = re.compile(SOFT_BOUNDARY_KEYWORDS)

# area 关键字（用于 area 识别与长度控制）
AREA_KEYWORDS = (
    r'小区|花园|花苑|家园|鑫苑|名苑|雅苑|绿洲|华庭|豪庭|名庭|嘉园|华府|公寓|大厦|'
    r'广场|中心|商城|商场|城|都|国际|壹号|一号|二期|三期|期|阁|府|湾|岸|岛|里|'
    r'苑|庭|园|居|墅|邨|坊|村|庄|组|围|中心|商务|食堂|舎|宿|轩|堂|馆|棚|洲|'
    r'工业区|产业园|科技园|创业园|物流园|商贸城|大学城|学校|学院|医院|银行|酒店|'
    r'综合楼|办公楼|写字楼|厂房|仓库|商铺|门面|门店|营业部|分公司|总部|项目部|管理处|交汇处|'
    r'市场|综合市场|综合商业楼|商业楼|宿舍楼|宿舍|菜场|集装箱|板房|集团|地铁|'
    r'商业街|商业广场|商业城|商业中心|购物广场|购物中心|步行街|'
    r'[一二三四五六七八九十ABCDEFG]?区'
)
AREA_KEYWORD_PATTERN = re.compile(AREA_KEYWORDS)

# 门牌号
# 注意：去掉末尾的 [\dA-Za-z]*，避免把"数字+字母+数字+字母+号"（如 1B057A号）
# 这类房号误识别为门牌号。门牌号通常只支持：纯数字+号、字母+数字+号、
# 数字+横杠+数字+号 等简单结构。
ROADNO_PATTERN = re.compile(
    r'((?:\d+|[' + CN_NUM + r']+|附\d+|A\d+|B\d+|C\d+|D\d+)(?:[\-－/\\]\d+)?\s*号)'
)

# 楼栋号（注意：单独的"号"不是楼栋，必须配合"号楼"或栋/幢/座/塔楼）
# 增加 (?:第\s*)? 可选前缀：识别"第1栋/第一栋"等结构，"第"字被消耗但不进入捕获组，
# 避免分词结果中 bldg 包含"第"或"第"字残留 area。
# 增加横杠连接多栋分支（必须放在最前）：识别 5-8栋、12-15栋、62-1栋、1-3号楼、1-2-3-4栋 等
# 横杠连接的多栋编号（支持2段及以上），避免被 _find_house 第一个模式（横杠/斜杠多段连接）
# 抢先匹配为 house。
BLDG_PATTERN = re.compile(
    r'(?:第\s*)?'
    r'('
    r'[A-Za-z\d]+(?:\s*[-－]\s*[A-Za-z\d]+)+\s*(?:栋|幢|座|号楼)|'  # 横杠连接多栋（5-8栋、12-15栋、62-1栋、1-3号楼、1-2-3-4栋、B13-3栋、A5-3栋）
    r'[A-Za-z](?:\s*[.．]\s*[A-Za-z])+\s*(?:座|楼|栋|幢)|'  # 点号连接多座（如 A.B座、A.B.C座）
    r'[A-Za-z][\d' + CN_NUM + r']+\s*(?:栋|幢|座)|'      # B9栋、A1座
    r'[\d' + CN_NUM + r']+\s*(?:栋|幢|座)|'
    r'[\d' + CN_NUM + r']+\s*号楼|'
    r'[\d' + CN_NUM + r'A-Za-z]+\s*[塔楼]|'
    r'[东南西北]\s*[座楼]|'
    r'[A-Za-z]\s*[座楼栋幢]'  # 单字母+栋/幢/座/楼，如 C栋、A幢
    r')'
)

# 单元号
# 支持字母前缀（如 A单元、AB单元、EFGH单元），避免字母单元被丢弃或被吞入 area。
# 字母单元在真实地址中大量存在（A单元6472/B单元5623/C单元1833/D单元910/AB单元3等）。
UNIT_PATTERN = re.compile(
    r'([\d' + CN_NUM + r']+\s*(?:单元|梯)|'
    r'[一二三四五六七八九十]+\s*(?:单元|梯)|'
    r'[A-Za-z]+\s*(?:单元|梯))'
)

# bldg 之后的"X座"作为 unit 的模式（仅在 _parse_tail_after_bldg 中使用）。
# 用于处理"X栋Y座"结构（如"3栋5座101"中"5座"是 unit，"3栋B座101"中"B座"是 unit）。
# 单独的"X座"（无前导 bldg）在主流程中仍由 BLDG_PATTERN 识别为 bldg。
ZUO_AS_UNIT_PATTERN = re.compile(r'([\d' + CN_NUM + r'A-Za-z]+\s*座)')

# 楼层号
# 扩展"第X层"支持中文数字（如"第二层"），避免"第"字残留 area。
# 增加"[A-Za-z]层"分支：识别"G层/P层"等字母标识的楼层（G=Ground, P=Parking），
# 避免字母残留在 area 中。
# 扩展：支持"字母+数字+层"（如 B1层，B1层是地下一层/负一层标识），
# 避免 B 残留 area 或 floor 丢失前导字母。
FLOOR_PATTERN = re.compile(
    r'((?:[A-Za-z]?\d+|[' + CN_NUM + r']+|[A-Za-z])\s*[层楼F]|'
    r'负\s*(?:\d+|[' + CN_NUM + r']+)\s*[层樓]|'
    r'第\s*(?:\d+|[' + CN_NUM + r']+)\s*[层樓])'
)

# 特殊无数字 house 描述
SPECIAL_HOUSE_PATTERN = re.compile(
    r'(整套|之一|公共空间|机房|食堂|大堂|东面|西面|南面|北面|操作间|垃圾房|避难层|'
    r'杂物房|工具房|工人食堂|架空层|风机房|水泵房|配电房|变压器房|垃圾站|公厕|'
    r'卫生间|楼梯间|电梯间|走廊|过道|门厅|前台|办公室|会议室|库房|车间|工区|工位)'
)

# ---- 预编译正则：原 _parse_single 内每次调用都重新编译，提升到模块级别避免重复编译 ----
# 行政区划切分
_PROVINCE_PATTERN = re.compile(r'^(.+?(?:省|自治区|特别行政区))')
_CITY_PATTERN = re.compile(r'^(.*?市)')
_DISTRICT_PATTERN = re.compile(r'^(.*?[区县])')
_ADMIN_PATTERNS = [
    ('province', [_PROVINCE_PATTERN]),
    ('city', [_CITY_PATTERN]),
    ('district', [_DISTRICT_PATTERN]),
]

# street/community 按优先级匹配
_STREET_PATTERNS = [
    re.compile(r'^(.*?街道)'),
    re.compile(r'^(.*?镇)'),
    re.compile(r'^(.*?乡)'),
]
_COMMUNITY_PATTERNS = [
    re.compile(r'^(.*?社区)'),
    re.compile(r'^(.*?村)'),
    re.compile(r'^(.*?居委会)'),
]

# ---- 预编译正则：原 _find_house 内每次调用都重新编译 ----
# 后缀列表（长后缀优先，避免被短后缀抢先匹配）
# 扩展：增加 房屋/厂房/专柜/店 等房号后缀类型
# 扩展：增加 教师宿舍/宿舍/杂物间/夹层/教室/裙楼 等建筑/房间类型后缀
#   - 教师宿舍(4字) 必须在 宿舍(2字) 前
#   - 杂物间(3字) 必须在 间(1字) 前
#   - 裙楼/夹层/教室 为独立后缀，不与现有短后缀冲突
_HOUSE_SUFFIX = r'(?:商铺|店铺|商店|号铺|铺位|铺面|档铺|教师宿舍|杂物间|房间|房屋|厂房|柜台|专柜|档口|裙楼|夹层|教室|宿舍|埔|铺|号档|[一-龥]档|档|室|房|户|间|柜|店)'
HOUSE_PATTERNS = [
    # 多房号顿号分隔（如 F202、203 / 1311、1312、1313室 / B-2201、2202A / 24D-F、D1 /
    # 163号、164号 / 7号、8号、35号、55号、56号 / 39号、40号）
    # 段 = 字母数字+可选横杠/长横杠/点号/波浪线连接；每段后可带"号"（_find_house 中统一去号），
    # 末尾可带房号后缀，末尾锚定$
    # 避免"7、8、9、16栋201"（bldg序列）误匹配：段后跟"栋"无法消化，整体不匹配
    re.compile(
        r'((?:[A-Za-z0-9]+(?:[-－/—.~]+[A-Za-z0-9]+)*号?、)+'
        r'[A-Za-z0-9]+(?:[-－/—.~]+[A-Za-z0-9]+)*号?)'
        r'\s*(?:' + _HOUSE_SUFFIX + r')?\s*$'
    ),
    # 横杠连接 + 括号数字（如 A-3501(03)、3A08-(2)），括号内容是房号一部分需保留
    # 扩展：横杠后可直接跟括号（如 3A08-(2) 中"-"后无字母数字段）
    # 支持 双横杠（如 23Q--2418）
    re.compile(r'([A-Za-z0-9]+(?:[-－/—]+[A-Za-z0-9]+)*[-－/—]?\(\d+\))'),
    # 下划线连接房号（如 A322B_01），lookbehind 从串首匹配
    # lookahead 要求至少含一个数字，避免纯字母 A_B 误匹配
    # 必须早于"通用字母数字多段交替"模式：否则 A322B_01 会被通用模式
    # 通过回溯拆分为 A32+2B 两段抢先匹配为 A322B，丢失 _01 部分
    re.compile(r'(?<![A-Za-z0-9])((?=[A-Za-z0-9_]*\d)[A-Za-z0-9]+(?:_[A-Za-z0-9]+)+)'),
    # 通用字母数字多段交替（如 6A1BC、N2C248、12B19G1、B1JF428、F1F0009、A4207A6、1F0009）
    # {2,} 确保至少两段"字母+数字"/"数字+字母"交替，避免误匹配单段（B16、100B、A137等）
    # lookbehind 确保从混合串起始位置匹配，避免开头字母残留 area（如 N2C248 被切为 N+2C248）
    re.compile(r'(?<![A-Za-z0-9])((?:[A-Za-z]+\d+|\d+[A-Za-z]+){2,}[A-Za-z0-9]*)'),
    # 前导连接符 + 横杠连接 + 号 + 后缀（如 -LM-11号商铺），房号含前导"-"
    # 必须早于"横杠连接+号+后缀"和"横杠连接"，避免前导"-"被截断
    # 注意：增加 lookbehind 断言 (?<![A-Za-z0-9])，确保前导"-"前面不是字母/数字，
    # 避免 "LG-M-05号铺" 被错误匹配为 "-M-05"（应整体匹配为 "LG-M-05"）
    re.compile(r'(?<![A-Za-z0-9])([-－][A-Za-z0-9]+(?:[-－/—]+[A-Za-z0-9]+)+)\s*号\s*' + _HOUSE_SUFFIX),
    # 横杠连接 + 号 + 后缀（如 A17-3号铺、102-103-2号商铺、LG-M-05号铺、196—215号商铺、36-37号鱼档）
    # 支持双横杠（如 23Q--2418号室）、长横杠（如 196—215，U+2014）、
    # 点号/波浪线连接（如 104.105号商铺、1030~1032号商铺）
    re.compile(r'([A-Za-z0-9]+(?:[-－/—.~]+[A-Za-z0-9]+)+)\s*号\s*' + _HOUSE_SUFFIX),
    # 横杠/点号/波浪线连接 + 号（如 104.105号、8106.8108号、1030~1032号、101-1号、810.811.812号）
    # "号"不纳入 house 值；放在"连接+号+后缀"之后处理号后无后缀的场景，
    # 放在"横杠连接+末尾"之前避免"104.105"被截断为末段数字
    re.compile(r'([A-Za-z0-9]+(?:[-－/—.~]+[A-Za-z0-9]+)+)\s*号$'),
    # 横杠连接 + 后缀（不含"号"，如 23Q--2418室、301-302房、B-13D铺、B1-09——CB109柜）
    # 后缀不纳入 house 值，必须放在"横杠连接+末尾"模式之前
    # 支持长横杠/双横杠（如 ——）
    re.compile(r'([A-Za-z0-9]+(?:[-－/—]+[A-Za-z0-9]+)+)\s*' + _HOUSE_SUFFIX),
    # 横杠/斜杠多段连接（如 101-102、L1-21A、23Q--2418、B1-49.50）
    # 重要：增加末尾锚定 $，只匹配末尾的横杠连接，避免把文本中间的门牌号
    # （如 "村12-14号时代科创中心503" 中的 "12-14"）误识别为房号
    # 扩展：连接符支持点号/波浪线（如 B1-49.50、1030~1032）和长横杠
    re.compile(r'([A-Za-z0-9]+(?:[-－/—.~]+[A-Za-z0-9]+)+)$'),
    # 字母+数字+字母+数字+字母（如 A4480A），早于"字母+数字+字母"避免截断
    re.compile(r'([A-Za-z]+\d+[A-Za-z]\d+[A-Za-z])'),
    # 数字+字母+数字+字母（如 1B057A、3C11A），早于"数字+字母+数字"避免截断
    re.compile(r'(\d+[A-Za-z]\d+[A-Za-z])'),
    # 数字+字母+数字（如 7B12、1A101）
    re.compile(r'(\d+[A-Za-z]\d+)'),
    # 字母+数字+字母+字母（如 B11HI、G23C），早于"字母+数字+字母"避免截断
    re.compile(r'([A-Za-z]+\d+[A-Za-z]{2,})'),
    # 字母+数字+字母（如 B16D、A101B），早于"字母+数字"避免截断末尾字母
    re.compile(r'([A-Za-z]+\d+[A-Za-z]\d*)'),
    # 附+数字（如 附01）
    re.compile(r'(附\s*\d+)'),
    # 字母数字组合(必含字母) + 号 + 后缀（如 3B号商铺、417A号商铺、A137号铺、G23C号铺）
    re.compile(r'([0-9]*[A-Za-z][A-Za-z0-9]*)\s*号\s*' + _HOUSE_SUFFIX),
    # 字母数字组合(必含字母) + 号（如 111A号、510B号、A137号、3C11A号）
    re.compile(r'([0-9]*[A-Za-z][A-Za-z0-9]*)\s*号(?![楼栋幢座])'),
    # 数字+字母+后缀：处理"18A铺"、"101A室"等组合，后缀不纳入house值
    re.compile(r'(\d+[A-Za-z])\s*' + _HOUSE_SUFFIX),
    # 字母+后缀：处理"A铺"、"B档"等字母标识的商铺/档口房号，后缀不纳入house值
    re.compile(r'([A-Za-z]+)\s*' + _HOUSE_SUFFIX),
    # 字母+数字（如 F521、B101、A1），早于末尾纯数字避免字母残留area
    re.compile(r'([A-Za-z]+\d+)'),
    # "之X"子房号：提取"之"前面的数字（如302之2→302、106之8→106、201之4→201、302之12→302）
    # 必须在"末尾纯数字2-4位"之前，避免"302之12"中"12"被末尾纯数字模式抢先匹配
    # 末尾锚定$，避免匹配文本中间的"数字+之+数字"
    # 注意：仅匹配"之+ASCII数字"，不匹配"之一/之二"等中文数字（由 SPECIAL_HOUSE_PATTERN 处理）
    re.compile(r'(\d+)\s*之\d+$'),
    # 末尾纯数字 2-4 位（优先于带后缀，避免误匹配"3号"）
    re.compile(r'(\d{2,4})$'),
    # 数字+后缀：后缀不纳入house值（如"3铺"→house="3"而非"3铺"），含"号"用于1位数字+号
    re.compile(r'(\d+)\s*(?:' + _HOUSE_SUFFIX + r'|号)'),
    # 数字+字母+字母（如 25AF、11KL、1505AB），早于"数字+字母"避免截断
    re.compile(r'(\d+[A-Za-z]{2,})'),
    # 数字+字母（如 101A）
    re.compile(r'(\d+[A-Za-z])'),
]

# 判断 "area + X号" 后面是否只跟了商铺/档/室/房/户等后缀（无其他结构信息）。
# 例如"春树里104号商铺"中 roadno_part='104号'，remaining='商铺'，此时"104"应作为房号。
# 同步 _HOUSE_SUFFIX 扩展，增加 房屋/厂房/专柜/店/教师宿舍/宿舍/杂物间/夹层/教室/裙楼 等后缀类型
# 扩展：增加 商店（第X号商店）和 [一-龥]档（16号肉档/36-37号鱼档 等市场摊位类）
# 注意：后缀为必需匹配（去掉?），避免空remaining也匹配导致"X号"被误识别为房号
# 例如"三坊67号"中remaining=''，不应匹配本模式，"67号"应是roadno而非house
_HOUSE_ONLY_SUFFIX_PATTERN = re.compile(
    r'^[、，,（）()\s]*(?:商铺|店铺|商店|号铺|铺位|铺面|档铺|教师宿舍|杂物间|房间|房屋|厂房|柜台|专柜|档口|裙楼|夹层|教室|宿舍|埔|铺|号档|[一-龥]档|档|室|房|户|间|柜|店)[、，,（）()\s]*$'
)

# ---- 预编译正则：原 _extract_area_roadno_structure 内每次编译 ----
# 修改：允许 roadno_part 前导字母（如 A17-3号、A137号）和多段横杠连接（如 102-103-2号）
# 避免前导字母被留在 area_part 中导致 house 提取不完整
# V9扩展：连接符支持点号/波浪线（如 104.105号、1030~1032号），避免
# "新华保险大厦1030~1032号"中"1030~"残留在 area_part
_AREA_ROADNO_PATTERN = re.compile(r'(.+?)((?:[A-Za-z]?\d+(?:[-－/.~]\d+)*)号)(.*)$')

# ---- 预编译正则：原 _match_plain_roadno_after_kw 内每次编译 ----
_ROADNO_AFTER_KW_DIGIT_PATTERN = re.compile(r'(\d+(?:[-－/]\d+)?)')
_STRUCTURE_AFTER_ROADNO_PATTERN = re.compile(
    r'^(?:栋|幢|座|楼|层|号楼|塔楼|单元|梯)'
)
_STRUCTURE_PREFIX_PATTERN = re.compile(
    r'^(?:' + HARD_BOUNDARY_KEYWORDS + r'|' + SOFT_BOUNDARY_KEYWORDS + r')'
)

# ---- 预编译正则：原 _parse_single 内每条地址重复编译 ----
_AREA_BLDG_UNIT_TAIL_PATTERN = re.compile(r'(栋|幢|座|号楼|单元|梯|层|楼|F)$')
_STRUCT_IN_MIDDLE_PATTERN = re.compile(r'(?:号楼|塔楼|单元|栋|幢|座|层|楼|F|梯)')
_ROAD_NAME_PREFIX_KWS = {'园', '苑', '村', '坊', '里', '巷', '弄'}
_ROAD_DIRECTION_KWS = {'东', '西', '南', '北', '中', '新', '老', '上', '下', '大', '小'}
_MULTI_ROADNO_PATTERN = re.compile(r'((?:\d+号\s*[、，,]\s*)+\d+号)$')
_MULTI_BLDG_PREFIX_PATTERN = re.compile(r'((?:[A-Za-z]?\d+[、，,])+[A-Za-z]?\d+)$')
_HOUSE_CONNECTOR_PATTERN = re.compile(r'[\-－/\\]+$')
# area以房屋/建筑物关键字结尾时，"X号"是房号而非门牌号。
# 扩展：增加 楼/厦/堂/馆/轩/舍/宿 等建筑物结尾关键字，
# 例如"西丽体育中心综合楼14号"中"综合楼"以"楼"结尾，"14号"是房号。
# V9扩展：增加 市场/商城/广场等经营场所结尾字（场/城/寓/店/排/区/位/面/铺/档），
# 覆盖"上川市场1019号""枫叶国际公寓101号""润展服装城2504号""日用品店69号"
# "D排18号""A区53131号""档位77号""铺面114号""西湖苑商铺110号""猪肉档13号"等
# 场景——场所/摊位名后的"X号"是铺位号（房号）而非门牌号。
# 特例（防止误判）：
#   1. "档口/铺口"结尾（档+口/铺+口）→"口"单独不在白名单（"路口X号"是门牌号），
#      仅"档口/铺口"整体视为场所后缀。
#   2. 建筑物字+中文数字结尾（如"厂房一"）→中文数字是厂房附号，
#      前一位是白名单字时视为场所结尾（"新永成厂房一305号"中305是房号）。
_HOUSE_ROOM_SUFFIX_PATTERN = re.compile(
    r'(?:[房屋室楼厦堂馆轩舍宿铺档位面场城寓店排区][一二三四五六七八九十]?|[档铺]口)$'
)
# 修改：允许前导字母和多段横杠连接（如 A17-3、A137、102-103-2）
# 用于 _extract_area_roadno_structure 中把 roadno_part 转换为 house 的场景
# V9扩展：连接符支持点号/波浪线（如 1030~1032号、104.105号），
# 与 _AREA_ROADNO_PATTERN 保持一致，避免从 roadno_part 提取房号时截断
_HOUSE_DIGIT_PATTERN = re.compile(r'([A-Za-z]?\d+(?:[-－/.~]\d+)*)')
# area 是"数字+号"格式检查：在 house first 分支中，当 area 本身是"数字+号"时，
# 说明是"X号Y号"模式（如"30号103号"），area 是门牌号(roadno)而非 area，
# 当前 house 是房号。例如"30号103号"中 area="30号" → roadno="30号" house="103"
_AREA_AS_ROADNO_PATTERN = re.compile(r'^[A-Za-z]?\d+(?:[-－/]\d+)*号$')
_NORMALIZE_WHITESPACE_PATTERN = re.compile(r'\s+')
_PURE_ALPHA_PATTERN = re.compile(r'^[A-Za-z]+$')
_ALPHA_DIGIT_PATTERN = re.compile(r'^[A-Za-z]\d+$')

# 预处理：剥离末尾的括号备注（仅限办公/入驻XXX/办公场所等）和句号
# 注意：保留房号内的括号内容如 (03)（A-3501(03) 的房号一部分）
# 注意：入驻备注可能含嵌套括号（如"(入驻XX(深圳)有限公司)"），需贪婪匹配
# 扩展：支持 (办公场所)/(办公住所)/(办公地址)/(一照多址企业)/(仅办公) 等备注类型
_BRACKET_NOTE_PATTERN = re.compile(
    r'[(（](?:入驻.*|仅限办公|仅限[^()]*|仅办公|办公(?:场所|住所|地址)|一照多址企业)[)）]\s*$'
)
_TRAILING_PERIOD_PATTERN = re.compile(r'[。.]+\s*$')

# 通用末尾括号备注剥离：剥离非房号相关的括号备注（如位置说明、园区名等），
# 但保留房号相关括号（纯数字如(03)、数字+后缀如(102铺)）。
# 负向前瞻 (?!\d+\s*(?:后缀)?[)）]) 确保括号内不是"纯数字"或"数字+后缀"组合。
# 扩展：括号内"末尾"含数字+房号后缀时也保留（如 (一楼102铺) 中"102铺"是房号），
# 此类括号内含楼层描述（一楼）+房号（102铺），不能因含"楼"字被误剥离。
# 例如：(2层-3层)→剥离、(珠光创新科技园旁)→剥离、(中佳创意园)→剥离、(03)→保留、(102铺)→保留、(一楼102铺)→保留
_GENERIC_TRAILING_BRACKET_PATTERN = re.compile(
    r'[(（](?!\d+\s*(?:' + _HOUSE_SUFFIX + r')?[)）])'
    r'(?![^()]*?\d+\s*(?:' + _HOUSE_SUFFIX + r')[)）])'
    r'[^()]*[)）]\s*$'
)

# 剥离末尾的位置说明（东侧/西侧/南侧/北侧/旁等），这些不是房号后缀而是位置描述
# 例如"52栋301东侧"→"52栋301"，house=301
_TRAILING_LOCATION_PATTERN = re.compile(r'(?:东侧|西侧|南侧|北侧|旁边|旁)\s*$')

# 剥离房号后的#号：#在地址中常作为房号/门牌号结束符（类似"号"），
# 当#在末尾或#后紧跟房号后缀时，应剥离#使房号能被正确识别。
# 例如：303#→303、119#铺→119铺、45#商铺→45商铺、501B-1#→501B-1
# 注意：不剥离"2#A栋"中的#（#后是字母，非末尾也非后缀），保留为门牌号结束符
_HOUSE_HASH_PATTERN = re.compile(
    r'(\d)#((?:' + _HOUSE_SUFFIX + r')?\s*$)'
)

# 纯数字+连接符模式：用于 _extract_area_roadno_structure 中判断 area_part 是否是
# "数字+连接符"（如"8-"、"1-"），此时 area_part + roadno_part 应整体作为房号而非拆分。
# 例如"8-9号铺"中 area_part="8-"、roadno_part="9号"，应合并为 house="8-9"
_DIGIT_CONNECTOR_PATTERN = re.compile(r'^\d+[-－/]$')

# 路号后房号后缀检查：当 roadno 后面紧跟房号后缀时，"X号"是房号而非门牌号。
# 用于 _extract_road_and_roadno 中丢弃 roadno 让主流程处理为 house。
# 例如"吓坑路8-9号铺"中"8-9号"后面是"铺"，"8-9"是房号而非门牌号
# 同步 _HOUSE_SUFFIX 扩展，增加 教师宿舍/宿舍/杂物间/夹层/教室/裙楼 等后缀类型
# V9扩展：增加 商店（X号商店）和 [一-龥]档（16号肉档/36-37号鱼档 等摊位类）——
# "号"后紧跟"X档"时是市场摊位编号，数字部分是房号
_HOUSE_SUFFIX_AFTER_ROADNO_PATTERN = re.compile(
    r'^(?:商铺|店铺|商店|号铺|铺位|铺面|档铺|教师宿舍|杂物间|房间|房屋|厂房|柜台|专柜|档口|裙楼|夹层|教室|宿舍|埔|铺|号档|[一-龥]档|档|室|房|户|间|柜|店)'
)

# road 与 roadno 之间的"经营场所"关键字检查：当道路关键字与"X号"之间夹着
# 市场/广场/商城/公寓等经营场所名时，"X号"是场所内铺位号（房号）而非道路门牌号。
# 例如"福围中路福海市场1099号"中"福海市场"夹在"路"与"1099号"之间，
# "1099"是福海市场的铺位号；"立新路文源收藏品市场033号"同理。
# 注意：不含"村/园/苑"等居住区关键字——"人民南路罗湖村116号"中"罗湖村116号"
# 的"116号"仍是门牌号（roadno）。
# V9扩展：增加 商铺/店铺——"兴华路西湖苑商铺110号"中"110号"是铺位号而非门牌号，
# "根玉路商铺82号""长富花园临街商铺105号"同理（场所词后紧跟的"X号"是铺位编号）
_PLACE_AFTER_ROAD_PATTERN = re.compile(r'市场|广场|商城|商场|公寓|购物中心|购物广场|商业街|商铺|店铺')

# "字母+数字+号"形式的 roadno（如 D005号）：仅当 road 是场所街（商业街/步行街）时
# 视为铺位号（如"雅园新城商业街D005号"中 D005 是商铺编号）。
_ALPHA_DIGIT_ROADNO_PATTERN = re.compile(r'^[A-Za-z]\d+号$')

# 双门牌号前缀检查：当前"X号"之前的文本已含"数字+号"时，当前号是房号而非门牌号。
# 用于 _extract_road_and_roadno 中识别"号后残缺路名"场景（如"6-5号路临时铺14号"）。
_DOUBLE_ROADNO_PREFIX_PATTERN = re.compile(r'\d号')

# "数字+F"格式检查：用于区分"12F"是房号还是楼层。
# 当"数字F"是末尾（后面无更多结构）时，更可能是房号（如"6栋2单元12F"中"12F"是房号）；
# 当"数字F"后面还有房号时，是楼层（如"3F502"中"3F"是楼层，"502"是房号）。
# 在 _parse_tail_after_bldg/_parse_tail_after_unit 中，当 floor 和 house 匹配相同位置
# 且 floor 是"数字F"格式时，优先 house。
_FLOOR_F_PATTERN = re.compile(r'\d+F$')


class RuleBasedAddressTaggingEngine:
    """
    基于规则的地址12级拆分引擎。

    Attributes:
        output_fields: 输出字段列表，与现有12级模型保持一致。
    """

    def __init__(self):
        self.output_fields = OUTPUT_FIELDS

    # -------------------- 公共接口 --------------------

    def parse(self, addresses: List[str]) -> List[Dict[str, Any]]:
        """
        批量解析地址。

        Args:
            addresses: 地址字符串列表。

        Returns:
            List[Dict]: 每个地址对应一个字典，包含 original_address 和12级字段。
        """
        return [self._parse_single(addr) for addr in addresses]

    def parse_single(self, address: str) -> Dict[str, Any]:
        """解析单条地址。"""
        return self._parse_single(address)

    # -------------------- 内部解析 --------------------

    def _parse_single(self, address: str) -> Dict[str, Any]:
        addr = (address or '').strip()
        # 归一化内部空白：制表符、多个空格等统一为单个空格
        addr = _NORMALIZE_WHITESPACE_PATTERN.sub(' ', addr)
        # 预处理：剥离末尾的括号备注和句号
        # 注意：保留房号内的括号内容如 (03)（A-3501(03) 的房号一部分）
        # 注意：入驻备注可能含嵌套括号（如"(入驻XX(深圳)有限公司)"），需贪婪匹配
        # 顺序：特定备注→通用括号备注→句号→位置说明→房号后的#
        addr = _BRACKET_NOTE_PATTERN.sub('', addr)
        addr = _GENERIC_TRAILING_BRACKET_PATTERN.sub('', addr)
        addr = _TRAILING_PERIOD_PATTERN.sub('', addr)
        addr = _TRAILING_LOCATION_PATTERN.sub('', addr)
        addr = _HOUSE_HASH_PATTERN.sub(r'\1\2', addr)
        result = {'original_address': addr}

        if not addr:
            for field in self.output_fields:
                result[field] = ''
            return result

        rest = addr

        # 行政区划顺序切分（使用预编译正则，避免每条地址重复编译）
        for field, patterns in _ADMIN_PATTERNS:
            value, rest = self._consume_first(rest, patterns[0])
            result[field] = value

        # street：优先"街道"、其次"镇"、"乡"，按优先级匹配
        street, rest = self._consume_best(rest, _STREET_PATTERNS)
        result['street'] = street

        # community：优先"社区"、其次"村"、"居委会"，按优先级匹配
        community, rest = self._consume_best(rest, _COMMUNITY_PATTERNS)
        result['community'] = community

        # 道路与门牌号（road 可能附带 area 前缀）
        area_prefix, road, roadno, rest = self._extract_road_and_roadno(rest)
        result['road'] = road
        result['roadno'] = roadno

        # 在剩余文本中提取 area/roadno(无道路名时)/bldg/unit/floor/house
        area, extra_roadno, bldg, unit, floor, house = self._extract_structure(rest)

        # 如果 road 提取阶段已经识别出 area 前缀，合并进去
        if area_prefix:
            area = (area_prefix + area).strip('、，,（）()')

        # 无道路名时，将从 area 后提取到的门牌号作为 roadno
        if not roadno and extra_roadno:
            roadno = extra_roadno
        # 当 roadno 已存在时，extra_roadno 实际是房号（如"18号101号"中"101号"是房号），
        # 将 extra_roadno 中的数字部分作为 house
        elif roadno and extra_roadno and not house:
            house_digit = _HOUSE_DIGIT_PATTERN.match(extra_roadno)
            if house_digit:
                house = house_digit.group(1)

        # area 长度控制
        area = self._trim_overlong_area(area)
        # 当 area 过长且无明确关键字时，尝试拆分出楼栋号
        area, bldg = self._split_area_if_overlong(area, bldg)
        # 清理 area 中可能残留的行政区划前缀（如地址本身重复导致）
        area = self._clean_area_admin_residue(area)
        # 清理 area 中冗余的多门牌号序列（如"马坜新村1号、2号、3号..."）
        area = self._clean_multi_roadno_in_area(area)
        # 单字 area 兜底：长度为1时一律置空。
        # 单字 area 都是切分错误残留（如"栋"/"楼"/"东"/"南"/"-"/" "/"A"/"5"/"研"等），
        # 不存在合法的单字语义片区（即使是"村/园/区/城/阁/湾/洲"等关键字，
        # 单独一个字也无法表达完整 POI 名，通常是道路名/POI 名被切碎后的残留）。
        if len(area) <= 1:
            area = ''

        result.update({
            'roadno': roadno,
            'area': area,
            'bldg': bldg,
            'unit': unit,
            'floor': floor,
            'house': house,
        })
        return result

    @staticmethod
    def _consume_first(text: str, pattern: re.Pattern) -> tuple:
        """使用单个正则匹配并消费。"""
        m = pattern.match(text)
        if m:
            return m.group(1), text[m.end():]
        return '', text

    @staticmethod
    def _consume_best(text: str, patterns: List[re.Pattern]) -> tuple:
        """
        尝试多个正则，按列表顺序返回第一个匹配成功的结果并消费。
        用于需要按优先级匹配的场景。
        """
        for p in patterns:
            m = p.match(text)
            if m:
                return m.group(1), text[m.end():]
        return '', text

    @staticmethod
    def _consume_longest(text: str, patterns: List[re.Pattern]) -> tuple:
        """
        尝试多个正则，返回匹配长度最长且优先级最高的结果并消费。
        用于 street/community 等存在歧义后缀的场景（如"街道"优先于"镇"，
        同时避免"鹅埠镇街道"被截断为"鹅埠镇"）。
        """
        best_value = ''
        best_end = 0
        best_idx = len(patterns)
        for idx, p in enumerate(patterns):
            m = p.match(text)
            if m:
                end = m.end()
                value = m.group(1)
                # 优先按匹配长度，其次按模式顺序
                if end > best_end or (end == best_end and idx < best_idx):
                    best_value = value
                    best_end = end
                    best_idx = idx
        if best_end > 0:
            return best_value, text[best_end:]
        return '', text

    def _extract_road_and_roadno(self, text: str) -> tuple:
        """
        以 roadno 为锚点提取 road，并识别 road 之前的 area 前缀。

        算法：
            1. 找到所有道路关键字和门牌号位置。
            2. 从右向左遍历道路关键字，寻找"后面有 roadno"的关键字作为 road 终点。
            3. 在该关键字之前找 area/楼栋边界，拆分 area_prefix 与 road。
            4. 配对 roadno 为道路关键字之后、下一个关键字/楼栋之前的第一个 roadno。

        Returns:
            (area_prefix, road, roadno, remaining)
        """
        if not text:
            return '', '', '', text

        roadno_matches = list(ROADNO_PATTERN.finditer(text))
        road_kw_matches = list(ROAD_KEYWORD_PATTERN.finditer(text))

        if not road_kw_matches:
            # 无道路关键字，整段保留给后续处理
            return '', '', '', text

        # 从右向左找：优先选后面带 roadno 的道路关键字
        target_kw = None
        paired_roadno = None
        for kw in reversed(road_kw_matches):
            kw_end = kw.end()
            # 下一个道路关键字的起始位置
            next_kw_start = len(text)
            for next_kw in road_kw_matches:
                if next_kw.start() > kw.start():
                    next_kw_start = next_kw.start()
                    break

            for rn in roadno_matches:
                if kw_end <= rn.start() < next_kw_start:
                    target_kw = kw
                    paired_roadno = rn
                    break
            if target_kw:
                break

        if target_kw is None:
            # 没有道路关键字后紧跟 roadno，取最后一个道路关键字
            target_kw = road_kw_matches[-1]
            for rn in roadno_matches:
                if rn.start() > target_kw.end():
                    paired_roadno = rn
                    break

        kw_start = target_kw.start()
        kw_end = target_kw.end()

        # 在道路关键字之前找有效边界
        area_prefix, road_start = self._find_road_boundary(text, kw_start)

        road = text[road_start:kw_end]

        # 提取 roadno 并更新剩余文本
        roadno = ''
        remaining = text[kw_end:]
        if paired_roadno and paired_roadno.start() >= kw_end:
            # road 和 roadno 之间可能存在 area 文本（如"人民南路罗湖村116号"中的"罗湖村"，
            # "丽康路珍果园果场1号"中的"珍果园果场"），必须保留到 remaining 中，
            # 由 _extract_structure 提取为 area，否则 area 会被丢失。
            middle = text[kw_end:paired_roadno.start()]

            # 检查 middle 中是否包含楼栋/单元/楼层等结构关键字（栋/幢/座/号楼/单元/梯/层/楼/F）。
            # 若有，说明 "X号" 是 house 而非 roadno（如"爱国路东湖公园杜鹃园宿舍2栋5号"
            # 中 "5号" 是房号），丢弃 roadno，让 _extract_structure 处理为 house。
            # 注意：不把单独的"号"作为判定依据，避免"和平路1019号"等正常 case 被误判。
            if middle and _STRUCT_IN_MIDDLE_PATTERN.search(middle):
                roadno = ''
                remaining = text[kw_end:]
            else:
                # 检查 roadno 后面是否紧跟"楼"字（"X号楼"是楼栋号而非门牌号）。
                # 例如"振兴路1-3号楼101"中"1-3号楼"应作为 bldg 整体识别，
                # 而非把"1-3号"识别为 roadno 后残留"楼"到 area。
                # 该判断只在 roadno 紧跟"楼"时触发，不影响"X号定点/楼栋"等正常 case。
                after_roadno = text[paired_roadno.end():]
                if after_roadno.startswith('楼'):
                    roadno = ''
                    remaining = text[kw_end:]
                # 检查 roadno 后面是否紧跟房号后缀（商铺/铺/档/肉档/商店/室/房/户/房屋/厂房/专柜/店等）。
                # 若有，说明"X号"是房号而非门牌号（如"吓坑路8-9号铺""中环路东二市场16号肉档"），
                # 丢弃 roadno，让 _extract_structure 处理为 house。
                elif _HOUSE_SUFFIX_AFTER_ROADNO_PATTERN.match(after_roadno):
                    roadno = ''
                    remaining = text[kw_end:]
                # 检查道路关键字与 roadno 之间是否夹着经营场所（市场/广场/商城/公寓等）。
                # 若有，说明"X号"是场所内铺位号（房号）而非道路门牌号，
                # 如"福围中路福海市场1099号""立新路文源收藏品市场033号"。
                # 注意：不含"村/园/苑"等居住区，"人民南路罗湖村116号"仍是 roadno。
                elif middle and _PLACE_AFTER_ROAD_PATTERN.search(middle):
                    roadno = ''
                    remaining = text[kw_end:]
                # 场所街（商业街/步行街）后的"字母+数字+号"是铺位号（房号）而非门牌号。
                # 如"雅园新城商业街D005号"中 D005 是商铺编号；
                # 真正道路的"字母门牌号"极罕见（如"振兴路A137号"仍按 roadno 处理）。
                elif (road.endswith(('商业街', '步行街'))
                        and _ALPHA_DIGIT_ROADNO_PATTERN.match(paired_roadno.group(1))):
                    roadno = ''
                    remaining = text[kw_end:]
                # 双门牌号检查：当前 roadno 之前的文本已存在"数字+号"时，
                # 说明当前"X号"是第二个号（房号）而非门牌号。
                # 例如"景田路6-5号路临时铺14号"中"6-5号"在残缺路名"路"之前，
                # 末尾"14号"是临时铺的铺位号，应交由 _extract_structure 处理为 house。
                # 正常地址道路关键字在门牌号之前（paired 取第一个号），不会触发本检查；
                # 触发场景仅限"号后残缺单字路名"（如"6-5号路"）等切分异常。
                elif _DOUBLE_ROADNO_PREFIX_PATTERN.search(text[:paired_roadno.start()]):
                    roadno = ''
                    remaining = text[kw_end:]
                else:
                    roadno = paired_roadno.group(1)
                    remaining = middle + text[paired_roadno.end():]
        else:
            # 门牌号可能不带"号"，如"和平路1019侨社大院..."
            # 此时尝试在道路关键字后直接消费数字编号
            plain_rn = self._match_plain_roadno_after_kw(remaining)
            if plain_rn:
                roadno = plain_rn
                remaining = remaining[len(plain_rn):]

        return area_prefix, road, roadno, remaining

    def _match_plain_roadno_after_kw(self, text: str) -> str:
        """
        在道路关键字之后尝试匹配不带"号"的门牌号。
        仅当后续文本明显是 area/楼栋/单元/楼层/末尾时才消费，避免吞掉 house。
        """
        if not text:
            return ''

        # 匹配开头的一个数字（可带横杠/斜杠后缀）
        m = _ROADNO_AFTER_KW_DIGIT_PATTERN.match(text)
        if not m:
            return ''

        roadno_candidate = m.group(1)
        after = text[m.end():]

        # 如果后续为空，直接作为 roadno
        if not after:
            return roadno_candidate

        # 如果 after 以楼栋/单元/楼层等结构关键字开头，说明数字是楼栋号而非门牌号，
        # 必须返回 '' 让 BLDG_PATTERN/UNIT_PATTERN/FLOOR_PATTERN 处理。
        # 例如 "民福路12栋351" 中 "12" 是楼栋号，"12栋" 应作为 bldg，
        # 不应将 "12" 识别为 roadno 而把 "栋" 残留到 area。
        # 该判断必须在 structure_prefix 检查之前，避免 "栋/幢/座/楼/层"
        # 被 SOFT_BOUNDARY 误识别为门牌号边界。
        if _STRUCTURE_AFTER_ROADNO_PATTERN.match(after):
            return ''

        # 如果后续以area/结构关键字开头，说明是门牌号
        # 结构关键字：栋/幢/座/号楼/塔楼/单元/层/楼/F
        if _STRUCTURE_PREFIX_PATTERN.match(after):
            return roadno_candidate

        # 如果后续以"号"开头，则合并到 roadno（如"1019号"已被上一步捕获，这里是防御性处理）
        if after.startswith('号'):
            return roadno_candidate

        # 如果后续包含 area 关键字（如"高新北文体中心101"中的"中心"），
        # 说明数字后是 area/建筑物名，数字应为门牌号而非房号。
        # 否则会把数字误识别为 house（如"13-9"被识别为 house，area 丢失）。
        if AREA_KEYWORD_PATTERN.search(after):
            return roadno_candidate

        return ''

    def _find_road_boundary(self, text: str, kw_start: int) -> tuple:
        """
        在目标道路关键字起始位置之前找 area/楼栋边界。

        算法：
            - 同时收集硬边界和软边界，选择离道路关键字最近（最靠右）的有效边界。
              这样可避免"怡心广场C座怡心街"被错误拆成 area='怡心广场'、road='C座怡心街'。
            - 当边界结束位置与道路关键字起始位置重合（distance == 0）时：
                - 单独的"号"字或"X号楼"中的"楼"视为有效边界，避免 roadno 被吞入 road。
                - 其他情况视为道路名的一部分，继续向前找下一个边界。

        Returns:
            (area_prefix, road_start)
        """
        search_text = text[:kw_start]

        # 收集所有候选边界（硬边界 + 软边界），按结束位置降序排列
        candidates = []
        for boundary_pattern in [HARD_BOUNDARY_PATTERN, SOFT_BOUNDARY_PATTERN]:
            for m in boundary_pattern.finditer(search_text):
                if m.end() > kw_start:
                    break
                candidates.append((m.end(), m))

        # 按结束位置从大到小排序（离 keyword 近的优先）
        candidates.sort(key=lambda x: x[0], reverse=True)

        for _, m in candidates:
            boundary_text = m.group(0)
            distance = kw_start - m.end()
            if distance == 0:
                # 单独"号"字且紧贴道路关键字，说明前面是门牌号，应作为边界
                if boundary_text == '号':
                    return text[:m.end()], m.end()
                # "X号楼"中的"楼"与道路关键字"路"相邻时，说明前面是楼栋号，应作为边界
                if boundary_text in ('楼', '号楼'):
                    return text[:m.end()], m.end()
                # 否则可能是道路名的一部分，继续向前找
                continue
            # 距离>0时，检查是否为"area关键字+方向字+道路关键字"的道路名结构
            # 例如"桃园东路"：园(边界) + 东(间隔) + 路(道路关键字)，应视为道路名整体
            if distance == 1:
                middle_char = text[m.end():kw_start]
                if (boundary_text in _ROAD_NAME_PREFIX_KWS
                        and middle_char in _ROAD_DIRECTION_KWS):
                    continue
            # 有效边界
            return text[:m.end()], m.end()

        return '', 0

    def _extract_structure(self, text: str) -> tuple:
        """
        在道路/门牌号之后的文本中提取 area/roadno/bldg/unit/floor/house。

        Returns:
            (area, roadno, bldg, unit, floor, house)
        """
        if not text:
            return '', '', '', '', '', ''

        # 无道路名时：尝试 "area + 数字号 + 楼栋/单元/楼层/房号" 结构
        # _extract_area_roadno_structure 内部会检查 area_part 是否包含结构关键字，
        # 若包含（如"华清园B栋旁集装箱"中的"B栋"）则返回 None，避免 bldg 被吞入 area。
        fallback = self._extract_area_roadno_structure(text)
        if fallback:
            return fallback

        # 查找各类终止符位置
        bldg_match = BLDG_PATTERN.search(text)
        unit_match = UNIT_PATTERN.search(text)
        floor_match = FLOOR_PATTERN.search(text)

        # 从末尾查找 house（优先特殊描述，再按模式）
        house_match, house_start, house_value = self._find_house(text)

        # 收集候选终止符
        candidates = []
        if bldg_match:
            candidates.append((bldg_match.start(), 'bldg', bldg_match))
        if unit_match:
            candidates.append((unit_match.start(), 'unit', unit_match))
        if floor_match:
            candidates.append((floor_match.start(), 'floor', floor_match))
        if house_match:
            candidates.append((house_start, 'house', house_match))

        if not candidates:
            # 无任何终止符，全部作为 area
            return text, '', '', '', '', ''

        candidates.sort(key=lambda x: x[0])
        first_start, first_type, first_match = candidates[0]

        area = text[:first_start].strip('、，,（）()')

        if first_type == 'bldg':
            bldg = first_match.group(1).strip('、，,（）()')
            # 将 bldg 前可能存在的"数字、数字、"多栋序列并入 bldg
            area, bldg = self._merge_multi_building_prefix(area, bldg)
            after = text[first_match.end():]
            unit, floor, house = self._parse_tail_after_bldg(after)
            return area, '', bldg, unit, floor, house
        elif first_type == 'unit':
            unit = first_match.group(1).strip('、，,（）()')
            after = text[first_match.end():]
            # _parse_tail_after_unit 返回 (bldg, floor, house)，
            # 因为单元号后可能紧跟楼栋号（如"A单元B栋502"中"B栋"）。
            # 返回顺序与 bldg 分支一致：(area, extra_roadno, bldg, unit, floor, house)。
            # 注意 bldg 必须放在第 3 位，否则会被错误赋值给 extra_roadno。
            bldg, floor, house = self._parse_tail_after_unit(after)
            return area, '', bldg, unit, floor, house
        elif first_type == 'floor':
            floor = first_match.group(1).strip('、，,（）()')
            after = text[first_match.end():]
            area, house = self._house_from_tail(after, area)
            # 注意：house 为空就是空，不要用 floor 兜底。
            # 否则会把"1栋负3层"的"负3层"误识别为 house（house 不应是楼层描述）。
            return area, '', '', '', floor, house
        else:  # house first
            house = house_value.strip('、，,')
            # "数字+号"门牌号判断：当house通过"号"匹配（house值后紧跟"号"），
            # 且candidates中没有bldg/unit/floor结构，且"号"后面没有房号后缀，
            # 且area不以建筑物关键字结尾时，"数字+号"是门牌号（roadno）而非房号（house）。
            # 例如"下企沙村33号"中社区名已消耗"下企沙村"，剩余"33号"进入此分支，
            #   "33号"应是roadno而非house（area为空，"号"后面无后缀）。
            # 而"3号铺"中"3号"是house（"号"后面有"铺"后缀），不识别为roadno。
            # 而"西丽体育中心综合楼14号"中"14号"是house（area以"楼"结尾，是建筑物名）。
            # 而"2栋4号"中"4号"是house（前面有"2栋"bldg），不会走到此分支（走bldg分支）。
            # 例外：house 以字母开头（如"商业街D005号"中 D005）时是铺位编号，
            #   门牌号极少字母开头，保持 house 不转为 roadno。
            house_end_pos = house_start + len(house_value)
            if (house_end_pos < len(text) and text[house_end_pos] == '号'
                    and not house[:1].isalpha()
                    and not any(t in ('bldg', 'unit', 'floor') for _, t, _ in candidates)):
                after_hao = text[house_end_pos + 1:]
                if (not _HOUSE_SUFFIX_AFTER_ROADNO_PATTERN.match(after_hao)
                        and not _HOUSE_ROOM_SUFFIX_PATTERN.search(area)):
                    # "X号Y号"模式：area 本身是"数字+号"格式时，area 是门牌号(roadno)，
                    # 当前 house 是房号。例如"30号103号"中 area="30号" → roadno="30号" house="103"
                    if _AREA_AS_ROADNO_PATTERN.match(area):
                        return '', area, '', '', '', house
                    roadno = house + '号'
                    return area, roadno, '', '', '', ''
            return area, '', '', '', '', house

    def _parse_tail_after_bldg(self, text: str) -> tuple:
        """
        在楼栋号之后解析 unit/floor/house。

        特殊处理："X栋Y座"结构中，Y座应识别为 unit 而非 bldg
        （如"3栋5座101"中 unit='5座'，"3栋B座101"中 unit='B座'）。
        因此在 bldg 之后，UNIT_PATTERN 之外再匹配 ZUO_AS_UNIT_PATTERN
        （数字/字母+座），取最早出现者作为 unit 候选。
        单独的"X座"在主流程 _extract_structure 中仍由 BLDG_PATTERN 识别为 bldg。

        增加 bldg 候选：当 bldg 之后的文本中还有 bldg 匹配时（如"C5栋厂房C5栋5层-511室"
        中第二个"C5栋"），需优先走 bldg 分支递归处理，避免 house（字母+数字模式匹配"C5"）
        抢先于 bldg 被选中。但排除与 unit_match（含 ZUO_AS_UNIT_PATTERN）重叠的 bldg
        （如"5座"既是 unit 又是 bldg，优先 unit）。
        """
        if not text:
            return '', '', ''

        unit_match = UNIT_PATTERN.search(text)
        # bldg 之后的"X座"作为 unit 候选（如"3栋5座"中的"5座"）
        zuo_match = ZUO_AS_UNIT_PATTERN.search(text)
        # 取最早出现的作为 unit 候选（若同时存在）
        if unit_match and zuo_match:
            if zuo_match.start() < unit_match.start():
                unit_match = zuo_match
        elif zuo_match and not unit_match:
            unit_match = zuo_match

        floor_match = FLOOR_PATTERN.search(text)
        bldg_match = BLDG_PATTERN.search(text)
        # 排除与 unit_match（含 zuo_match）重叠的 bldg（如"5座"既是 unit 又是 bldg，优先 unit）
        if bldg_match and unit_match and bldg_match.start() == unit_match.start():
            bldg_match = None
        house_match, house_start, house_value = self._find_house(text)

        # 当 floor 和 house 匹配相同位置且 floor 是"数字+F"格式时，优先 house。
        # "12F"在末尾时更可能是房号（如"6栋2单元12F"），而非楼层。
        # "3F502"中 floor="3F"(start=0) 和 house="502"(start=2) 位置不同，不受影响。
        if (floor_match and house_match
                and floor_match.start() == house_start
                and _FLOOR_F_PATTERN.match(floor_match.group(1))):
            floor_match = None

        candidates = []
        if unit_match:
            candidates.append((unit_match.start(), 'unit', unit_match))
        if floor_match:
            candidates.append((floor_match.start(), 'floor', floor_match))
        if bldg_match:
            candidates.append((bldg_match.start(), 'bldg', bldg_match))
        if house_match:
            candidates.append((house_start, 'house', house_match))

        if not candidates:
            return '', '', ''

        candidates.sort(key=lambda x: x[0])
        _, typ, m = candidates[0]

        if typ == 'unit':
            unit = m.group(1).strip('、，,（）()')
            after = text[m.end():]
            # _parse_tail_after_unit 返回 (bldg, floor, house)。
            # 这里 bldg 已在外层识别，bldg_extra 通常是"X栋A单元B栋"中的"B栋"，
            # 罕见且语义不清，丢弃。
            _, floor, house = self._parse_tail_after_unit(after)
            return unit, floor, house
        elif typ == 'floor':
            floor = m.group(1).strip('、，,（）()')
            after = text[m.end():]
            _, house = self._house_from_tail(after, '')
            # house 为空就是空，不用 floor 兜底（避免楼层被误识别为房号）
            return '', floor, house
        elif typ == 'bldg':
            # bldg 之后的文本递归处理（bldg 值丢弃，因为外层已有 bldg）。
            # 这处理"C5栋厂房C5栋5层-511室"中第二个"C5栋"的情况：
            # 字母+数字模式会匹配"C5"作为 house，但"C5"是第二个"C5栋"的前缀，
            # 应跳过 house 走 bldg 分支，在 bldg 之后继续解析 floor/house。
            after = text[m.end():]
            unit, floor, house = self._parse_tail_after_bldg(after)
            return unit, floor, house
        else:
            return '', '', house_value.strip('、，,')

    def _parse_tail_after_unit(self, text: str) -> tuple:
        """
        在单元号之后解析 bldg/floor/house。

        Returns:
            (bldg, floor, house)
            - bldg：单元号后可能紧跟楼栋号（如"A单元B栋502"中"B栋"），需识别为 bldg。
            - floor/house：常规楼层和房号。
        """
        if not text:
            return '', '', ''

        bldg_match = BLDG_PATTERN.search(text)
        floor_match = FLOOR_PATTERN.search(text)
        house_match, house_start, house_value = self._find_house(text)

        # 当 floor 和 house 匹配相同位置且 floor 是"数字+F"格式时，优先 house。
        # "12F"在末尾时更可能是房号（如"6栋2单元12F"），而非楼层。
        if (floor_match and house_match
                and floor_match.start() == house_start
                and _FLOOR_F_PATTERN.match(floor_match.group(1))):
            floor_match = None

        candidates = []
        if bldg_match:
            candidates.append((bldg_match.start(), 'bldg', bldg_match))
        if floor_match:
            candidates.append((floor_match.start(), 'floor', floor_match))
        if house_match:
            candidates.append((house_start, 'house', house_match))

        if not candidates:
            return '', '', ''

        candidates.sort(key=lambda x: x[0])
        _, typ, m = candidates[0]

        if typ == 'bldg':
            bldg = m.group(1).strip('、，,（）()')
            after = text[m.end():]
            # bldg 之后可能还有 floor/house（如"A单元B栋2层5号"）
            # 递归调用 _parse_tail_after_bldg 拿 floor/house（忽略其返回的 unit，
            # 因为 unit 已识别，重复 unit 罕见且语义不清）。
            _, floor, house = self._parse_tail_after_bldg(after)
            return bldg, floor, house
        elif typ == 'floor':
            floor = m.group(1).strip('、，,（）()')
            after = text[m.end():]
            _, house = self._house_from_tail(after, '')
            # house 为空就是空，不用 floor 兜底（避免楼层被误识别为房号）
            return '', floor, house
        else:
            return '', '', house_value.strip('、，,')

    def _find_house(self, text: str) -> tuple:
        r"""
        在文本中查找 house，返回 (match, start, value)。

        优先按数字模式匹配（房号通常是数字），仅当所有数字模式都不匹配时，
        才回退到特殊描述（如"会议室"、"大堂"等中文描述）。

        模式顺序设计要点：
            1. SPECIAL_HOUSE_PATTERN（如"会议室"、"食堂"）必须放在数字模式之后，
               否则会把"园林集团公司会议室205"的 house 误识别为"会议室"而非"205"。
            2. "末尾纯数字 2-4 位" 必须在 "带后缀" 之前，否则"3号集装箱101"会被
               模式 `(\d+)\s*号` 误匹配为"3"，而非末尾的"101"。
            3. "带后缀"模式保留"号"，用于处理"4号"这类1位数字+号的情况
               （末尾纯数字模式要求2-4位，1位数字无法匹配，需靠带后缀模式补足）。
            4. house 不应包含中文，所有数字模式均只捕获数字/字母部分。
        """
        # 使用预编译的 HOUSE_PATTERNS，避免每条地址重复编译 8 个正则
        for idx, pattern in enumerate(HOUSE_PATTERNS):
            matches = list(pattern.finditer(text))
            if matches:
                # 同一模式取最靠后的匹配
                m = matches[-1]
                value = m.group(1)
                # 模式 0（顿号多房号）每段可带"号"（如"163号、164号"），
                # "号"是段后缀标记不纳入房号值，统一去除
                if idx == 0:
                    value = value.replace('号', '')
                return m, m.start(), value

        # 2. 数字模式都未匹配时，回退到特殊描述（如"会议室"、"大堂"等中文房号描述）
        # 这类房号是纯中文，仅在没有数字房号时才使用
        special_match = SPECIAL_HOUSE_PATTERN.search(text)
        if special_match:
            return special_match, special_match.start(), special_match.group(1)

        return None, -1, ''

    @staticmethod
    def _merge_multi_building_prefix(area: str, bldg: str) -> tuple:
        """
        将 area 末尾类似"7、8、9、10、"的多栋编号序列并入 bldg。
        例如 area='中骏蓝湾翠岭花园一期7、8、9、10、13、14、15',
             bldg='16栋' -> area='中骏蓝湾翠岭花园一期', bldg='7、8、9、10、13、14、15、16栋'。
        """
        if not area or not bldg:
            return area, bldg

        # 匹配 area 末尾的多栋编号序列（后面紧跟 bldg）。
        # 支持两种形式：
        #   1. "7、8、9、10、"（末尾带分隔符，未 strip 前）
        #   2. "B1、B2、B3、B4、B5、B6、B7"（末尾分隔符已被 strip）
        m = _MULTI_BLDG_PREFIX_PATTERN.search(area)
        if m:
            prefix = m.group(1)
            area = area[:m.start()].strip('、，,')
            bldg = prefix + '、' + bldg if not prefix.endswith(('、', '，', ',')) else prefix + bldg

        return area, bldg

    @staticmethod
    def _split_area_if_overlong(area: str, bldg: str) -> tuple:
        """
        当 area 过长且无明确 area 关键字时，从后向前截断，把楼栋号部分拆给 bldg。
        """
        if not area or len(area) <= 25:
            return area, bldg

        # 如果 area 已经包含明确 area 关键字，通常不再拆分
        if AREA_KEYWORD_PATTERN.search(area):
            return area, bldg

        # 从后向前查找第一个软边界（楼栋/单元/楼层等），截断 area
        last_pos = -1
        for m in SOFT_BOUNDARY_PATTERN.finditer(area):
            last_pos = m.end()
        if last_pos > 0:
            bldg_part = area[last_pos:].strip('、，,（）()')
            area = area[:last_pos].strip('、，,（）()')
            if bldg_part and not bldg:
                bldg = bldg_part
        return area, bldg

    def _house_from_tail(self, tail: str, area_prefix: str) -> tuple:
        """
        在 floor/bldg 之后的剩余文本中识别 house，并将 house 之前的文本追加到 area。

        Returns:
            (area, house)
        """
        if not tail:
            return area_prefix, ''

        house_match, house_start, house_value = self._find_house(tail)
        if house_match:
            # house 之前的连接符（-/－/ 等）应剥离，不追加到 area。
            # 例如"深港融合商业街-10A"中 house="10A"，"-"是连接符，area 不应残留"-"。
            before_house = tail[:house_start]
            before_house = _HOUSE_CONNECTOR_PATTERN.sub('', before_house)
            area_prefix = (area_prefix + before_house).strip('、，,（）() ')
            return area_prefix, house_value.strip('、，,')

        # 没有识别到 house，把剩余内容都作为 house（兜底）
        return area_prefix, tail.strip('、，,（）()')

    def _trim_overlong_area(self, area: str) -> str:
        """
        area 长度控制：超过20字且无明确 area 关键字时，从后向前截断。
        """
        if len(area) <= 20:
            return area

        if AREA_KEYWORD_PATTERN.search(area):
            return area

        # 从后向前找 area 关键字
        last_kw_end = -1
        for m in AREA_KEYWORD_PATTERN.finditer(area):
            last_kw_end = m.end()

        if last_kw_end > 0:
            return area[:last_kw_end].strip('、，,（）()')

        return area

    @staticmethod
    def _clean_area_admin_residue(area: str) -> str:
        """
        清理 area 中意外残留的行政区划前缀。

        某些地址在 community 之后再次包含“广东省/深圳市/XX区/XX街道/XX社区”
        等行政区划描述（通常是地址数据重复或冗余），导致 area 过长且含无关信息。
        本方法仅切掉 area 开头明确的行政区划片段，保留后面的真实 poi/area。
        """
        if not area:
            return area

        cleaned = area
        # 循环切掉开头的行政区划残留，避免一次只切一个
        while True:
            m = AREA_ADMIN_RESIDUE_PATTERN.match(cleaned)
            if not m:
                break
            # 防止把正常 area 关键字（如“XX新村”、“XX社区”本身）切光
            next_part = cleaned[m.end():].strip('、，,（）() ')
            if not next_part:
                break
            cleaned = next_part

        return cleaned

    @staticmethod
    def _clean_multi_roadno_in_area(area: str) -> str:
        """
        清理 area 末尾冗余的多门牌号序列。

        某些地址在 area 后列举多个门牌号（如“马坜新村1号、2号、3号...10号6号502”），
        导致 area 过长。本方法将 area 末尾类似“X号、Y号、Z号”的序列切除，
        保留真实 poi/area 名称。
        """
        if not area:
            return area

        # 匹配末尾的多号序列："1号、2号、3号" 或 "1号,2号,3号"
        m = _MULTI_ROADNO_PATTERN.search(area)
        if m:
            prefix = area[:m.start()].strip('、，,（）() ')
            # 仅当剩余部分仍包含 area 关键字时才切除，防止误切正常 area
            if prefix and AREA_KEYWORD_PATTERN.search(prefix):
                return prefix
        return area

    def _extract_area_roadno_structure(self, text: str) -> tuple:
        """
        无道路名时，尝试提取 "area + 数字号 + 楼栋/单元/楼层/房号" 结构。

        例如：
            富裕新村28号706        -> area=富裕新村, roadno=28号, house=706
            宝龙新村121号B单元606  -> area=宝龙新村, roadno=121号, unit=B单元, house=606
            旱塘仔46号201           -> area=旱塘仔, roadno=46号, house=201
            中航华府花园4号楼3604  -> 已在有楼栋分支处理，这里不匹配

        Returns:
            (area, roadno, bldg, unit, floor, house) 或 None
        """
        # 匹配：area_part + (数字[-数字]?)号 + remaining
        m = _AREA_ROADNO_PATTERN.search(text)
        if not m:
            return None

        area_part, roadno_part, remaining = m.groups()
        area_part = area_part.strip('、，,（）() ')
        if not area_part:
            return None

        # 如果 area 部分已经以楼栋/单元/楼层结尾，说明不应再拆分
        if _AREA_BLDG_UNIT_TAIL_PATTERN.search(area_part):
            return None

        # 如果 roadno_part 后面紧跟"楼"字（"X号楼"是楼栋号而非门牌号），
        # 返回 None 让主流程识别为 bldg。
        # 例如"1-3号楼101"中"1-3号楼"应作为 bldg 整体识别，
        # 而非拆分为 area="1-" + roadno="3号" + 残留"楼"到 area。
        if remaining.startswith('楼'):
            return None

        # 如果 area_part 内部包含楼栋/单元/楼层结构关键字（如"B栋"、"A幢"、"1单元"、"3层"），
        # 说明该结构信息不应被吞入 area，应返回 None 让主流程处理。
        # 例如"华清园B栋旁集装箱1号"：area_part="华清园B栋旁集装箱"包含"B栋"，
        # 返回 None 后由 _extract_structure 主流程识别 area="华清园", bldg="B栋", house="1"。
        if (BLDG_PATTERN.search(area_part) or UNIT_PATTERN.search(area_part)
                or FLOOR_PATTERN.search(area_part)):
            return None

        # area 部分应包含 area 关键字，或者是合理的村/地名缩写
        has_area_kw = bool(AREA_KEYWORD_PATTERN.search(area_part))
        looks_like_place_name = (
            2 <= len(area_part) <= 12
            and not _PURE_ALPHA_PATTERN.match(area_part)
            and not _ALPHA_DIGIT_PATTERN.match(area_part)
        )
        if not has_area_kw and not looks_like_place_name:
            return None

        # 末尾"X号"的歧义处理：
        # - 当 area_part 以"房/屋/室"等房屋关键字结尾且后面无更多结构时，
        #   "X号"是房号而非门牌号（如"东湖公园杜鹃园花圃工作房1号" → house="1"）。
        # - 否则"X号"是门牌号（如"富裕新村28号706" → roadno="28号", house="706"）。
        #   此分支由下方 _extract_tail_structure 继续处理 remaining。
        if not remaining and _HOUSE_ROOM_SUFFIX_PATTERN.search(area_part):
            house_digit = _HOUSE_DIGIT_PATTERN.match(roadno_part)
            if house_digit:
                return area_part, '', '', '', '', house_digit.group(1)

        # 当 area_part 是纯数字+连接符（如"8-"、"1-"）时，
        # "X-Y号" 是房号而非门牌号，area_part + roadno_part 应整体作为房号。
        # 例如"8-9号铺"中 area_part="8-"、roadno_part="9号"，应合并为 house="8-9"。
        # 这是因为 _AREA_ROADNO_PATTERN 的非贪婪匹配会把"8-9号"拆成 area="8-" + roadno="9号"，
        # 需在此处修正。
        if _DIGIT_CONNECTOR_PATTERN.match(area_part):
            house_digit = _HOUSE_DIGIT_PATTERN.match(area_part + roadno_part)
            if house_digit:
                return '', '', '', '', '', house_digit.group(1)

        # 当 area_part + "X号" 后面紧跟纯商铺/档/室/房/户后缀（无其他结构）时，
        # "X号"应作为房号而非门牌号。例如：
        #   "春树里104号商铺" -> area='春树里', house='104'
        #   "蓝虹豪苑06号铺"  -> area='蓝虹豪苑', house='06'
        if _HOUSE_ONLY_SUFFIX_PATTERN.match(remaining):
            house_digit = _HOUSE_DIGIT_PATTERN.match(roadno_part)
            if house_digit:
                return area_part, '', '', '', '', house_digit.group(1)

        # 在 remaining 中继续提取 area/楼栋/单元/楼层/房号
        # tail_area 是 remaining 中 bldg 前的 area 文本（如"金田工业区5栋"中的"金田工业区"）
        tail_area, bldg, unit, floor, house = self._extract_tail_structure(remaining)

        # 如果 tail_area 包含 area 关键字（如"金田工业区"），用 tail_area 替换 area_part。
        # 因为 tail_area 离 bldg 更近，更可能是真实的 POI 名
        # （如"坳下村128号金田工业区5栋"中"金田工业区"比"坳下村"更具体）。
        # 否则丢弃 tail_area（可能是无意义残留如"楼"）。
        if tail_area and AREA_KEYWORD_PATTERN.search(tail_area):
            area_part = tail_area

        # 无 area 关键字时，要求 remaining 必须能提取出结构信息，
        # 避免把无意义前缀误当成 area
        if not has_area_kw and not any([bldg, unit, floor, house]):
            return None

        return area_part, roadno_part, bldg, unit, floor, house

    def _extract_tail_structure(self, text: str) -> tuple:
        """
        在门牌号/楼栋号之后的剩余文本中提取 area/bldg/unit/floor/house。

        复用 _extract_structure 的核心逻辑，但已知的 area/roadno 已被切除。
        Returns:
            (area, bldg, unit, floor, house)
        """
        if not text:
            return '', '', '', '', ''

        text = text.strip('、，,（）() ')

        # 查找各类终止符位置
        bldg_match = BLDG_PATTERN.search(text)
        unit_match = UNIT_PATTERN.search(text)
        floor_match = FLOOR_PATTERN.search(text)
        house_match, house_start, house_value = self._find_house(text)

        candidates = []
        if bldg_match:
            candidates.append((bldg_match.start(), 'bldg', bldg_match))
        if unit_match:
            candidates.append((unit_match.start(), 'unit', unit_match))
        if floor_match:
            candidates.append((floor_match.start(), 'floor', floor_match))
        if house_match:
            candidates.append((house_start, 'house', house_match))

        if not candidates:
            # 无任何终止符，全部作为 area
            return text, '', '', '', ''

        candidates.sort(key=lambda x: x[0])
        first_start, first_type, first_match = candidates[0]

        # 终止符之前的文本作为 area（如"金田工业区5栋"中的"金田工业区"）
        area = text[:first_start].strip('、，,（）()')

        if first_type == 'bldg':
            bldg = first_match.group(1).strip('、，,（）()')
            after = text[first_match.end():]
            unit, floor, house = self._parse_tail_after_bldg(after)
            return area, bldg, unit, floor, house
        elif first_type == 'unit':
            unit = first_match.group(1).strip('、，,（）()')
            after = text[first_match.end():]
            # _parse_tail_after_unit 返回 (bldg, floor, house)，
            # 单元号后可能紧跟楼栋号（如"A单元B栋502"中"B栋"）。
            bldg, floor, house = self._parse_tail_after_unit(after)
            return area, bldg, unit, floor, house
        elif first_type == 'floor':
            floor = first_match.group(1).strip('、，,（）()')
            after = text[first_match.end():]
            new_area, house = self._house_from_tail(after, '')
            # floor 之后可能还有 area 残留，合并到 area
            area = (area + new_area).strip('、，,（）()')
            # house 为空就是空，不用 floor 兜底（避免楼层被误识别为房号）
            return area, '', '', floor, house
        else:
            return area, '', '', '', house_value.strip('、，,')
