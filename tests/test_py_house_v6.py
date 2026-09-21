# -*- coding: utf-8 -*-
"""
测试"某某村X号"类地址（无后续号码时X号应为门牌号而非房号）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from matching.address_tagging_rules import RuleBasedAddressTaggingEngine

USER_SAMPLES = [
    ('深圳市宝安区石岩街道塘头社区塘头大道又一村47号', ''),
    ('深圳市大鹏新区南澳街道下企沙村33号', ''),
    ('深圳市福田区赤尾村三坊67号', ''),
]


def main():
    engine = RuleBasedAddressTaggingEngine()
    print('=' * 90)
    print('"某某村X号"类地址测试（期望house为空，X号是门牌号）')
    print('=' * 90)
    for addr, expected in USER_SAMPLES:
        result = engine.parse_single(addr)
        actual = result.get('house', '')
        ok = actual == expected
        status = 'OK' if ok else 'FAIL'
        print(f'{status} house={actual!r:15s} 期望={expected!r:15s}')
        print(f'    地址: {addr}')
        print(f'    road={result.get("road")!r} roadno={result.get("roadno")!r}')
        print(f'    area={result.get("area")!r} bldg={result.get("bldg")!r}')
        print(f'    unit={result.get("unit")!r} floor={result.get("floor")!r} house={result.get("house")!r}')
        print()


if __name__ == '__main__':
    main()
