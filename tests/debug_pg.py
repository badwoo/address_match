# -*- coding: utf-8 -*-
"""临时调试脚本：测试 PG extract_house_number 对特定地址的解析"""
import psycopg2

SQL_FILE = 'sql/extract_house_number.sql'

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

    test_cases = [
        '40号105店',
        '深圳市龙岗区横岗街道横岗社区新光一街40号105店',
        '5层-511室',
        '深圳市龙岗区坂田街道象角塘社区中浩工业城C5栋厂房C5栋5层-511室',
        '深圳市宝安区石岩街道罗租社区罗租中新村一区4号101室商铺',
        '深圳市福田区南园街道滨河路与华强南路交汇处御景华城花园1层L110/111/124室商铺',
        '17号商铺',
        '深圳市龙岗区坂田街道岗头社区中心围村中围路17号商铺',
    ]

    for addr in test_cases:
        cur.execute("SELECT extract_house_number(%s)", (addr,))
        result = cur.fetchone()[0] or ''
        print(f'{addr}')
        print(f'  -> "{result}"')
        print()

if __name__ == '__main__':
    main()
