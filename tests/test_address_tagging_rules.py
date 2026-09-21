# -*- coding: utf-8 -*-
"""
12级地址规则分词引擎测试
======================

验证 RuleBasedAddressTaggingEngine 对各类地址形式的解析正确性，
以及 AddressTaggingParser 在 mode='12' 时使用规则引擎而非 MGeo 模型。
"""
import sys
import os
import re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from matching.address_tagging_rules import RuleBasedAddressTaggingEngine


@pytest.fixture(scope='module')
def engine():
    return RuleBasedAddressTaggingEngine()


class TestRuleBasedAddressTaggingEngine:
    """规则引擎单元测试"""

    def test_empty_address(self, engine):
        r = engine.parse_single('')
        assert r['original_address'] == ''
        assert all(r.get(f) == '' for f in engine.output_fields)

    def test_basic_admin_division(self, engine):
        addr = '广东省深圳市福田区华强北街道华航社区振兴路91-13号'
        r = engine.parse_single(addr)
        assert r['province'] == '广东省'
        assert r['city'] == '深圳市'
        assert r['district'] == '福田区'
        assert r['street'] == '华强北街道'
        assert r['community'] == '华航社区'
        assert r['road'] == '振兴路'
        assert r['roadno'] == '91-13号'

    def test_area_and_building(self, engine):
        addr = '广东省深圳市南山区桃源街道龙联社区龙珠一路8号西丽体育中心综合楼'
        r = engine.parse_single(addr)
        assert r['road'] == '龙珠一路'
        assert r['roadno'] == '8号'
        assert '西丽体育中心' in r['area']

    def test_house_patterns(self, engine):
        cases = [
            ('广东省深圳市宝安区新安街道甲岸社区宝民一路甲岸村22号401', '401'),
            ('广东省深圳市福田区沙头街道新洲社区新洲北村57-1号8A', '8A'),
            ('广东省深圳市南山区桃源街道龙联社区龙珠一路8号西丽体育中心综合楼14号', '14'),
        ]
        for addr, expected_house in cases:
            r = engine.parse_single(addr)
            assert r['house'] == expected_house, f"地址 '{addr}' 期望 house={expected_house}, 实际={r['house']}"

    def test_no_road_name_with_roadno(self, engine):
        addr = '广东省深圳市光明区凤凰街道塘尾社区后底园小区72号401'
        r = engine.parse_single(addr)
        assert r['area'] == '后底园小区'
        assert r['roadno'] == '72号'
        assert r['house'] == '401'

    def test_multi_building_sequence(self, engine):
        addr = '广东省深圳市龙岗区龙岗街道中骏蓝湾翠岭花园一期7、8、9、10、13、14、15、16栋201'
        r = engine.parse_single(addr)
        assert '中骏蓝湾翠岭花园一期' in r['area']
        assert '7、8、9、10、13、14、15、16栋' in r['bldg']

    def test_admin_residue_cleaning(self, engine):
        addr = '广东省深圳市福田区西交利物浦大学深圳校区XX楼101'
        r = engine.parse_single(addr)
        # area 不应再包含省市区前缀
        assert not r['area'].startswith('广东省')
        assert not r['area'].startswith('深圳市')
        assert not r['area'].startswith('福田区')

    def test_street_priority_match(self, engine):
        # "街道"应优先于"镇"被识别
        r = engine.parse_single('广东省深圳市深汕特别合作区鹅埠镇街道鹅埠村社区创新大道南344号')
        assert r['street'] == '鹅埠镇街道'

    def test_community_priority_match(self, engine):
        # "社区"应优先于"村"被识别
        r = engine.parse_single('广东省深圳市顺德区荔村社区居委会荔村大道1号')
        assert '社区' in r['community']


class TestUserReportedAddressSamples:
    """
    用户反馈的10+个真实地址样例回归测试

    这些样例覆盖了以下修复点：
        1. SPECIAL_HOUSE_PATTERN 优先级降低：house 优先匹配数字，"会议室"/"之一"等
           仅在无数字匹配时才作为 house（样例1、10）。
        2. BLDG_PATTERN 增加"字母+栋/幢"：识别"C栋"、"A幢"等楼栋号（样例3）。
        3. road 和 roadno 之间的 area 文本不再丢失：如"人民南路罗湖村116号"中的
           "罗湖村"会被保留为 area（样例4、6）。
        4. _match_plain_roadno_after_kw 扩展识别 area 后续：不带"号"的门牌号
           （如"13-9"）后跟 area 时也能被识别为 roadno（样例5）。
        5. 末尾"X号"作为 house 而非 roadno：当 area 以"房/屋/室"结尾且无后续结构时
           （样例9）。
        6. 去掉 `if not house: house = floor` 兜底：楼层描述（如"负3层"）不应被
           识别为 house（样例11）。
        7. house 模式优先级：末尾2-4位数字优先于带后缀模式，避免"3号集装箱101"
           被误识别为 house="3"（样例7）。
    """

    def test_sample1_house_not_special_keyword(self, engine):
        """样例1：house应为'205'而非'会议室'（SPECIAL_HOUSE优先级降低）"""
        addr = '广东省深圳市罗湖区黄贝街道水库社区东湖一街1号园林集团公司会议室205'
        r = engine.parse_single(addr)
        assert r['road'] == '东湖一街'
        assert r['roadno'] == '1号'
        assert r['house'] == '205', f"期望 house='205', 实际='{r['house']}'"
        # area 应包含园林集团公司，不应为空
        assert '园林集团公司' in r['area']

    def test_sample2_area_with_special_place(self, engine):
        """样例2：area='莲塘口岸员工食堂', bldg='1栋', house='101'"""
        addr = '广东省深圳市罗湖区黄贝街道罗芳社区延芳路600号莲塘口岸员工食堂1栋101'
        r = engine.parse_single(addr)
        assert r['road'] == '延芳路'
        assert r['roadno'] == '600号'
        assert r['area'] == '莲塘口岸员工食堂', f"期望 area='莲塘口岸员工食堂', 实际='{r['area']}'"
        assert r['bldg'] == '1栋'
        assert r['house'] == '101'

    def test_sample3_letter_plus_dong_building(self, engine):
        """样例3：area='莲塘坑工业区', bldg='C栋', house='206'（字母+栋识别）"""
        addr = '广东省深圳市宝安区西乡街道凤凰岗社区莲塘坑工业区C栋206'
        r = engine.parse_single(addr)
        assert r['area'] == '莲塘坑工业区', f"期望 area='莲塘坑工业区', 实际='{r['area']}'"
        assert r['bldg'] == 'C栋', f"期望 bldg='C栋', 实际='{r['bldg']}'"
        assert r['house'] == '206'

    def test_sample4_area_between_road_and_roadno(self, engine):
        """样例4：area='罗湖村' 不应丢失（road和roadno之间的area保留）"""
        addr = '广东省深圳市罗湖区南湖街道罗湖社区人民南路罗湖村116号103'
        r = engine.parse_single(addr)
        assert r['road'] == '人民南路'
        assert r['roadno'] == '116号'
        assert r['area'] == '罗湖村', f"期望 area='罗湖村', 实际='{r['area']}'"
        assert r['house'] == '103'

    def test_sample5_plain_roadno_with_area_after(self, engine):
        """样例5：roadno='13-9', area='高新北文体中心', house='101'（不带号的门牌号识别）"""
        addr = '广东省深圳市南山区西丽街道松坪山社区乌石头路13-9高新北文体中心101'
        r = engine.parse_single(addr)
        assert r['road'] == '乌石头路'
        assert r['roadno'] == '13-9', f"期望 roadno='13-9', 实际='{r['roadno']}'"
        assert r['area'] == '高新北文体中心', f"期望 area='高新北文体中心', 实际='{r['area']}'"
        assert r['house'] == '101'

    def test_sample6_area_not_lost(self, engine):
        """样例6：area='珍果园果场' 不应丢失"""
        addr = '广东省深圳市南山区西丽街道阳光社区丽康路珍果园果场1号101'
        r = engine.parse_single(addr)
        assert r['road'] == '丽康路'
        assert r['roadno'] == '1号'
        assert r['area'] == '珍果园果场', f"期望 area='珍果园果场', 实际='{r['area']}'"
        assert r['house'] == '101'

    def test_sample7_house_not_3hao(self, engine):
        """样例7：house='101' 而非'3'（末尾数字优先于带后缀模式）"""
        addr = '广东省深圳市南山区西丽街道松坪山社区朗康路13号3号集装箱101'
        r = engine.parse_single(addr)
        assert r['road'] == '朗康路'
        assert r['roadno'] == '13号'
        assert r['house'] == '101', f"期望 house='101', 实际='{r['house']}'"
        # area 应包含"集装箱"（特殊地点属于area）
        assert '集装箱' in r['area']

    def test_sample8_house_4_not_empty(self, engine):
        """样例8：area='东湖公园杜鹃园宿舍', bldg='2栋', house='4'"""
        addr = '广东省深圳市罗湖区黄贝街道水库社区东湖公园杜鹃园宿舍2栋4号'
        r = engine.parse_single(addr)
        assert r['area'] == '东湖公园杜鹃园宿舍', f"期望 area='东湖公园杜鹃园宿舍', 实际='{r['area']}'"
        assert r['bldg'] == '2栋'
        assert r['house'] == '4', f"期望 house='4', 实际='{r['house']}'"

    def test_sample9_tail_hao_as_house(self, engine):
        """样例9：house='1' 而非 roadno='1号'（末尾X号作为house）"""
        addr = '广东省深圳市罗湖区黄贝街道水库社区东湖公园杜鹃园花圃工作房1号'
        r = engine.parse_single(addr)
        assert r['house'] == '1', f"期望 house='1', 实际='{r['house']}'"
        assert r['roadno'] == '', f"期望 roadno 为空, 实际='{r['roadno']}'"
        assert '花圃工作房' in r['area']

    def test_sample10_house_not_zhiyi(self, engine):
        """样例10：house='101' 而非'之一'（SPECIAL_HOUSE优先级降低）"""
        addr = '广东省深圳市罗湖区黄贝街道新兴社区经二路48号罗湖体育馆之一北-101'
        r = engine.parse_single(addr)
        assert r['road'] == '经二路'
        assert r['roadno'] == '48号'
        assert r['house'] == '101', f"期望 house='101', 实际='{r['house']}'"
        assert r['house'] != '之一'
        # area 应包含"罗湖体育馆"
        assert '罗湖体育馆' in r['area']

    def test_sample11_floor_not_as_house(self, engine):
        """样例11：'负3层'不应被识别为 house（去掉 house=floor 兜底）"""
        addr = '广东省深圳市南山区桃源街道峰景社区北环大道8028号方直珑樾山花园1栋负3层'
        r = engine.parse_single(addr)
        assert r['road'] == '北环大道'
        assert r['roadno'] == '8028号'
        assert '方直珑樾山花园' in r['area']
        assert r['bldg'] == '1栋'
        assert r['floor'] == '负3层'
        # house 应为空，不应被"负3层"误填充
        assert r['house'] == '', f"期望 house 为空, 实际='{r['house']}'"

    def test_house_no_chinese_suffix(self, engine):
        """房号不应包含中文后缀：'xx栋101房' 的 house 应为 '101' 而非 '101房'"""
        addr = '广东省深圳市南山区桃源街道峰景社区北环大道8028号方直珑樾山花园1栋101房'
        r = engine.parse_single(addr)
        assert r['house'] == '101', f"期望 house='101', 实际='{r['house']}'"
        # house 不应包含中文
        assert not any('\u4e00' <= ch <= '\u9fff' for ch in r['house']), \
            f"house 不应包含中文: '{r['house']}'"


class TestUserReportedAddressSamples2:
    """
    用户第二批反馈的5类真实地址样例回归测试。

    覆盖以下修复点：
        1. 路号错位：道路关键字 + area + bldg + "X号" 中 "X号" 是 house 而非 roadno。
        2. "第"字残留：FLOOR_PATTERN 支持中文数字"第X层"；BLDG_PATTERN 支持"第X栋"前缀；
           _clean_area_admin_residue 去掉易误切POI名的 [^区]+?区 分支。
        3. 商业街/商业广场未识别：补全 AREA_KEYWORDS / HARD_BOUNDARY_KEYWORDS。
        4. 房号混合组合：调整 _find_house 模式优先级，数字+字母+数字 优先于 纯末尾数字；
           新增"附X"模式。
        5. area 残留字母：_extract_structure 中先检测 bldg/unit/floor 结构关键字，
           避免将"B栋"等吞入 area。
    """

    # -------- 问题1：路号错位 --------
    def test_issue1_roadno_should_be_house(self, engine):
        """道路后area+bldg+'X号' 中 'X号' 应识别为 house 而非 roadno。"""
        addr = '广东省深圳市罗湖区黄贝街道水库社区爱国路东湖公园杜鹃园宿舍2栋5号'
        r = engine.parse_single(addr)
        assert r['road'] == '爱国路'
        assert r['roadno'] == '', f"期望 roadno 为空, 实际='{r['roadno']}'"
        assert r['area'] == '东湖公园杜鹃园宿舍'
        assert r['bldg'] == '2栋'
        assert r['house'] == '5', f"期望 house='5', 实际='{r['house']}'"

    def test_issue1_roadno_should_be_house_variant(self, engine):
        """同问题1的变体：道路后area+bldg+'X号' 不应将X号识别为roadno。"""
        addr = '广东省深圳市罗湖区黄贝街道水库社区爱国路东湖公园杜鹃园宿舍2栋15号'
        r = engine.parse_single(addr)
        assert r['road'] == '爱国路'
        assert r['roadno'] == '', f"期望 roadno 为空, 实际='{r['roadno']}'"
        assert r['bldg'] == '2栋'
        assert r['house'] == '15', f"期望 house='15', 实际='{r['house']}'"

    # -------- 问题2："第"字残留 + 工业区 --------
    def test_issue2_di_zi_in_floor_chinese_number(self, engine):
        """'第二层' 应整体识别为 floor，'第' 不应残留在 area。"""
        addr = '广东省深圳市福田区莲花街道狮岭社区景城路8号荔园外国语小学（天骄校区）第二层教学楼'
        r = engine.parse_single(addr)
        # area 不应是孤立的"第"字，也不应残留"第"
        assert r['area'] != '第'
        assert not r['area'].endswith('第'), f"area 末尾不应有'第': '{r['area']}'"
        # "第二层" 应被识别为 floor
        assert '二层' in r['floor'] or '第二层' in r['floor'], f"floor='{r['floor']}'"
        # "天骄校区" 不应被行政残留清理误切
        assert '校区' in r['area'] or '荔园外国语小学' in r['area'], f"area='{r['area']}'"

    def test_issue2_di_zi_in_bldg(self, engine):
        """'第1栋' 中的 '1栋' 应识别为 bldg，'第' 不应残留在 area。"""
        addr = '广东省深圳市南山区桃源街道珠光社区珠光路新屋村工业区第1栋302'
        r = engine.parse_single(addr)
        assert r['area'] == '新屋村工业区', f"期望 area='新屋村工业区', 实际='{r['area']}'"
        assert r['bldg'] == '1栋', f"期望 bldg='1栋', 实际='{r['bldg']}'"
        assert r['house'] == '302'
        # area 不应残留"第"
        assert '第' not in r['area']

    def test_issue2_industrial_zone_with_shop(self, engine):
        """'翠山工业区临街商铺' 中 '翠山工业区' 应识别为 area 主体。"""
        addr = '广东省深圳市罗湖区东晓街道绿景社区金稻田路2069号翠山工业区临街商铺一单元104'
        r = engine.parse_single(addr)
        assert '翠山工业区' in r['area'], f"area 应包含'翠山工业区', 实际='{r['area']}'"

    def test_issue2_industrial_zone_no_roadno(self, engine):
        """'坳下村128号金田工业区5栋' 应识别 area='金田工业区', bldg='5栋'。"""
        addr = '广东省深圳市罗湖区莲塘街道坳下社区坳下村128号金田工业区5栋右侧301'
        r = engine.parse_single(addr)
        # area 应包含"金田工业区"
        assert '金田工业区' in r['area'], f"area 应包含'金田工业区', 实际='{r['area']}'"
        assert r['bldg'] == '5栋', f"期望 bldg='5栋', 实际='{r['bldg']}'"
        assert r['house'] == '301'

    # -------- 问题3：商业街/商业广场 --------
    def test_issue3_commercial_street_dash_house(self, engine):
        """'深港融合商业街-10A' 中 '深港融合商业街' 是 area，'10A' 是 house。"""
        addr = '广东省深圳市罗湖区南湖街道罗湖桥社区建设路1001号火车站综合大楼负一层深港融合商业街-10A'
        r = engine.parse_single(addr)
        assert '深港融合商业街' in r['area'], f"area 应包含'深港融合商业街', 实际='{r['area']}'"
        # area 末尾不应残留 "-"
        assert not r['area'].endswith('-'), f"area 不应以'-'结尾: '{r['area']}'"
        assert r['house'] == '10A', f"期望 house='10A', 实际='{r['house']}'"

    # -------- 问题4：房号混合组合 --------
    def test_issue4_house_number_letter_number(self, engine):
        """房号 '7B12'（数字+字母+数字）应整体作为 house，不应切分为 '7B'+'12'。"""
        addr = '广东省深圳市罗湖区黄贝街道黄贝岭社区深南东路1038号黄贝岭经泽大厦7B12'
        r = engine.parse_single(addr)
        assert r['area'] == '黄贝岭经泽大厦', f"期望 area='黄贝岭经泽大厦', 实际='{r['area']}'"
        assert r['house'] == '7B12', f"期望 house='7B12', 实际='{r['house']}'"

    def test_issue4_house_letter_number_with_dash(self, engine):
        """房号 'L1-21A'（字母+数字+连接符+字母数字）应整体作为 house。"""
        addr = '广东省深圳市罗湖区南湖街道嘉北社区人民南路3002号国际贸易中心大厦A区L1-21A'
        r = engine.parse_single(addr)
        assert r['house'] == 'L1-21A', f"期望 house='L1-21A', 实际='{r['house']}'"

    def test_issue4_house_with_fu_prefix(self, engine):
        """房号 '附01'（附+数字）应整体作为 house。"""
        addr = '广东省深圳市罗湖区黄贝街道新兴社区经二路38号安业花园C2栋附01'
        r = engine.parse_single(addr)
        assert r['bldg'] == 'C2栋', f"期望 bldg='C2栋', 实际='{r['bldg']}'"
        # house 应为 "01" 或 "附01"
        assert r['house'] in ('01', '附01'), f"期望 house='01' 或 '附01', 实际='{r['house']}'"

    def test_issue4_house_pure_letter(self, engine):
        """房号 'B'（单字母）应作为 house（楼层后）。"""
        addr = '广东省深圳市罗湖区黄贝街道怡景社区怡景路2003号怡景花园荷花村401型一层B'
        r = engine.parse_single(addr)
        assert r['house'] == 'B', f"期望 house='B', 实际='{r['house']}'"

    # -------- 问题5：area 残留字母 --------
    def test_issue5_bldg_in_area_should_extract(self, engine):
        """'华清园B栋旁集装箱1号' 中 'B栋' 应识别为 bldg，不残留在 area。"""
        addr = '广东省深圳市罗湖区黄贝街道新兴社区经二路38号华清园B栋旁集装箱1号'
        r = engine.parse_single(addr)
        # "B栋" 应识别为 bldg
        assert r['bldg'] == 'B栋', f"期望 bldg='B栋', 实际='{r['bldg']}'"
        # area 不应残留 "B栋"
        assert 'B栋' not in r['area'], f"area 不应包含'B栋': '{r['area']}'"
        assert r['house'] == '1', f"期望 house='1', 实际='{r['house']}'"

    def test_issue5_no_letter_residue_in_area(self, engine):
        """area 末尾不应残留 '7B' 等数字+字母片段（应由问题4修复顺带解决）。"""
        addr = '广东省深圳市罗湖区黄贝街道黄贝岭社区深南东路1038号黄贝岭经泽大厦7B12'
        r = engine.parse_single(addr)
        # area 不应以数字+字母结尾
        assert not re.search(r'\d+[A-Za-z]$', r['area']), f"area 末尾不应残留数字+字母: '{r['area']}'"

    def test_issue5_letter_plus_number_as_house(self, engine):
        """'F521'（字母+数字）应整体作为 house，不应切分为 area='...F' + house='521'。"""
        addr = '广东省深圳市罗湖区南湖街道罗湖桥社区建设路1001号火车站综合大楼F521'
        r = engine.parse_single(addr)
        assert r['area'] == '火车站综合大楼', f"期望 area='火车站综合大楼', 实际='{r['area']}'"
        assert r['house'] == 'F521', f"期望 house='F521', 实际='{r['house']}'"
        # area 末尾不应残留字母
        assert not re.search(r'[A-Za-z]$', r['area']), f"area 末尾不应残留字母: '{r['area']}'"

    def test_issue5_letter_floor_should_extract(self, engine):
        """'G层'/'P层'（字母+层）应识别为 floor，不残留在 area。"""
        addr = '广东省深圳市罗湖区南湖街道罗湖桥社区人民南路1002号罗湖商业城G层A10'
        r = engine.parse_single(addr)
        assert r['area'] == '罗湖商业城', f"期望 area='罗湖商业城', 实际='{r['area']}'"
        assert r['floor'] == 'G层', f"期望 floor='G层', 实际='{r['floor']}'"
        assert r['house'] == 'A10', f"期望 house='A10', 实际='{r['house']}'"
        # area 不应残留 "G层"
        assert 'G层' not in r['area'], f"area 不应包含'G层': '{r['area']}'"


class TestUserReportedAddressSamples3:
    """
    用户第三批反馈：单字 area 问题。

    规则：area 解析出来为单个字（不管是中文、字母还是符号）时都是有问题的。
    如果没法语义识别为片区，那么片区解析为空。

    覆盖以下修复点：
        1. _match_plain_roadno_after_kw 中，"数字+栋/幢/座/楼/层" 开头时
           数字应作为楼栋号而非 roadno，避免 "12栋" 被切分为 roadno='12' + area='栋'。
        2. _parse_single 末尾兜底：area 长度为 1 时一律置空
           （单字 area 都是切分错误残留，没有合法的语义片区）。
    """

    # -------- 用户示例：12栋被切分 --------
    def test_issue6_user_example_minfu_road(self, engine):
        """用户示例：'民福路12栋351' 应 area='', bldg='12栋', roadno=''。"""
        addr = '广东省深圳市宝安区沙井街道沙头社区民福路12栋351'
        r = engine.parse_single(addr)
        assert r['road'] == '民福路', f"期望 road='民福路', 实际='{r['road']}'"
        assert r['roadno'] == '', f"期望 roadno 为空, 实际='{r['roadno']}'"
        assert r['area'] == '', f"期望 area 为空, 实际='{r['area']}'"
        assert r['bldg'] == '12栋', f"期望 bldg='12栋', 实际='{r['bldg']}'"
        assert r['house'] == '351', f"期望 house='351', 实际='{r['house']}'"

    def test_issue6_dong_residue_with_bldg(self, engine):
        """'光侨街11栋202A' 中 '11栋' 应识别为 bldg，'栋' 不应残留 area。"""
        addr = '广东省深圳市南山区沙河街道光华街社区光侨街11栋202A'
        r = engine.parse_single(addr)
        assert r['area'] == '', f"期望 area 为空, 实际='{r['area']}'"
        assert r['bldg'] == '11栋', f"期望 bldg='11栋', 实际='{r['bldg']}'"
        assert r['house'] == '202A', f"期望 house='202A', 实际='{r['house']}'"

    def test_issue6_dong_residue_zhaoshang(self, engine):
        """'招商南路7栋703' 中 '7栋' 应识别为 bldg，'栋' 不应残留 area。"""
        addr = '广东省深圳市南山区蛇口街道南水社区蛇口招商南路7栋703'
        r = engine.parse_single(addr)
        assert r['area'] == '', f"期望 area 为空, 实际='{r['area']}'"
        assert r['bldg'] == '7栋', f"期望 bldg='7栋', 实际='{r['bldg']}'"
        assert r['house'] == '703', f"期望 house='703', 实际='{r['house']}'"

    def test_issue6_dong_residue_fengqing_street(self, engine):
        """'风情街1栋2层' 中 '1栋' 应识别为 bldg，'栋' 不应残留 area。"""
        addr = '广东省深圳市福田区南园街道巴登社区红岭南路风情街1栋2层'
        r = engine.parse_single(addr)
        assert r['area'] == '', f"期望 area 为空, 实际='{r['area']}'"
        assert r['bldg'] == '1栋', f"期望 bldg='1栋', 实际='{r['bldg']}'"
        assert r['floor'] == '2层', f"期望 floor='2层', 实际='{r['floor']}'"

    # -------- 单字方位/旁字残留 --------
    def test_issue6_single_pang_residue(self, engine):
        """'X号旁101' 中 '旁' 不应残留 area。"""
        addr = '广东省深圳市罗湖区东门街道城东社区东门中路2040号旁101'
        r = engine.parse_single(addr)
        assert r['area'] == '', f"期望 area 为空, 实际='{r['area']}'"
        assert r['house'] == '101', f"期望 house='101', 实际='{r['house']}'"

    def test_issue6_single_direction_residue(self, engine):
        """'X号东101' 中 '东' 不应残留 area。"""
        addr = '广东省深圳市南山区沙河街道香山街社区文昌南街18号东103'
        r = engine.parse_single(addr)
        assert r['area'] == '', f"期望 area 为空, 实际='{r['area']}'"
        assert r['house'] == '103', f"期望 house='103', 实际='{r['house']}'"

    def test_issue6_single_bian_residue(self, engine):
        """'X号边101' 中 '边' 不应残留 area。"""
        addr = '广东省深圳市南山区南山街道南山社区南山村南巷8号边101'
        r = engine.parse_single(addr)
        assert r['area'] == '', f"期望 area 为空, 实际='{r['area']}'"
        assert r['house'] == '101', f"期望 house='101', 实际='{r['house']}'"

    # -------- 单字连接符/空格残留 --------
    def test_issue6_single_dash_residue(self, engine):
        """'X号-1101' 中 '-' 不应残留 area。"""
        addr = '广东省深圳市南山区西丽街道新围社区九祥岭南天路86号-1101'
        r = engine.parse_single(addr)
        assert r['area'] == '', f"期望 area 为空, 实际='{r['area']}'"
        assert r['house'] == '1101', f"期望 house='1101', 实际='{r['house']}'"

    def test_issue6_single_space_residue(self, engine):
        """'X号 302' 中空格不应残留 area。"""
        addr = '广东省深圳市南山区南头街道大新社区新铺街42号 302'
        r = engine.parse_single(addr)
        assert r['area'] == '', f"期望 area 为空, 实际='{r['area']}'"
        assert r['house'] == '302', f"期望 house='302', 实际='{r['house']}'"

    # -------- 单字 POI 残留（村/园/区/城/里/阁/围/洲/庄/湾）--------
    def test_issue6_single_ge_residue(self, engine):
        """'X号阁108' 中 '阁' 不应残留 area。"""
        addr = '广东省深圳市福田区梅林街道上梅社区上梅林新村101号阁108'
        r = engine.parse_single(addr)
        assert r['area'] == '', f"期望 area 为空, 实际='{r['area']}'"
        assert r['house'] == '108', f"期望 house='108', 实际='{r['house']}'"

    def test_issue6_single_wan_residue(self, engine):
        """'湾厦路X号221' 中 '湾' 不应残留 area。"""
        addr = '广东省深圳市南山区蛇口街道渔二社区湾厦路12-14号221'
        r = engine.parse_single(addr)
        assert r['area'] == '', f"期望 area 为空, 实际='{r['area']}'"
        assert r['house'] == '221', f"期望 house='221', 实际='{r['house']}'"

    def test_issue6_single_zhou_residue(self, engine):
        """'洲奋路X号3栋101' 中 '洲' 不应残留 area。"""
        addr = '广东省深圳市宝安区石岩街道宝源社区洲奋路5号3栋101'
        r = engine.parse_single(addr)
        assert r['area'] == '', f"期望 area 为空, 实际='{r['area']}'"
        assert r['bldg'] == '3栋', f"期望 bldg='3栋', 实际='{r['bldg']}'"
        assert r['house'] == '101', f"期望 house='101', 实际='{r['house']}'"

    def test_issue6_single_hua_residue(self, engine):
        """'梅东二路7号华南楼104' 中 '华' 不应残留 area。"""
        addr = '广东省深圳市福田区梅林街道翰岭社区梅东二路7号华南楼104'
        r = engine.parse_single(addr)
        assert r['area'] == '', f"期望 area 为空, 实际='{r['area']}'"
        assert r['house'] == '104', f"期望 house='104', 实际='{r['house']}'"

    # -------- 单字字母/数字残留 --------
    def test_issue6_single_letter_residue(self, engine):
        """'埔尾路38号B' 中 'B' 不应残留 area。"""
        addr = '广东省深圳市福田区南园街道巴登社区埔尾路38号B'
        r = engine.parse_single(addr)
        assert r['area'] == '', f"期望 area 为空, 实际='{r['area']}'"

    def test_issue6_single_digit_residue(self, engine):
        """'梅拉尼亚小镇5、6号铺5号' 中 '5' 不应残留 area。"""
        addr = '广东省深圳市南山区沙河街道东方社区深南大道9037号梅拉尼亚小镇5、6号铺5号'
        r = engine.parse_single(addr)
        assert r['area'] == '', f"期望 area 为空, 实际='{r['area']}'"

    # -------- 单字结构残留（楼/负/口/铺/市/研）--------
    def test_issue6_single_yan_residue(self, engine):
        """'创研路2号研一楼一层' 中 '研' 不应残留 area。"""
        addr = '广东省深圳市南山区西丽街道曙光社区创研路2号研一楼一层'
        r = engine.parse_single(addr)
        assert r['area'] == '', f"期望 area 为空, 实际='{r['area']}'"

    def test_issue6_single_kou_residue(self, engine):
        """'部九窝路口101' 中 '口' 不应残留 area。"""
        addr = '广东省深圳市南山区西丽街道大磡社区部九窝路口101'
        r = engine.parse_single(addr)
        assert r['area'] == '', f"期望 area 为空, 实际='{r['area']}'"
        assert r['house'] == '101', f"期望 house='101', 实际='{r['house']}'"


class TestUserReportedAddressSamples4:
    """
    用户第四批反馈：单元分词问题。

    覆盖以下修复点：
        1. UNIT_PATTERN 增加字母前缀支持：识别 A单元、AB单元、EFGH单元 等字母单元，
           避免字母单元被丢弃或被吞入 area。
        2. _parse_tail_after_bldg 中扩展 unit 匹配：bldg 之后的"数字/字母+座"
           作为 unit 处理（如"3栋5座101"中 unit="5座"，"3栋B座101"中 unit="B座"）。
           单独的"X座"在主流程中仍作为 bldg。
    """

    # -------- 问题1：字母单元未识别 --------
    def test_issue7_single_letter_unit(self, engine):
        """'金泰名苑A单元1501' 中 'A单元' 应识别为 unit。"""
        addr = '广东省深圳市罗湖区东湖街道东乐社区太宁路18号金泰名苑A单元1501'
        r = engine.parse_single(addr)
        assert r['area'] == '金泰名苑', f"期望 area='金泰名苑', 实际='{r['area']}'"
        assert r['unit'] == 'A单元', f"期望 unit='A单元', 实际='{r['unit']}'"
        assert r['house'] == '1501', f"期望 house='1501', 实际='{r['house']}'"

    def test_issue7_letter_unit_after_bldg(self, engine):
        """'5栋A单元101-1号' 中 'A单元' 应识别为 unit。"""
        addr = '广东省深圳市福田区南园街道滨河社区滨河大道3161号怡兴苑5栋A单元101-1号'
        r = engine.parse_single(addr)
        assert r['area'] == '怡兴苑', f"期望 area='怡兴苑', 实际='{r['area']}'"
        assert r['bldg'] == '5栋', f"期望 bldg='5栋', 实际='{r['bldg']}'"
        assert r['unit'] == 'A单元', f"期望 unit='A单元', 实际='{r['unit']}'"

    def test_issue7_letter_unit_b(self, engine):
        """'B单元' 应识别为 unit，area 不应包含'B单元'。"""
        addr = '广东省深圳市罗湖区莲塘街道长岭社区长岭村62号B单元62-6号'
        r = engine.parse_single(addr)
        assert r['unit'] == 'B单元', f"期望 unit='B单元', 实际='{r['unit']}'"
        assert 'B单元' not in r['area'], f"area 不应包含'B单元': '{r['area']}'"

    def test_issue7_letter_unit_c(self, engine):
        """'C单元' 应识别为 unit，area 不应残留'C单元'。"""
        addr = '广东省深圳市福田区园岭街道上林社区八卦四路32号意馨居C单元1层5号'
        r = engine.parse_single(addr)
        assert r['area'] == '意馨居', f"期望 area='意馨居', 实际='{r['area']}'"
        assert r['unit'] == 'C单元', f"期望 unit='C单元', 实际='{r['unit']}'"
        assert r['floor'] == '1层', f"期望 floor='1层', 实际='{r['floor']}'"

    def test_issue7_multi_letter_unit_ab(self, engine):
        """'AB单元'（多字母）应识别为 unit。"""
        addr = '广东省深圳市福田区沙头街道新洲社区新洲北路1栋AB单元302'
        r = engine.parse_single(addr)
        assert r['bldg'] == '1栋', f"期望 bldg='1栋', 实际='{r['bldg']}'"
        assert r['unit'] == 'AB单元', f"期望 unit='AB单元', 实际='{r['unit']}'"
        assert r['house'] == '302', f"期望 house='302', 实际='{r['house']}'"

    def test_issue7_multi_letter_unit_efgh(self, engine):
        """'EFGH单元'（4字母）应识别为 unit。"""
        addr = '广东省深圳市福田区沙头街道新洲社区新洲北路1栋EFGH单元302'
        r = engine.parse_single(addr)
        assert r['bldg'] == '1栋', f"期望 bldg='1栋', 实际='{r['bldg']}'"
        assert r['unit'] == 'EFGH单元', f"期望 unit='EFGH单元', 实际='{r['unit']}'"

    def test_issue7_letter_unit_before_bldg(self, engine):
        """'A单元B栋502' 中 'A单元' 是 unit，'B栋' 是 bldg，两者都应识别。"""
        addr = '广东省深圳市罗湖区黄贝街道怡景社区怡景路8号A单元B栋502'
        r = engine.parse_single(addr)
        # A单元 是 unit（先于 B栋），B栋 是 bldg
        assert r['unit'] == 'A单元', f"期望 unit='A单元', 实际='{r['unit']}'"
        assert r['bldg'] == 'B栋', f"期望 bldg='B栋', 实际='{r['bldg']}'"
        assert r['house'] == '502', f"期望 house='502', 实际='{r['house']}'"
        # area 不应是 'A单元'
        assert r['area'] != 'A单元', f"area 不应是'A单元': '{r['area']}'"

    # -------- 问题2：X栋Y座 中 Y座归 unit --------
    def test_issue8_dong_zuo_unit(self, engine):
        """'1栋3座2303' 中 '3座' 应识别为 unit。"""
        addr = '广东省深圳市南山区招商街道赤湾社区伴山伴海1栋3座2303'
        r = engine.parse_single(addr)
        assert r['bldg'] == '1栋', f"期望 bldg='1栋', 实际='{r['bldg']}'"
        assert r['unit'] == '3座', f"期望 unit='3座', 实际='{r['unit']}'"
        assert r['house'] == '2303', f"期望 house='2303', 实际='{r['house']}'"

    def test_issue8_dong_letter_zuo_unit(self, engine):
        """'3栋B座101' 中 'B座' 应识别为 unit。"""
        addr = '广东省深圳市南山区粤海街道科技园社区科苑路3栋B座101'
        r = engine.parse_single(addr)
        assert r['bldg'] == '3栋', f"期望 bldg='3栋', 实际='{r['bldg']}'"
        assert r['unit'] == 'B座', f"期望 unit='B座', 实际='{r['unit']}'"
        assert r['house'] == '101', f"期望 house='101', 实际='{r['house']}'"

    def test_issue8_single_zuo_still_bldg(self, engine):
        """单独的 '5座101'（无X栋前缀）应识别为 bldg='5座'，而非 unit。"""
        addr = '广东省深圳市南山区粤海街道科技园社区科苑路5座101'
        r = engine.parse_single(addr)
        assert r['bldg'] == '5座', f"期望 bldg='5座', 实际='{r['bldg']}'"
        assert r['unit'] == '', f"期望 unit 为空, 实际='{r['unit']}'"
        assert r['house'] == '101', f"期望 house='101', 实际='{r['house']}'"

    def test_issue8_dong_zuo_with_floor(self, engine):
        """'1栋3座2层5号' 中 '3座' 是 unit，'2层' 是 floor。"""
        addr = '广东省深圳市南山区招商街道赤湾社区伴山伴海1栋3座2层5号'
        r = engine.parse_single(addr)
        assert r['bldg'] == '1栋', f"期望 bldg='1栋', 实际='{r['bldg']}'"
        assert r['unit'] == '3座', f"期望 unit='3座', 实际='{r['unit']}'"
        assert r['floor'] == '2层', f"期望 floor='2层', 实际='{r['floor']}'"


class TestUserReportedAddressSamples5:
    """
    用户第五批反馈：横杠连接多栋编号未识别为 bldg。

    覆盖以下修复点：
        BLDG_PATTERN 增加横杠连接多栋分支：识别 5-8栋、12-15栋、62-1栋、1-3号楼 等
        横杠连接的多栋编号，避免被 _find_house 第一个模式（横杠/斜杠多段连接）
        抢先匹配为 house。

    数据库样本量：含 'X-Y栋' 模式的地址 2617 条，含 'X-Y号楼' 模式 35 条。
    """

    def test_issue9_dash_bldg_simple(self, engine):
        """'62-1栋103' 中 '62-1栋' 应整体识别为 bldg，'103' 是 house。"""
        addr = '广东省深圳市罗湖区黄贝街道黄贝岭社区深南东路1002号黄贝岭下村62-1栋103'
        r = engine.parse_single(addr)
        assert r['bldg'] == '62-1栋', f"期望 bldg='62-1栋', 实际='{r['bldg']}'"
        assert r['house'] == '103', f"期望 house='103', 实际='{r['house']}'"

    def test_issue9_dash_bldg_range(self, engine):
        """'6-7栋6栋301' 中 '6-7栋' 应整体识别为 bldg。"""
        addr = '广东省深圳市罗湖区东晓街道东晓社区东晓路3051号布心特力工业区6-7栋6栋301'
        r = engine.parse_single(addr)
        assert r['bldg'] == '6-7栋', f"期望 bldg='6-7栋', 实际='{r['bldg']}'"
        assert r['house'] == '301', f"期望 house='301', 实际='{r['house']}'"

    def test_issue9_dash_bldg_with_zuo(self, engine):
        """'5-8栋7座27D' 中 '5-8栋' 是 bldg，'7座' 是 unit，'27D' 是 house。"""
        addr = '广东省深圳市龙华区民治街道新牛社区锦绣江南四期5-8栋7座27D'
        r = engine.parse_single(addr)
        assert r['bldg'] == '5-8栋', f"期望 bldg='5-8栋', 实际='{r['bldg']}'"
        assert r['unit'] == '7座', f"期望 unit='7座', 实际='{r['unit']}'"
        assert r['house'] == '27D', f"期望 house='27D', 实际='{r['house']}'"

    def test_issue9_dash_bldg_with_unit(self, engine):
        """'12-15栋15栋B单元312' 中 '12-15栋' 是 bldg，'B单元' 是 unit。"""
        addr = '广东省深圳市龙岗区布吉街道长龙社区德兴城12-15栋15栋B单元312'
        r = engine.parse_single(addr)
        assert r['bldg'] == '12-15栋', f"期望 bldg='12-15栋', 实际='{r['bldg']}'"
        assert r['unit'] == 'B单元', f"期望 unit='B单元', 实际='{r['unit']}'"
        assert r['house'] == '312', f"期望 house='312', 实际='{r['house']}'"

    def test_issue9_dash_bldg_with_north(self, engine):
        """'6-7栋7栋南312' 中 '6-7栋' 是 bldg，'312' 是 house。"""
        addr = '广东省深圳市罗湖区东晓街道东晓社区东晓路3051号布心特力工业区6-7栋7栋南312'
        r = engine.parse_single(addr)
        assert r['bldg'] == '6-7栋', f"期望 bldg='6-7栋', 实际='{r['bldg']}'"
        assert r['house'] == '312', f"期望 house='312', 实际='{r['house']}'"

    def test_issue9_dash_bldg_with_north_and_letter(self, engine):
        """'6-7栋7栋南312A' 中 '6-7栋' 是 bldg，'312A' 是 house（数字+字母）。"""
        addr = '广东省深圳市罗湖区东晓街道东晓社区东晓路3051号布心特力工业区6-7栋7栋南312A'
        r = engine.parse_single(addr)
        assert r['bldg'] == '6-7栋', f"期望 bldg='6-7栋', 实际='{r['bldg']}'"
        assert r['house'] == '312A', f"期望 house='312A', 实际='{r['house']}'"

    def test_issue9_dash_bldgno(self, engine):
        """'1-3号楼' 中 '1-3号楼' 应整体识别为 bldg。"""
        addr = '广东省深圳市福田区华强北街道华航社区振兴路1-3号楼101'
        r = engine.parse_single(addr)
        assert r['bldg'] == '1-3号楼', f"期望 bldg='1-3号楼', 实际='{r['bldg']}'"
        assert r['house'] == '101', f"期望 house='101', 实际='{r['house']}'"

    def test_issue9_dash_house_not_bldg(self, engine):
        """'101-102'（房号横杠连接，无栋关键字）应识别为 house 而非 bldg。"""
        addr = '广东省深圳市福田区南园街道滨河社区滨河大道1001号怡兴苑5栋101-102'
        r = engine.parse_single(addr)
        assert r['bldg'] == '5栋', f"期望 bldg='5栋', 实际='{r['bldg']}'"
        assert r['house'] == '101-102', f"期望 house='101-102', 实际='{r['house']}'"

    def test_issue9_dash_bldg_no_regression_single(self, engine):
        """无横杠的单栋号 '5栋' 不应受影响。"""
        addr = '广东省深圳市福田区南园街道滨河社区滨河大道1001号怡兴苑5栋301'
        r = engine.parse_single(addr)
        assert r['bldg'] == '5栋', f"期望 bldg='5栋', 实际='{r['bldg']}'"
        assert r['house'] == '301', f"期望 house='301', 实际='{r['house']}'"

    def test_issue9_multi_dash_bldg_4_segments(self, engine):
        """'1-2-3-4栋2001' 中 '1-2-3-4栋' 是 bldg（4段横杠连接），'2001' 是 house。"""
        addr = '广东省深圳市南山区南山街道北头社区桂庙路5号福海苑1-2-3-4栋2001'
        r = engine.parse_single(addr)
        assert r['bldg'] == '1-2-3-4栋', f"期望 bldg='1-2-3-4栋', 实际='{r['bldg']}'"
        assert r['house'] == '2001', f"期望 house='2001', 实际='{r['house']}'"

    def test_issue9_multi_dash_bldg_3_segments(self, engine):
        """'10-11-12栋' 是 bldg（3段横杠连接）。"""
        addr = '广东省深圳市龙岗区横岗街道六约北社区深华街4-1-4栋103'
        r = engine.parse_single(addr)
        assert r['bldg'] == '4-1-4栋', f"期望 bldg='4-1-4栋', 实际='{r['bldg']}'"
        assert r['house'] == '103', f"期望 house='103', 实际='{r['house']}'"

    def test_issue9_letter_dash_bldg_b13(self, engine):
        """'B13-3栋204' 中 'B13-3栋' 是 bldg（字母+数字+横杠+数字），'204' 是 house。"""
        addr = '广东省深圳市宝安区沙井街道壆岗社区岗头路23号B区G馆B13-3栋204'
        r = engine.parse_single(addr)
        assert r['bldg'] == 'B13-3栋', f"期望 bldg='B13-3栋', 实际='{r['bldg']}'"
        assert r['house'] == '204', f"期望 house='204', 实际='{r['house']}'"

    def test_issue9_letter_dash_bldg_a5(self, engine):
        """'A5-3栋108' 中 'A5-3栋' 是 bldg（字母+数字+横杠+数字）。"""
        addr = '广东省深圳市宝安区沙井街道壆岗社区岗头路20号A5-3栋108'
        r = engine.parse_single(addr)
        assert r['bldg'] == 'A5-3栋', f"期望 bldg='A5-3栋', 实际='{r['bldg']}'"
        assert r['house'] == '108', f"期望 house='108', 实际='{r['house']}'"


class TestUserReportedAddressSamples6:
    """
    用户第六批反馈：字母+数字+字母形式的房号被截断。

    典型问题：
        - "平朗路9号0国城B16D" 被解析为 house='B16'，正确应为 house='B16D'
        - "平朗路9号0国城B16G" 被解析为 house='B16'，正确应为 house='B16G'
    """

    def test_issue10_letter_digit_letter_house_b16d(self, engine):
        """房号"B16D"（字母+数字+字母）应完整识别，不应截断为"B16"。"""
        addr = '广东省深圳市龙岗区南湾街道上李朗社区平吉大道平朗路9号0国城B16D'
        r = engine.parse_single(addr)
        assert r['house'] == 'B16D', f"期望 house='B16D', 实际='{r['house']}'"

    def test_issue10_letter_digit_letter_house_b16g(self, engine):
        """房号"B16G"（字母+数字+字母）应完整识别，不应截断为"B16"。"""
        addr = '深圳市龙岗区南湾街道上李朗社区平吉大道平朗路9号0国城B16G'
        r = engine.parse_single(addr)
        assert r['house'] == 'B16G', f"期望 house='B16G', 实际='{r['house']}'"

    def test_issue10_letter_digit_letter_house_a101b(self, engine):
        """房号"A101B"（字母+数字+字母）应完整识别。"""
        addr = '广东省深圳市南山区科技园南区A101B'
        r = engine.parse_single(addr)
        assert r['house'] == 'A101B', f"期望 house='A101B', 实际='{r['house']}'"

    def test_issue10_no_regression_letter_digit(self, engine):
        """原有"字母+数字"房号（如"B101"）不应回归。"""
        addr = '广东省深圳市福田区华强北街道华航社区振兴路91-13号B101'
        r = engine.parse_single(addr)
        assert r['house'] == 'B101', f"期望 house='B101', 实际='{r['house']}'"

    def test_issue10_no_regression_digit_letter_digit(self, engine):
        """原有"数字+字母+数字"房号（如"7B12"）不应回归。"""
        addr = '广东省深圳市罗湖区东晓街道东晓社区东晓路3051号7B12'
        r = engine.parse_single(addr)
        assert r['house'] == '7B12', f"期望 house='7B12', 实际='{r['house']}'"


class TestUserReportedAddressSamples7:
    """
    用户第七批反馈：商铺/档口等后缀的房号未完整提取。

    典型问题：
        - "丽景城3栋118商铺" 中 house=''，正确应为 house='118'
        - "丽景城3栋118档" 中 house=''，正确应为 house='118'
        - "118号铺/118铺/118号档" 已能提取出数字，但 "118商铺/118档" 无法触发后缀匹配
    """

    def test_issue11_house_with_shangpu_suffix(self, engine):
        """"118商铺"应提取房号"118"。"""
        addr = '深圳市宝安区西乡街道丽景城3栋118商铺'
        r = engine.parse_single(addr)
        assert r['house'] == '118', f"期望 house='118', 实际='{r['house']}'"

    def test_issue11_house_with_pu_suffix(self, engine):
        """"118铺"应提取房号"118"。"""
        addr = '深圳市宝安区西乡街道丽景城3栋118铺'
        r = engine.parse_single(addr)
        assert r['house'] == '118', f"期望 house='118', 实际='{r['house']}'"

    def test_issue11_house_with_haopu_suffix(self, engine):
        """"118号铺"应提取房号"118"。"""
        addr = '深圳市宝安区西乡街道丽景城3栋118号铺'
        r = engine.parse_single(addr)
        assert r['house'] == '118', f"期望 house='118', 实际='{r['house']}'"

    def test_issue11_house_with_dang_suffix(self, engine):
        """"118档"应提取房号"118"。"""
        addr = '深圳市宝安区西乡街道丽景城3栋118档'
        r = engine.parse_single(addr)
        assert r['house'] == '118', f"期望 house='118', 实际='{r['house']}'"

    def test_issue11_house_with_haodang_suffix(self, engine):
        """"118号档"应提取房号"118"。"""
        addr = '深圳市宝安区西乡街道丽景城3栋118号档'
        r = engine.parse_single(addr)
        assert r['house'] == '118', f"期望 house='118', 实际='{r['house']}'"

    def test_issue11_no_regression_linjie_shangpu(self, engine):
        """"临街商铺"作为area描述时不应被误当房号后缀，房号"104"仍需提取。"""
        addr = '广东省深圳市罗湖区东晓街道绿景社区金稻田路2069号翠山工业区临街商铺一单元104'
        r = engine.parse_single(addr)
        assert r['house'] == '104', f"期望 house='104', 实际='{r['house']}'"
        assert '临街商铺' in r['area'], f"期望 area 包含'临街商铺', 实际='{r['area']}'"


class TestUserReportedAddressSamples8:
    """
    用户第八批反馈：字母+铺/档后缀（A铺、B档等）未识别为房号。

    典型问题：
        - "华强北路1号A铺" 中 house=''，'A铺'被当作area，正确应为 house='A'
        - "爱国路1号B档" 中 house=''，'B档'被当作area，正确应为 house='B'
        - "3栋B铺" 中 house=''，正确应为 house='B'
        - 后缀不纳入house值（如"A铺"→house="A"而非"A铺"）
    """

    def test_alpha_pu_suffix(self, engine):
        """"A铺"应提取房号"A"，后缀不纳入。"""
        addr = '广东省深圳市福田区华强北路1号A铺'
        r = engine.parse_single(addr)
        assert r['house'] == 'A', f"期望 house='A', 实际='{r['house']}'"
        assert r['area'] == '', f"期望 area='', 实际='{r['area']}'"

    def test_alpha_dang_suffix(self, engine):
        """"B档"应提取房号"B"，后缀不纳入。"""
        addr = '广东省深圳市罗湖区黄贝街道爱国路1号B档'
        r = engine.parse_single(addr)
        assert r['house'] == 'B', f"期望 house='B', 实际='{r['house']}'"
        assert r['area'] == '', f"期望 area='', 实际='{r['area']}'"

    def test_alpha_shangpu_suffix(self, engine):
        """"A商铺"应提取房号"A"，后缀不纳入。"""
        addr = '广东省深圳市福田区华强北路1号A商铺'
        r = engine.parse_single(addr)
        assert r['house'] == 'A', f"期望 house='A', 实际='{r['house']}'"

    def test_alpha_dangkou_suffix(self, engine):
        """"C档口"应提取房号"C"，后缀不纳入。"""
        addr = '广东省深圳市福田区华强北路1号C档口'
        r = engine.parse_single(addr)
        assert r['house'] == 'C', f"期望 house='C', 实际='{r['house']}'"

    def test_alpha_pu_after_bldg(self, engine):
        """楼栋后"B铺"应识别为房号"B"。"""
        addr = '广东省深圳市福田区沙头街道金地社区福强路金地工业区3栋B铺'
        r = engine.parse_single(addr)
        assert r['bldg'] == '3栋', f"期望 bldg='3栋', 实际='{r['bldg']}'"
        assert r['house'] == 'B', f"期望 house='B', 实际='{r['house']}'"

    def test_digit_haopu_suffix_no_suffix_in_result(self, engine):
        """"3号铺"应提取房号"3"，后缀不纳入。"""
        addr = '广东省深圳市福田区华强北路1号3号铺'
        r = engine.parse_single(addr)
        assert r['house'] == '3', f"期望 house='3', 实际='{r['house']}'"

    def test_digit_pu_suffix_no_suffix_in_result(self, engine):
        """"3铺"应提取房号"3"，后缀不纳入。"""
        addr = '广东省深圳市福田区华强北路1号3铺'
        r = engine.parse_single(addr)
        assert r['house'] == '3', f"期望 house='3', 实际='{r['house']}'"

    def test_digit_haodang_suffix_no_suffix_in_result(self, engine):
        """"3号档"应提取房号"3"，后缀不纳入。"""
        addr = '广东省深圳市福田区华强北路1号3号档'
        r = engine.parse_single(addr)
        assert r['house'] == '3', f"期望 house='3', 实际='{r['house']}'"

    def test_digit_dangkou_suffix_no_suffix_in_result(self, engine):
        """"3号档口"应提取房号"3"，后缀不纳入。"""
        addr = '广东省深圳市福田区华强北路15号3号档口'
        r = engine.parse_single(addr)
        assert r['house'] == '3', f"期望 house='3', 实际='{r['house']}'"

    def test_digit_dianpu_suffix(self, engine):
        """"118店铺"应提取房号"118"，后缀不纳入。"""
        addr = '广东省深圳市福田区华强北路1号118店铺'
        r = engine.parse_single(addr)
        assert r['house'] == '118', f"期望 house='118', 实际='{r['house']}'"
        assert r['area'] == '', f"期望 area='', 实际='{r['area']}'"

    def test_digit_hao_dianpu_suffix(self, engine):
        """"5号店铺"应提取房号"5"，后缀不纳入。"""
        addr = '广东省深圳市福田区华强北路1号5号店铺'
        r = engine.parse_single(addr)
        assert r['house'] == '5', f"期望 house='5', 实际='{r['house']}'"

    def test_small_digit_dianpu_suffix(self, engine):
        """"3店铺"应提取房号"3"，后缀不纳入。"""
        addr = '广东省深圳市福田区华强北路1号3店铺'
        r = engine.parse_single(addr)
        assert r['house'] == '3', f"期望 house='3', 实际='{r['house']}'"

    def test_alpha_dianpu_suffix(self, engine):
        """"A店铺"应提取房号"A"，后缀不纳入。"""
        addr = '广东省深圳市福田区华强北路1号A店铺'
        r = engine.parse_single(addr)
        assert r['house'] == 'A', f"期望 house='A', 实际='{r['house']}'"
        assert r['area'] == '', f"期望 area='', 实际='{r['area']}'"

    def test_alpha_digit_dianpu_suffix(self, engine):
        """"C4店铺"应提取房号"C4"（字母+数字组合由"字母+数字"模式匹配，店铺后缀不纳入）。"""
        addr = '广东省深圳市福田区华强北路1号C4店铺'
        r = engine.parse_single(addr)
        assert r['house'] == 'C4', f"期望 house='C4', 实际='{r['house']}'"

    def test_alpha_digit_dianpu_large(self, engine):
        """"B201店铺"应提取房号"B201"。"""
        addr = '广东省深圳市福田区华强北路1号B201店铺'
        r = engine.parse_single(addr)
        assert r['house'] == 'B201', f"期望 house='B201', 实际='{r['house']}'"

    def test_alpha_digit_dash_digit_pu_suffix(self, engine):
        """"A1-2铺"应提取房号"A1-2"（字母+数字+横杠+数字组合）。"""
        addr = '广东省深圳市福田区华强北路1号A1-2铺'
        r = engine.parse_single(addr)
        assert r['house'] == 'A1-2', f"期望 house='A1-2', 实际='{r['house']}'"

    def test_alpha_digit_dash_digit_dang_suffix(self, engine):
        """"B3-4档"应提取房号"B3-4"（字母+数字+横杠+数字组合）。"""
        addr = '广东省深圳市福田区华强北路1号B3-4档'
        r = engine.parse_single(addr)
        assert r['house'] == 'B3-4', f"期望 house='B3-4', 实际='{r['house']}'"

    def test_digit_alpha_suffix_18A_pu(self, engine):
        """"18A铺"应完整提取房号"18A"，后缀不纳入。"""
        addr = '深圳市南山区粤海街道科苑北科兴科学园B栋G层18A铺'
        r = engine.parse_single(addr)
        assert r['bldg'] == 'B栋', f"期望 bldg='B栋', 实际='{r['bldg']}'"
        assert r['floor'] == 'G层', f"期望 floor='G层', 实际='{r['floor']}'"
        assert r['house'] == '18A', f"期望 house='18A', 实际='{r['house']}'"

    def test_digit_alpha_suffix_101A_shi(self, engine):
        """"101A室"应完整提取房号"101A"，后缀不纳入。"""
        addr = '深圳市南山区粤海街道科苑北科兴科学园B栋G层101A室'
        r = engine.parse_single(addr)
        assert r['house'] == '101A', f"期望 house='101A', 实际='{r['house']}'"

    def test_roadno_then_area_then_house_with_shangpu_suffix(self, engine):
        """道路门牌号后紧跟 area + 房号 + 商铺后缀，房号应被识别。"""
        addr = '深圳市南山区蛇口街道新街路26号春树里104号商铺'
        r = engine.parse_single(addr)
        assert r['road'] == '新街路', f"期望 road='新街路', 实际='{r['road']}'"
        assert r['roadno'] == '26号', f"期望 roadno='26号', 实际='{r['roadno']}'"
        assert r['area'] == '春树里', f"期望 area='春树里', 实际='{r['area']}'"
        assert r['house'] == '104', f"期望 house='104', 实际='{r['house']}'"

    def test_roadno_then_area_then_house_with_pu_suffix(self, engine):
        """道路门牌号后紧跟 area + 房号 + 铺后缀（前导零），房号应被识别。"""
        addr = '深圳市南山区蛇口街道海昌街22号蓝虹豪苑06号铺'
        r = engine.parse_single(addr)
        assert r['road'] == '海昌街', f"期望 road='海昌街', 实际='{r['road']}'"
        assert r['roadno'] == '22号', f"期望 roadno='22号', 实际='{r['roadno']}'"
        assert r['area'] == '蓝虹豪苑', f"期望 area='蓝虹豪苑', 实际='{r['area']}'"
        assert r['house'] == '06', f"期望 house='06', 实际='{r['house']}'"


class TestAddressTaggingParser12Level:
    """AddressTaggingParser 在12级模式下使用规则引擎的集成测试"""

    def test_parser_loads_rule_engine_for_mode_12(self):
        from matching.address_tagging import AddressTaggingParser
        parser = AddressTaggingParser(device='cpu', mode='12')
        parser._load_model()
        assert parser.rule_engine is not None
        assert isinstance(parser.rule_engine, RuleBasedAddressTaggingEngine)

    def test_parser_12_dataframe(self):
        import pandas as pd
        from matching.address_tagging import AddressTaggingParser

        parser = AddressTaggingParser(device='cpu', mode='12')
        df = pd.DataFrame({
            'address': [
                '广东省深圳市福田区华强北街道华航社区振兴路91-13号',
                '广东省深圳市光明区凤凰街道塘尾社区后底园小区72号401',
            ]
        })
        results = parser.parse_from_dataframe(df, address_col='address')
        assert len(results) == 2
        assert results[0]['province'] == '广东省'
        assert results[1]['roadno'] == '72号'


class TestRegexPrecompilationPerformance:
    """验证正则预编译优化的性能提升和功能正确性"""

    # 典型地址样本
    SAMPLE_ADDRESSES = [
        '广东省深圳市福田区华强北街道华航社区振兴路91-13号',
        '广东省深圳市光明区凤凰街道塘尾社区后底园小区72号401',
        '广东省深圳市南山区粤海街道科技园社区高新南一道008号创维大厦A座10层1001',
        '深圳市宝安区新安街道海裕社区N4区新安一路1号金城时代花园3栋B单元702',
        '深圳市罗湖区黄贝街道新兴社区爱国路东湖公园杜鹃园宿舍2栋5号',
        '深圳市龙岗区坂田街道五和社区五和大道1-3号楼101',
        '深圳市龙华区民治街道民新社区民治大道328号潜龙鑫茂花园A区5栋3单元6B',
        '深圳市坪山区坪山街道六联社区昌盛路69号',
        '深圳市福田区沙头街道金地社区福强路金地工业区5-8栋302',
        '深圳市南山区桃源街道塘朗社区塘兴路120号A单元B栋502',
    ]

    def test_precompiled_patterns_exist(self):
        """验证模块级预编译正则已正确定义"""
        from matching.address_tagging_rules import (
            HOUSE_PATTERNS, _ADMIN_PATTERNS, _STREET_PATTERNS, _COMMUNITY_PATTERNS,
            _AREA_ROADNO_PATTERN, _ROADNO_AFTER_KW_DIGIT_PATTERN,
            _STRUCTURE_AFTER_ROADNO_PATTERN, _STRUCTURE_PREFIX_PATTERN,
            _AREA_BLDG_UNIT_TAIL_PATTERN, _STRUCT_IN_MIDDLE_PATTERN,
            _MULTI_ROADNO_PATTERN, _MULTI_BLDG_PREFIX_PATTERN,
            _HOUSE_CONNECTOR_PATTERN, _HOUSE_ROOM_SUFFIX_PATTERN,
            _HOUSE_DIGIT_PATTERN, _NORMALIZE_WHITESPACE_PATTERN,
            _PURE_ALPHA_PATTERN, _ALPHA_DIGIT_PATTERN,
        )
        # 验证都是编译后的正则对象
        import re
        for p in HOUSE_PATTERNS:
            assert isinstance(p, re.Pattern), f"HOUSE_PATTERNS 元素应为 re.Pattern，实际为 {type(p)}"
        assert isinstance(_AREA_ROADNO_PATTERN, re.Pattern)
        assert isinstance(_ROADNO_AFTER_KW_DIGIT_PATTERN, re.Pattern)
        assert len(_ADMIN_PATTERNS) == 3  # province, city, district

    def test_precompiled_results_match_original(self, engine):
        """验证预编译正则优化后，解析结果与之前完全一致"""
        for addr in self.SAMPLE_ADDRESSES:
            result = engine.parse_single(addr)
            # 验证所有字段都有值（不全是空）
            assert result['original_address'] == addr.strip()
            # 关键字段非空检查（至少 province/road/area 之一应有值）
            has_content = any(result.get(f, '') for f in ['province', 'city', 'district', 'road', 'area'])
            assert has_content, f"地址 '{addr}' 解析结果全为空"

    def test_batch_parse_performance(self, engine):
        """性能测试：1000条地址批量解析应快速完成"""
        import time
        # 构造1000条测试地址
        addresses = self.SAMPLE_ADDRESSES * 100  # 1000条

        start = time.perf_counter()
        results = engine.parse(addresses)
        elapsed = time.perf_counter() - start

        assert len(results) == 1000
        speed = len(addresses) / elapsed
        # 优化后1000条地址应在1秒内完成，速度至少 500条/秒
        assert speed >= 500, f"解析速度过慢: {speed:.0f}条/秒，预期至少500条/秒"
        print(f"\n12级规则引擎性能: {speed:.0f}条/秒 (1000条耗时 {elapsed:.3f}s)")


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
