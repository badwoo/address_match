# -*- coding: utf-8 -*-
"""测试PG函数对V9市场/商铺/档口类房号地址的解析（样例复用test_py_house_v9）"""
import os
import sys
import psycopg2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.test_py_house_v9 import USER_SAMPLES_V9

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


def main():
    conn = psycopg2.connect(
        host='localhost', port=5432,
        dbname='postgres', user='postgres', password='123456'
    )
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute(load_sql_file())

    print('=' * 70)
    print(f'PG函数 V9 市场/商铺/档口类房号测试（{len(USER_SAMPLES_V9)} 样例）')
    print('=' * 70)
    passed = 0
    failed = 0
    for addr, expected in USER_SAMPLES_V9:
        cur.execute("SELECT extract_house_number(%s)", (addr,))
        actual = cur.fetchone()[0] or ''
        ok = actual == expected
        status = 'OK' if ok else 'FAIL'
        if ok:
            passed += 1
        else:
            failed += 1
        print(f'{status} actual={actual!r:30s} expected={expected!r}')
        if not ok:
            print(f'    地址: {addr}')

    print(f'\n总数: {passed + failed}, 通过: {passed}, 失败: {failed}')


if __name__ == '__main__':
    main()
