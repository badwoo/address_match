# -*- coding: utf-8 -*-
"""
测试现有规则对14个V5特殊地址样例的解析情况。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from matching.address_tagging_rules import RuleBasedAddressTaggingEngine

USER_SAMPLES_V5 = [
    ('广东省深圳市坪山区龙田街道竹坑社区翠景路37号坪山城投智园C栋C201裙楼', 'C201'),
    ('广东省深圳市福田区园岭街道红荔社区园岭四街6号园中花园A栋3303宿舍', '3303'),
    ('广东省深圳市福田区南园街道赤尾社区赤尾村一坊15号104杂物间', '104'),
    ('广东省深圳市福田区沙头街道金城社区白石路4号福安小区A栋302之2', '302'),
    ('广东省深圳市福田区沙头街道金城社区白石路4号福安小区C栋703之3', '703'),
    ('广东省深圳市宝安区松岗街道沙浦社区满京华云著花园（二期）1号楼106之8', '106'),
    ('广东省深圳市宝安区松岗街道潭头社区潭头新一村十三巷3号201之4', '201'),
    ('广东省深圳市宝安区松岗街道松岗社区松白路7035号B栋402之3', '402'),
    ('广东省深圳市光明区马田街道石家社区将石水库路76号1栋201A夹层', '201A'),
    ('广东省深圳市光明区马田街道将围社区塘下围新村61号101夹层', '101'),
    ('广东省深圳市光明区马田街道将围社区足球场小区74区209夹层', '209'),
    ('广东省深圳市光明区凤凰街道塘尾社区足球场小区51号映隆苑107夹层', '107'),
    ('广东省深圳市南山区桃源街道朗山社区留仙大道深圳大学附属中学320教室', '320'),
    ('广东省深圳市南山区桃源街道朗山社区留仙大道深圳大学附属教育集团外国语中学409教师宿舍', '409'),
]


def main():
    engine = RuleBasedAddressTaggingEngine()
    passed = 0
    failed = 0
    failed_cases = []

    print('=' * 90)
    print('V5 特殊地址样例测试（14 个）')
    print('=' * 90)
    for addr, expected in USER_SAMPLES_V5:
        result = engine.parse_single(addr)
        actual = result.get('house', '')
        ok = actual == expected
        status = 'OK' if ok else 'FAIL'
        if ok:
            passed += 1
        else:
            failed += 1
            failed_cases.append((addr, expected, actual, result))
        print(f'{status} [{actual!r:20s}] 期望[{expected!r:20s}]')
        if not ok:
            # 打印详细解析结果
            print(f'    地址: {addr}')
            print(f'    road={result.get("road")!r} roadno={result.get("roadno")!r}')
            print(f'    area={result.get("area")!r} bldg={result.get("bldg")!r}')
            print(f'    unit={result.get("unit")!r} floor={result.get("floor")!r} house={result.get("house")!r}')
            print()

    total = passed + failed
    print('=' * 90)
    print(f'总数: {total}, 通过: {passed}, 失败: {failed}')
    print(f'准确率: {passed / total * 100:.2f}%' if total > 0 else 'N/A')
    print('=' * 90)


if __name__ == '__main__':
    main()
