# -*- coding: utf-8 -*-
"""调试"西丽体育中心综合楼14号"的解析过程"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from matching.address_tagging_rules import RuleBasedAddressTaggingEngine

addr = '广东省深圳市南山区桃源街道龙联社区龙珠一路8号西丽体育中心综合楼14号'
engine = RuleBasedAddressTaggingEngine()
r = engine.parse_single(addr)
print(f"地址: {addr}")
print(f"original_address: {r.get('original_address')!r}")
print(f"road={r.get('road')!r} roadno={r.get('roadno')!r}")
print(f"area={r.get('area')!r} bldg={r.get('bldg')!r}")
print(f"unit={r.get('unit')!r} floor={r.get('floor')!r} house={r.get('house')!r}")
