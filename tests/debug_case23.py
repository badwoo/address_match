# -*- coding: utf-8 -*-
"""调试用例23的处理流程。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from matching.address_tagging_rules import (
    RuleBasedAddressTaggingEngine, BLDG_PATTERN, FLOOR_PATTERN,
    HOUSE_PATTERNS, _AREA_ROADNO_PATTERN, _HOUSE_SUFFIX
)

addr = '中浩工业城C5栋厂房C5栋5层-511室'
engine = RuleBasedAddressTaggingEngine()

# 模拟 _parse_single 到 _extract_structure 的输入
# 行政区划切分后 rest = '中浩工业城C5栋厂房C5栋5层-511室'
# 无道路关键字，_extract_road_and_roadno 返回 ('', '', '', text)
text = addr

print(f'文本: {text}')
print(f'文本长度: {len(text)}')
for i, ch in enumerate(text):
    print(f'  [{i}] = {ch!r}')

# 检查 _extract_area_roadno_structure
m = _AREA_ROADNO_PATTERN.search(text)
print(f'\n_AREA_ROADNO_PATTERN 匹配: {m}')

# 检查 BLDG_PATTERN
bldg_matches = list(BLDG_PATTERN.finditer(text))
print(f'\nBLDG_PATTERN 匹配:')
for bm in bldg_matches:
    print(f'  group={bm.group(1)!r} start={bm.start()} end={bm.end()}')

# 检查 FLOOR_PATTERN
floor_matches = list(FLOOR_PATTERN.finditer(text))
print(f'\nFLOOR_PATTERN 匹配:')
for fm in floor_matches:
    print(f'  group={fm.group(1)!r} start={fm.start()} end={fm.end()}')

# 检查 _find_house
print(f'\n_find_house 匹配:')
for i, pattern in enumerate(HOUSE_PATTERNS):
    matches = list(pattern.finditer(text))
    if matches:
        print(f'  模式[{i}]: {pattern.pattern}')
        for m in matches:
            print(f'    group={m.group(1)!r} start={m.start()} end={m.end()}')
        # _find_house 取最靠后的匹配
        last = matches[-1]
        print(f'  → 选中: group={last.group(1)!r} start={last.start()}')
        break

# 完整解析结果
print(f'\n完整解析结果:')
result = engine.parse_single(addr)
for k, v in result.items():
    print(f'  {k}: {v!r}')
