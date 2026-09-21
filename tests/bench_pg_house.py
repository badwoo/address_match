# -*- coding: utf-8 -*-
"""
extract_house_number 函数性能基准测试。

用法：
    python tests/bench_pg_house.py          # 对真实表数据采样计时
    python tests/bench_pg_house.py 200000   # 指定采样行数

计时方式：
    1. 真实表采样：SELECT extract_house_number(address) FROM <table> LIMIT N
       （纯函数调用计时，不含 UPDATE/IO，可反映函数本身优化效果）
    2. 典型样例循环：19 个 V8 样例 + 常见 roadno 样例各重复 N 次，
       覆盖「末尾纯数字/横杠号/字母数字号/无匹配」等不同路径
"""
import os
import sys
import time

import psycopg2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))

# 真实表（优先 enterprise_address，其次取第一个含 address 列的表）
TABLE_CANDIDATES = ['enterprise_address', 'standard_address']

# 典型样例（覆盖不同执行路径：快速通道/模式2动态正则/字母数字号/顿号/无匹配）
TYPICAL_SAMPLES = [
    '广东省深圳市福田区华强北街道华航社区振兴路91-13号B101',   # 末尾字母数字（模式10）
    '广东省深圳市宝安区新安街道甲岸社区宝民一路甲岸村22号401',  # 末尾纯数字（模式11）
    '广东省深圳市福田区华强北街道华航社区振兴路91-13号',        # roadno（模式2命中后被过滤）
    '广东省深圳市罗湖区黄贝街道水库社区东湖公园杜鹃园宿舍2栋4号',  # 数字+号（模式13b）
    '深圳市龙华新区民治街道民乐村民乐翠园9栋6单元824号',         # 数字+号
    '深圳市福田区民田路新华保险大厦13楼1311、1312、1313室',      # 顿号多房号（模式0）
    '深圳市福田区香蜜湖街道竹林社区金众街2号益华综合楼A、B栋B栋A322B_01',  # 下划线
    '深圳市南山区粤海街道大冲社区深南大道9678号大冲商务中心(二期)1栋2号楼6A1BC',  # 多段交替
    '广东省深圳市南山区桃源街道峰景社区北环大道8028号方直珑樾山花园1栋负3层',   # 无匹配（全模式跑完）
    '广东省深圳市南山区科技园科苑路15号科技园研发楼',             # 无匹配（全模式跑完）
]


def main():
    sample_rows = int(sys.argv[1]) if len(sys.argv) > 1 else 100000
    conn = psycopg2.connect(
        host=os.getenv('DB_HOST', 'localhost'),
        port=os.getenv('DB_PORT', 5432),
        dbname=os.getenv('DB_NAME', 'postgres'),
        user=os.getenv('DB_USER', 'postgres'),
        password=os.getenv('DB_PASSWORD', ''),
    )
    cur = conn.cursor()

    # 找真实表
    table = None
    addr_col = None
    for t in TABLE_CANDIDATES:
        cur.execute(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name=%s AND column_name IN ('address','original_address')",
            (t,),
        )
        if cur.fetchone():
            cur.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name=%s AND column_name IN ('address','original_address') "
                "ORDER BY column_name='address' DESC",
                (t,),
            )
            addr_col = cur.fetchone()[0]
            table = t
            break
    if table is None:
        cur.execute(
            "SELECT table_name, column_name FROM information_schema.columns "
            "WHERE table_schema='public' AND column_name IN ('address','original_address') LIMIT 1"
        )
        row = cur.fetchone()
        if row:
            table, addr_col = row

    print('=' * 70)

    # 基准 1：真实表采样
    if table:
        cur.execute(f'SELECT count(*) FROM public.{table}')
        total = cur.fetchone()[0]
        n = min(sample_rows, total)
        t0 = time.perf_counter()
        cur.execute(
            f'SELECT count(extract_house_number({addr_col})) FROM '
            f'(SELECT {addr_col} FROM public.{table} LIMIT %s) s', (n,)
        )
        cur.fetchone()
        elapsed = time.perf_counter() - t0
        print(f'[真实表] {table}.{addr_col} 采样 {n} 行: {elapsed:.2f}s '
              f'({n / elapsed:.0f} 行/s, {elapsed / n * 1000:.3f} ms/千行)')
    else:
        print('[真实表] 未找到含地址列的表，跳过')

    # 基准 2：典型样例循环（每样例重复 2000 次，覆盖不同路径）
    repeats = 2000
    t0 = time.perf_counter()
    for addr in TYPICAL_SAMPLES:
        cur.execute(
            'SELECT extract_house_number(%s) FROM generate_series(1, %s)', (addr, repeats)
        )
        cur.fetchall()
    elapsed = time.perf_counter() - t0
    calls = repeats * len(TYPICAL_SAMPLES)
    print(f'[典型样例] {len(TYPICAL_SAMPLES)} 个样例 x {repeats} 次 = {calls} 次调用: '
          f'{elapsed:.2f}s ({calls / elapsed:.0f} 次/s, {elapsed / calls * 1e6:.1f} us/次)')
    print('=' * 70)
    conn.close()


if __name__ == '__main__':
    main()
