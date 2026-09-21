# -*- coding: utf-8 -*-
"""
测试"X号Y号"类地址（末尾两个"号"，前者门牌号，后者房号）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from matching.address_tagging_rules import RuleBasedAddressTaggingEngine

# 8个用户标注样例：末尾"Y号"是房号
USER_SAMPLES_V7 = [
    ('深圳市龙华新区民治街道民乐村民乐翠园9栋6单元824号', '824'),
    ('深圳市宝安区松岗街道潭头社区新二村一巷18号101号', '101'),
    ('深圳市罗湖区黄贝街道黄贝路1002号华丽东村12栋2单元101号', '101'),
    ('深圳市南山区蛇口街道渔村路围仔西村19号104号', '104'),
    ('深圳市罗湖区清水河街道泥岗村金碧路28号大地苑小区1栋3单元802号', '802'),
    ('深圳市罗湖区东晓街道金稻田路草埔吓屋村30号103号', '103'),
    ('深圳市龙岗区吉华街道三联塘园新村八巷1号102号', '102'),
    ('深圳市罗湖区南湖街道向西社区向西村东区47号101号', '101'),
]


def main():
    engine = RuleBasedAddressTaggingEngine()
    passed = 0
    failed = 0
    failed_cases = []

    print('=' * 90)
    print('V7 "X号Y号"类地址测试（末尾Y号是房号）')
    print('=' * 90)
    for addr, expected in USER_SAMPLES_V7:
        result = engine.parse_single(addr)
        actual = result.get('house', '')
        ok = actual == expected
        status = 'OK' if ok else 'FAIL'
        if ok:
            passed += 1
        else:
            failed += 1
            failed_cases.append((addr, expected, actual, result))
        print(f'{status} house={actual!r:10s} 期望={expected!r:10s}')
        # 打印详细解析结果（无论成败都打印，便于分析）
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
