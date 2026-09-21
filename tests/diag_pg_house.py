# -*- coding: utf-8 -*-
"""
诊断 extract_house_number 在真实数据上的慢查询热点。
逐条计时（服务端 EXPLAIN ANALYZE 不适用于函数），用客户端逐行调用 + 重复计时，
找出耗时 top 样例并分析其特征（长度、字符构成、命中的模式路径）。
"""
import os
import re
import sys
import time

import psycopg2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))

TABLE = 'standard_address'
ADDR_COL = 'address'


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 300
    start = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    conn = psycopg2.connect(
        host=os.getenv('DB_HOST', 'localhost'), port=os.getenv('DB_PORT', 5432),
        dbname=os.getenv('DB_NAME', 'postgres'), user=os.getenv('DB_USER', 'postgres'),
        password=os.getenv('DB_PASSWORD', ''),
    )
    cur = conn.cursor()
    # 用 offset 参数化阻止 IMMUTABLE 常量折叠；取第 start..start+n-1 行
    cur.execute(
        f'SELECT {ADDR_COL} FROM (SELECT {ADDR_COL}, row_number() OVER () rn '
        f'FROM public.{TABLE}) t WHERE rn BETWEEN %s AND %s', (start, start + n - 1)
    )
    addrs = [r[0] for r in cur.fetchall() if r[0]]

    results = []
    for addr in addrs:
        # 每条重复计时 3 次取平均（单次太快时用循环放大）
        t0 = time.perf_counter()
        cur.execute('SELECT extract_house_number(a.addr || %s) FROM '
                    '(SELECT %s::text AS addr) a, generate_series(1, 3)', ('', addr))
        cur.fetchall()
        dt = (time.perf_counter() - t0) / 3
        results.append((dt, addr))

    results.sort(reverse=True)
    total = sum(dt for dt, _ in results)
    print(f'采样 {len(results)} 行, 总耗时 {total:.2f}s, 平均 {total / len(results) * 1000:.2f} ms/行')
    print('-' * 100)
    print('最慢 TOP 15：')
    for dt, addr in results[:15]:
        print(f'  {dt * 1000:8.2f} ms  len={len(addr):4d}  {addr[:80]}')
    print('-' * 100)
    # 耗时与长度的相关性
    slow = [r for r in results if r[0] > 0.01]
    print(f'超过 10ms 的行数: {len(slow)} / {len(results)}')
    # 长度分布
    lens = sorted(len(a) for _, a in results)
    print(f'地址长度: min={lens[0]}, 中位={lens[len(lens) // 2]}, max={lens[-1]}')
    conn.close()


if __name__ == '__main__':
    main()
