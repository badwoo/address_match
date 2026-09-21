# -*- coding: utf-8 -*-
"""
服务端精确计时：DO 块内循环调用 extract_house_number，排除网络往返与常量折叠干扰。
对 standard_address 前 N 行整体计时 + 对单条典型地址重复计时。
"""
import os
import sys

import psycopg2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))

# 典型路径样例：roadno结尾（最坏路径）/ 纯数字房号 / 附X号 / 之X / 无匹配
SAMPLES = [
    ('roadno结尾(最坏)', '广东省深圳市福田区深南大道137号'),
    ('纯数字房号', '广东省深圳市宝安区新安街道甲岸社区宝民一路甲岸村22号401'),
    ('附X号', '广东省深圳市龙华区和平路8089号附2号'),
    ('之X', '广东省深圳市南山区科苑路4148号之二'),
    ('楼栋房号', '广东省深圳市罗湖区宝安北路8075号3栋3楼301室'),
    ('无匹配', '广东省深圳市南山区桃园路8278号深圳湾科技生态园'),
]


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 2000
    conn = psycopg2.connect(
        host=os.getenv('DB_HOST', 'localhost'), port=os.getenv('DB_PORT', 5432),
        dbname=os.getenv('DB_NAME', 'postgres'), user=os.getenv('DB_USER', 'postgres'),
        password=os.getenv('DB_PASSWORD', ''),
    )
    cur = conn.cursor()
    conn.autocommit = True

    print('=' * 78)
    # 1. 整体：真实表前 n 行（服务端计时）
    # 注意：count(fn(..)) 而非 count(*)——外层不引用函数列会被优化器消除，函数不执行
    cur.execute(f"""
        DO $do$ DECLARE t timestamptz; c int;
        BEGIN
            t := clock_timestamp();
            SELECT count(extract_house_number(address)) INTO c FROM
                (SELECT address FROM public.standard_address LIMIT {n}) s;
            RAISE NOTICE 'SERVER_WHOLE % rows: % ms', {n},
                round(extract(epoch from (clock_timestamp()-t))*1000::numeric, 1);
        END $do$;
    """)
    whole_ms = None
    for line in conn.notices:
        if 'SERVER_WHOLE' in line:
            whole_ms = line.strip().replace('NOTICE:', '').strip()
    conn.notices.clear()
    print(f'  服务端整体计时: {whole_ms}')

    # 2. 单样例：服务端重复 500 次
    print(f'{"样例":<20} {"单次耗时(us)":>12}   地址')
    for label, addr in SAMPLES:
        lit = cur.mogrify('SELECT %s::text', (addr,)).decode('utf-8')
        cur.execute(f"""
            DO $do$ DECLARE t timestamptz; n int := 500;
            BEGIN
                t := clock_timestamp();
                -- || g::text 引用运行时列，防止计划期常量折叠导致函数只执行 1 次
                PERFORM extract_house_number(a.addr || g::text) FROM
                    ({lit} AS addr) a, generate_series(1, n) g;
                RAISE NOTICE 'SAMPLE % us',
                    round(extract(epoch from (clock_timestamp()-t))*1e6/n::numeric, 1);
            END $do$;
        """)
        # 从 notices 取结果
        us = None
        for line in conn.notices:
            if 'SAMPLE' in line:
                us = line.strip().split('SAMPLE')[1].strip().rstrip('us').strip()
        conn.notices.clear()
        print(f'{label:<20} {us:>12}   {addr}')
    print('=' * 78)
    conn.close()


if __name__ == '__main__':
    main()
