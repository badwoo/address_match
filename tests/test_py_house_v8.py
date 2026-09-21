# -*- coding: utf-8 -*-
"""
测试V8特殊房号地址样例（多房号/字母数字混合/特殊连接符/括号房号）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from matching.address_tagging_rules import RuleBasedAddressTaggingEngine

USER_SAMPLES_V8 = [
    ('深圳市南山区南油A区11栋102室#', '102'),
    ('深圳市福田区香蜜湖街道竹林社区金众街2号益华综合楼A、B栋B栋A322B_01', 'A322B_01'),
    ('深圳市福田区沙头街道天安社区深南大道6021号喜年中心A栋12B19G1', '12B19G1'),
    ('深圳市前海深港合作区南山街道梦海大道5033号前海卓越金融中心3号楼B1-49.50', 'B1-49.50'),
    ('深圳市宝安区西乡街道固成社区宝安大道4231号红湾创客中心B3栋3A08-(2)', '3A08-(2)'),
    ('深圳市罗湖区南湖街道嘉南社区春风路3019号庐山花园B座24D-F、D1', '24D-F、D1'),
    ('深圳市龙岗区平湖街道禾花社区平新北路163号广弘美居F栋F202、203', 'F202、203'),
    ('深圳市南山区粤海街道大冲社区深南大道9678号大冲商务中心(二期)1栋2号楼6A1BC', '6A1BC'),
    ('深圳市罗湖区桂园街道老围社区深南东路5016号京基100B座22层B-2201、2202A', 'B-2201、2202A'),
    ('深圳市龙岗区平湖街道华南大道一号华南国际印刷纸品包装物流区二期2号楼B1层B1JF428', 'B1JF428'),
    ('深圳市宝安区西乡街道办锦花路天骄世家1栋106商铺之一', '106'),
    ('深圳市龙岗区平湖街道华南大道一号华南国际印刷纸品包装物流区二期2号楼B1层B1JF105、106号', 'B1JF105、106'),
    ('深圳市罗湖区翠竹街道翠锦社区布心路3033号水贝壹号B1-09——CB109柜', 'B1-09——CB109'),
    ('深圳市福田区华强北街道华航社区中航路18号新亚洲国利大厦2层新亚洲电子市场二期N2C248', 'N2C248'),
    ('深圳市龙岗区中心城龙城37区黄阁路阳光天健城3栋2层196—215号商铺', '196—215'),
    ('深圳市福田区民田路新华保险大厦13楼1311、1312、1313室', '1311、1312、1313'),
    ('深圳市宝安区西乡街道河西社区金雅新苑6号(一楼102铺)', '102'),
    ('深圳市福田区福保街道石厦社区石厦北二街西新天世纪商务中心A.B座A4207A6', 'A4207A6'),
    ('深圳市南山区招商街道蛇口工业大道四海加油站右侧沃尔玛购物广场一层F1F0009', 'F1F0009'),
]


def main():
    engine = RuleBasedAddressTaggingEngine()
    passed = 0
    failed = 0

    print('=' * 90)
    print('V8 特殊房号地址样例测试（19 个）')
    print('=' * 90)
    for addr, expected in USER_SAMPLES_V8:
        result = engine.parse_single(addr)
        actual = result.get('house', '')
        ok = actual == expected
        status = 'OK' if ok else 'FAIL'
        if ok:
            passed += 1
        else:
            failed += 1
        print(f'{status} house={actual!r:25s} 期望={expected!r}')
        if not ok:
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
