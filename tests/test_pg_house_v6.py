# -*- coding: utf-8 -*-
"""测试PG函数对"某某村X号"类地址的解析"""
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
    ('深圳市宝安区石岩街道塘头社区塘头大道又一村47号', ''),
    ('深圳市大鹏新区南澳街道下企沙村33号', ''),
    ('深圳市福田区赤尾村三坊67号', ''),
    # 回归测试：确保"X号"是房号的场景不受影响
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
    print('PG函数"某某村X号"类地址测试')
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
        print(f'{status} actual={actual!r:15s} expected={expected!r:15s}')
        if not ok:
            print(f'    地址: {addr}')

    print(f'\n总数: {passed + failed}, 通过: {passed}, 失败: {failed}')


if __name__ == '__main__':
    main()
