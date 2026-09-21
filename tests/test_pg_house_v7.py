# -*- coding: utf-8 -*-
"""测试PG函数对"X号Y号"类地址的解析（末尾Y号是房号）"""
import os
import sys
import psycopg2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SQL_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'sql', 'extract_house_number.sql'
)


def load_sql_file():
    with open(SQL_FILE, 'r', encoding='utf-8') as f:
        content = f.read()
    lines = []
    for line in content.splitlines():
        if line.lstrip().startswith('--'):
            continue
        lines.append(line)
    return '\n'.join(lines)


USER_SAMPLES = [
    # V7 新场景：末尾"Y号"是房号
    ('深圳市龙华新区民治街道民乐村民乐翠园9栋6单元824号', '824'),
    ('深圳市宝安区松岗街道潭头社区新二村一巷18号101号', '101'),
    ('深圳市罗湖区黄贝街道黄贝路1002号华丽东村12栋2单元101号', '101'),
    ('深圳市南山区蛇口街道渔村路围仔西村19号104号', '104'),
    ('深圳市罗湖区清水河街道泥岗村金碧路28号大地苑小区1栋3单元802号', '802'),
    ('深圳市罗湖区东晓街道金稻田路草埔吓屋村30号103号', '103'),
    ('深圳市龙岗区吉华街道三联塘园新村八巷1号102号', '102'),
    ('深圳市罗湖区南湖街道向西社区向西村东区47号101号', '101'),
    # V6 回归：确保"某某村X号"仍为门牌号（house为空）
    ('深圳市宝安区石岩街道塘头社区塘头大道又一村47号', ''),
    ('深圳市大鹏新区南澳街道下企沙村33号', ''),
    ('深圳市福田区赤尾村三坊67号', ''),
    # V6 回归：确保"X栋X号"/"X房X号"仍为房号
    ('广东省深圳市罗湖区黄贝街道水库社区东湖公园杜鹃园宿舍2栋4号', '4'),
    ('广东省深圳市罗湖区黄贝街道水库社区东湖公园杜鹃园花圃工作房1号', '1'),
    ('广东省深圳市南山区桃源街道龙联社区龙珠一路8号西丽体育中心综合楼14号', '14'),
    ('广东省深圳市福田区华强北路1号3号铺', '3'),
    ('广东省深圳市福田区华强北路1号5号店铺', '5'),
]


def main():
    conn = psycopg2.connect(
        host='localhost', port=5432,
        dbname='postgres', user='postgres', password='123456'
    )
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute(load_sql_file())

    print('=' * 70)
    print('PG函数"X号Y号"类地址测试（末尾Y号是房号）+ V6回归')
    print('=' * 70)
    passed = 0
    failed = 0
    for addr, expected in USER_SAMPLES:
        cur.execute("SELECT extract_house_number(%s)", (addr,))
        actual = cur.fetchone()[0] or ''
        ok = actual == expected
        status = 'OK' if ok else 'FAIL'
        if ok:
            passed += 1
        else:
            failed += 1
        print(f'{status} actual={actual!r:10s} expected={expected!r:10s}')
        if not ok:
            print(f'    地址: {addr}')

    print(f'\n总数: {passed + failed}, 通过: {passed}, 失败: {failed}')


if __name__ == '__main__':
    main()
