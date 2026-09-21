# -*- coding: utf-8 -*-
"""
验证 sql/extract_house_number.sql 中 extract_house_number 函数的正确性（V2）。

测试覆盖：
    1. 用户新提供的 38 个地址样例（房号解析）
    2. 原有测试用例回归（确保不破坏现有解析结果）
"""
import os
import sys
import psycopg2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


SQL_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'sql', 'extract_house_number.sql'
)


def load_sql_file():
    """读取 SQL 文件，移除注释行，返回可执行 SQL。"""
    with open(SQL_FILE, 'r', encoding='utf-8') as f:
        content = f.read()
    lines = []
    for line in content.splitlines():
        if line.lstrip().startswith('--'):
            continue
        lines.append(line)
    return '\n'.join(lines)


# 用户提供的地址样例（地址, 期望房号）
USER_SAMPLES = [
    ('深圳市福田区福保街道福田保税区金花路29号华宝1号大厦1楼111A号', '111A'),
    ('深圳市福田区8卦2路宿舍区32栋103A号', '103A'),
    ('深圳市福田区华富街道新田社区彩田路3030号橄榄鹏苑1楼1号Z105-1号商铺', 'Z105-1'),
    ('深圳市福田区8卦1路鹏盛村33区8栋第壹层8110A号', '8110A'),
    ('深圳市福田区福田区梅华路103号光荣大厦7楼707(仅限办公)', '707'),
    ('深圳市福田区莲花街道红荔西路南天健世纪花园1栋商场3B号商铺', '3B'),
    ('深圳市福田区皇岗路皇城广场皇溪苑1909(仅限办公)', '1909'),
    ('深圳市福田区华发北路高科德通信数码市场1B057A号', '1B057A'),
    ('深圳市福田区8卦2路8卦岭工业区48栋1层105号。', '105'),
    ('深圳市福田区梅林街道梅华路绅宝花园绅泰阁1楼B-11号铺', 'B-11'),
    ('深圳市福田区华强北街道荔村社区华强北路2028号华联发419栋4层A4480A号', 'A4480A'),
    ('深圳市福田区深南大道6025号英龙展业中心大厦1409室(仅限办公)', '1409'),
    ('深圳市福田区莲花街道景田北路景雅居商城首层226档铺', '226'),
    ('深圳市福田区香蜜湖街道香蜜湖度假村美食广场A17-3号铺', 'A17-3'),
    ('深圳市福田区梅林街道深圳市福田区卓越梅林中心广场(南区)B座B单元11层1108B号', '1108B'),
    ('深圳市福田区车公庙泰然9路盛唐商务大厦18层1813号(仅限办公)', '1813'),
    ('深圳市福田区滨河大道上沙创新科技园5栋2楼2B01(仅限办公)', '2B01'),
    ('深圳市福田区华强北街道华强北路赛格广场3楼3C11A号', '3C11A'),
    ('深圳市福田区8卦5街23号远东大厦国安居装饰建材市场内第A137号铺。', 'A137'),
    ('深圳市福田区南园街道巴登社区深南中路1095号新城市广场LG层LG-M-05号铺', 'LG-M-05'),
    ('深圳市福田区华强北街道华航社区深南中路3018号世纪汇商场4层417A号商铺', '417A'),
    ('深圳市福田区车公庙泰然9路海松大厦B-1507(仅限办公)', 'B-1507'),
    ('深圳市福田区福田保税区桂花路11号帝港海湾豪园C座25AF', '25AF'),
    ('深圳市福田区南园街道南园社区南园路68号上步大厦11层11KL', '11KL'),
    ('深圳市福田区滨河路北彩田路东交汇处联合广场A栋塔楼A2603(仅限办公)', 'A2603'),
    ('深圳市福田区南园街道东园路埔尾村26栋104埔', '104'),
    ('深圳市福田区华强北街道华红社区红荔路3002号交行大厦510B号', '510B'),
    ('深圳市福田区香轩路东海花园福禄居1号商店1层商场G23C号铺', 'G23C'),
    ('深圳市福田区深南大道7888号东海国际中心A-3501(03)', 'A-3501(03)'),
    ('深圳市福田区华富街道莲花3村社区福中路32号振业花园9栋104S号商铺', '104S'),
    ('深圳市福田区香蜜湖街道东海社区深南大道7002号财富广场B座B11HI', 'B11HI'),
    ('深圳市福田区华强北街道深南中路2008号华联大厦1116室(入驻深圳市网丰商务秘书有限公司)', '1116'),
    ('深圳市福田区福田街道福山社区滨河大道5022号联合广场A座4412(入驻圳浩商务秘书(深圳)有限公司)', '4412'),
    ('深圳市福田区沙头街道天安社区泰然4路29号天安创新科技广场1期A座1505AB', '1505AB'),
    ('深圳市福田区南园街道沙埔头社区沙埔头大厦1、2、3、4栋爱华路34号酷联通讯市场KL8122铺面', 'KL8122'),
    ('深圳市福田区南园街道巴登社区深南中路1095号新城市广场LG层-LM-11号商铺', '-LM-11'),
    ('深圳市福田区沙头街道天安社区泰然4路6号天安数码时代大厦主楼102-103-2号商铺', '102-103-2'),
    ('深圳市福田区香蜜湖街道农园社区侨香路2023号翠海花园18B号铺', '18B'),
]

# 原有测试用例回归（地址, 期望房号）- 来自 test_address_tagging_rules.py
REGRESSION_SAMPLES = [
    ('广东省深圳市宝安区新安街道甲岸社区宝民一路甲岸村22号401', '401'),
    ('广东省深圳市福田区沙头街道新洲社区新洲北村57-1号8A', '8A'),
    ('广东省深圳市南山区桃源街道龙联社区龙珠一路8号西丽体育中心综合楼14号', '14'),
    ('广东省深圳市罗湖区黄贝街道水库社区东湖一街1号园林集团公司会议室205', '205'),
    ('广东省深圳市罗湖区黄贝街道罗芳社区延芳路600号莲塘口岸员工食堂1栋101', '101'),
    ('广东省深圳市宝安区西乡街道凤凰岗社区莲塘坑工业区C栋206', '206'),
    ('广东省深圳市罗湖区南湖街道罗湖社区人民南路罗湖村116号103', '103'),
    ('广东省深圳市南山区西丽街道松坪山社区乌石头路13-9高新北文体中心101', '101'),
    ('广东省深圳市南山区西丽街道阳光社区丽康路珍果园果场1号101', '101'),
    ('广东省深圳市南山区西丽街道松坪山社区朗康路13号3号集装箱101', '101'),
    ('广东省深圳市罗湖区黄贝街道水库社区东湖公园杜鹃园宿舍2栋4号', '4'),
    ('广东省深圳市罗湖区黄贝街道水库社区东湖公园杜鹃园花圃工作房1号', '1'),
    ('广东省深圳市罗湖区黄贝街道新兴社区经二路48号罗湖体育馆之一北-101', '101'),
    ('广东省深圳市南山区桃源街道峰景社区北环大道8028号方直珑樾山花园1栋负3层', ''),
    ('广东省深圳市南山区桃源街道峰景社区北环大道8028号方直珑樾山花园1栋101房', '101'),
    ('广东省深圳市罗湖区黄贝街道水库社区爱国路东湖公园杜鹃园宿舍2栋5号', '5'),
    ('广东省深圳市罗湖区黄贝街道水库社区爱国路东湖公园杜鹃园宿舍2栋15号', '15'),
    ('广东省深圳市南山区桃源街道珠光社区珠光路新屋村工业区第1栋302', '302'),
    ('广东省深圳市罗湖区莲塘街道坳下社区坳下村128号金田工业区5栋右侧301', '301'),
    ('广东省深圳市罗湖区南湖街道罗湖桥社区建设路1001号火车站综合大楼负一层深港融合商业街-10A', '10A'),
    ('广东省深圳市罗湖区黄贝街道黄贝岭社区深南东路1038号黄贝岭经泽大厦7B12', '7B12'),
    ('广东省深圳市罗湖区南湖街道嘉北社区人民南路3002号国际贸易中心大厦A区L1-21A', 'L1-21A'),
    ('广东省深圳市罗湖区黄贝街道新兴社区经二路38号安业花园C2栋附01', '附01'),
    ('广东省深圳市福田区华强北街道华航社区振兴路91-13号B101', 'B101'),
    ('广东省深圳市福田区华强北街道华航社区振兴路91-13号', ''),
    ('深圳市宝安区西乡街道丽景城3栋118商铺', '118'),
    ('深圳市福田区华强北路1号A铺', 'A'),
    ('广东省深圳市南山区科技园南区A101B', 'A101B'),
]


def main():
    conn = psycopg2.connect(
        host='localhost', port=5432,
        dbname='postgres', user='postgres', password='123456'
    )
    conn.autocommit = True
    cur = conn.cursor()

    # 创建 PG 函数
    cur.execute(load_sql_file())

    # ========== 测试 1：用户提供的地址样例 ==========
    print('=' * 70)
    print('测试 1：用户提供的地址样例（38 个）')
    print('=' * 70)
    passed = 0
    failed = 0
    failed_cases = []

    for addr, expected in USER_SAMPLES:
        cur.execute("SELECT extract_house_number(%s)", (addr,))
        actual = cur.fetchone()[0] or ''
        if actual == expected:
            passed += 1
        else:
            failed += 1
            failed_cases.append((addr, expected, actual))

    total = passed + failed
    accuracy = passed / total * 100 if total > 0 else 0
    print(f'总数: {total}, 通过: {passed}, 失败: {failed}')
    print(f'准确率: {accuracy:.2f}%\n')

    if failed_cases:
        print('---- 失败用例 ----')
        for addr, expected, actual in failed_cases:
            print(f'地址: {addr}')
            print(f'  期望: "{expected}"')
            print(f'  实际: "{actual}"')
            print()

    # ========== 测试 2：原有测试用例回归 ==========
    print('=' * 70)
    print('测试 2：原有测试用例回归（27 个）')
    print('=' * 70)
    reg_passed = 0
    reg_failed = 0
    reg_failed_cases = []

    for addr, expected in REGRESSION_SAMPLES:
        cur.execute("SELECT extract_house_number(%s)", (addr,))
        actual = cur.fetchone()[0] or ''
        if actual == expected:
            reg_passed += 1
        else:
            reg_failed += 1
            reg_failed_cases.append((addr, expected, actual))

    reg_total = reg_passed + reg_failed
    reg_accuracy = reg_passed / reg_total * 100 if reg_total > 0 else 0
    print(f'总数: {reg_total}, 通过: {reg_passed}, 失败: {reg_failed}')
    print(f'准确率: {reg_accuracy:.2f}%\n')

    if reg_failed_cases:
        print('---- 回归失败用例 ----')
        for addr, expected, actual in reg_failed_cases:
            print(f'地址: {addr}')
            print(f'  期望: "{expected}"')
            print(f'  实际: "{actual}"')
            print()

    # ========== 总结 ==========
    print('=' * 70)
    print('总结')
    print('=' * 70)
    total_all = total + reg_total
    passed_all = passed + reg_passed
    failed_all = failed + reg_failed
    accuracy_all = passed_all / total_all * 100 if total_all > 0 else 0
    print(f'总用例: {total_all}, 总通过: {passed_all}, 总失败: {failed_all}')
    print(f'总准确率: {accuracy_all:.2f}%')

    cur.close()
    conn.close()

    # 非零退出码（有失败时）
    if failed_all > 0:
        sys.exit(1)


if __name__ == '__main__':
    main()
