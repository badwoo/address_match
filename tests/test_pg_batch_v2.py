# -*- coding: utf-8 -*-
"""
测试 batch_update_house_number 存储过程（V2：p_id_col 参数版）。

验证：
    1. PROCEDURE 创建成功（语法正确）
    2. 批量更新功能正确（能解析的写入房号，不能解析的保持空）
    3. 幂等性（重复调用不重复更新）
    4. p_where_clause 过滤
    5. 参数校验（p_id_col 为空/不存在/非数值类型时抛异常）
"""
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


# 测试地址：包含能解析出房号和不能解析出房号的地址
TEST_ADDRESSES = [
    # 能解析出房号的地址
    ('广东省深圳市福田区华强北街道华航社区振兴路91-13号B101', 'B101'),
    ('广东省深圳市宝安区新安街道甲岸社区宝民一路甲岸村22号401', '401'),
    ('深圳市宝安区西乡街道丽景城3栋118商铺', '118'),
    ('深圳市福田区华强北路1号A铺', 'A'),
    ('深圳市龙岗区坂田街道下雪村下雪路2#A栋厂房303#', '303'),
    ('深圳市龙岗区坂田街道杨美社区疏导美食街A07-08号商铺', 'A07-08'),
    ('深圳市宝安区石岩街道罗租社区罗租中新村一区4号101室商铺', '101'),
    ('深圳市宝安区新安街道23区东联工业区五栋七层703-704室(东联商务大厦)', '703-704'),
    # 不能解析出房号的地址（返回空串）
    ('广东省深圳市南山区桃源街道峰景社区北环大道8028号方直珑樾山花园1栋负3层', ''),
    ('广东省深圳市福田区华强北街道华航社区振兴路91-13号', ''),
]


def main():
    conn = psycopg2.connect(
        host='localhost', port=5432,
        dbname='postgres', user='postgres', password='123456'
    )
    conn.autocommit = True
    cur = conn.cursor()

    # 1. 创建函数和存储过程（验证语法正确）
    cur.execute(load_sql_file())
    print('✓ 函数和存储过程创建成功\n')

    # 2. 创建临时测试表
    cur.execute("DROP TABLE IF EXISTS test_house_batch")
    cur.execute("""
        CREATE TABLE test_house_batch (
            id SERIAL PRIMARY KEY,
            address TEXT,
            house_no TEXT,
            group_tag INT
        )
    """)

    # 3. 插入测试数据
    for i, (addr, _) in enumerate(TEST_ADDRESSES):
        group = 1 if i < 5 else 2
        cur.execute(
            "INSERT INTO test_house_batch (address, house_no, group_tag) VALUES (%s, NULL, %s)",
            (addr, group)
        )
    print(f'插入 {len(TEST_ADDRESSES)} 条测试数据\n')

    expected_parsed = sum(1 for _, h in TEST_ADDRESSES if h)

    # ========== 测试 1：全量批量更新 ==========
    print('==== 测试 1：全量批量更新（p_id_col=id, batch_size=3） ====')
    cur.execute("""
        CALL batch_update_house_number(
            p_table_name  := 'test_house_batch',
            p_id_col      := 'id',
            p_address_col := 'address',
            p_house_col   := 'house_no',
            p_batch_size  := 3
        )
    """)

    # 验证结果
    cur.execute("SELECT id, address, house_no FROM test_house_batch ORDER BY id")
    rows = cur.fetchall()
    actual_parsed = 0
    all_correct = True
    for i, (rid, addr, house) in enumerate(rows):
        expected = TEST_ADDRESSES[i][1]
        actual = house or ''
        if actual == expected:
            if actual:
                actual_parsed += 1
        else:
            all_correct = False
            print(f'  ✗ id={rid}: 期望="{expected}", 实际="{actual}"')
            print(f'    地址: {addr}')

    print(f'  期望解析数: {expected_parsed}, 实际解析数: {actual_parsed}')
    if all_correct and actual_parsed == expected_parsed:
        print('  ✓ 全量批量更新正确\n')
    else:
        print('  ✗ 全量批量更新有误\n')
        sys.exit(1)

    # ========== 测试 2：幂等性（重复调用不重复更新） ==========
    print('==== 测试 2：幂等性（重复调用） ====')
    cur.execute("""
        CALL batch_update_house_number(
            p_table_name  := 'test_house_batch',
            p_id_col      := 'id',
            p_address_col := 'address',
            p_house_col   := 'house_no',
            p_batch_size  := 5
        )
    """)
    cur.execute("SELECT count(*) FROM test_house_batch WHERE house_no IS NOT NULL AND house_no <> ''")
    repeat_parsed = cur.fetchone()[0]
    if repeat_parsed == expected_parsed:
        print(f'  ✓ 幂等性验证通过（重复调用后解析数仍为 {repeat_parsed}）\n')
    else:
        print(f'  ✗ 幂等性失败：重复调用后解析数变为 {repeat_parsed}\n')
        sys.exit(1)

    # ========== 测试 3：清空后用 p_where_clause 过滤 ==========
    print('==== 测试 3：p_where_clause 过滤（只处理 group_tag=1） ====')
    cur.execute("UPDATE test_house_batch SET house_no = NULL")
    cur.execute("""
        CALL batch_update_house_number(
            p_table_name   := 'test_house_batch',
            p_id_col       := 'id',
            p_address_col  := 'address',
            p_house_col    := 'house_no',
            p_batch_size   := 10,
            p_where_clause := 'group_tag = 1'
        )
    """)
    cur.execute("SELECT count(*) FROM test_house_batch WHERE house_no IS NOT NULL AND house_no <> ''")
    filtered_parsed = cur.fetchone()[0]
    # group_tag=1 的有5条（i<5），其中能解析的看 TEST_ADDRESSES[:5]
    expected_group1 = sum(1 for i, (_, h) in enumerate(TEST_ADDRESSES) if i < 5 and h)
    if filtered_parsed == expected_group1:
        print(f'  ✓ 过滤正确（group_tag=1 解析数: {filtered_parsed}）\n')
    else:
        print(f'  ✗ 过滤失败：期望 {expected_group1}, 实际 {filtered_parsed}\n')
        sys.exit(1)

    # ========== 测试 4：参数校验 ==========
    print('==== 测试 4：参数校验 ====')

    # 4a. p_id_col 为空
    try:
        cur.execute("CALL batch_update_house_number('test_house_batch', '', 'address', 'house_no', 10)")
        print('  ✗ p_id_col 为空未抛异常')
        sys.exit(1)
    except psycopg2.Error:
        print('  ✓ p_id_col 为空正确抛异常')

    # 4b. p_id_col 不存在
    try:
        cur.execute("CALL batch_update_house_number('test_house_batch', 'nonexistent_col', 'address', 'house_no', 10)")
        print('  ✗ 不存在的列未抛异常')
        sys.exit(1)
    except psycopg2.Error:
        print('  ✓ 不存在的列正确抛异常')

    # 4c. p_id_col 非数值类型（address 是 TEXT）
    try:
        cur.execute("CALL batch_update_house_number('test_house_batch', 'address', 'address', 'house_no', 10)")
        print('  ✗ 非数值类型列未抛异常')
        sys.exit(1)
    except psycopg2.Error:
        print('  ✓ 非数值类型列正确抛异常')

    print()

    # ========== 清理 ==========
    cur.execute("DROP TABLE IF EXISTS test_house_batch")

    print('==== 所有测试通过 ====')


if __name__ == '__main__':
    main()
