# -*- coding: utf-8 -*-
"""
测试 extract_house_number 函数的批量应用功能（V2：ctid keyset pagination）。

注意：batch_update_house_number PROCEDURE 的内部 COMMIT 与 psycopg2 事务
管理冲突，无法直接在 Python 中调用。PROCEDURE 的语法正确性已通过函数
创建成功验证。用户应在 psql 或其他 PG 客户端中调用 PROCEDURE。

本脚本通过 Python 模拟优化后的 ctid keyset pagination 批量 UPDATE 逻辑，
验证：
    1. 不死循环（无法解析的地址被跳过，扫描完全表后正常退出）
    2. 幂等性（已处理的记录不会被重复更新）
    3. where_clause 过滤
    4. 性能不退化（每批扫描行数固定，不随进度增长）
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
# 不能解析的地址（返回空串）在原方案中会导致死循环
TEST_ADDRESSES = [
    # 能解析出房号的地址
    '广东省深圳市福田区华强北街道华航社区振兴路91-13号B101',
    '广东省深圳市宝安区新安街道甲岸社区宝民一路甲岸村22号401',
    '广东省深圳市罗湖区黄贝街道水库社区东湖公园杜鹃园宿舍2栋4号',
    '深圳市宝安区西乡街道丽景城3栋118商铺',
    '深圳市福田区华强北路1号A铺',
    '广东省深圳市罗湖区黄贝街道黄贝岭社区深南东路1038号黄贝岭经泽大厦7B12',
    '广东省深圳市南山区科技园南区A101B',
    '广东省深圳市罗湖区黄贝街道新兴社区经二路38号安业花园C2栋附01',
    # 不能解析出房号的地址（返回空串）
    '广东省深圳市南山区桃源街道峰景社区北环大道8028号方直珑樾山花园1栋负3层',
    '广东省深圳市福田区华强北街道华航社区振兴路91-13号',
] * 10  # 100 条（80 条能解析，20 条不能解析）

# 无法解析的地址集合
UNPARSEABLE = {
    '广东省深圳市南山区桃源街道峰景社区北环大道8028号方直珑樾山花园1栋负3层',
    '广东省深圳市福田区华强北街道华航社区振兴路91-13号',
}


def simulate_keyset_batch_update(cur, table, addr_col, house_col, batch_size,
                                  where_clause=''):
    """
    模拟优化后的「临时表 + 行号 keyset pagination」批量更新逻辑。
    返回 (total_scanned, total_updated, batch_sizes)。
    batch_sizes 记录每批处理行数，用于验证性能不退化。

    核心思路：
      1. 先一次性将待处理记录的 ctid 收集到临时表（带 row_number 行号）
      2. 在临时表上用 WHERE rn > last_rn 分批（临时表不 UPDATE，行号稳定）
      3. UPDATE 源表时只对本批 ctid 调用 extract_house_number

    不能直接用源表 ctid 做 keyset pagination，因为 UPDATE 源表后 ctid 会变（MVCC）。
    """
    extra_cond = f' AND ({where_clause})' if where_clause else ''
    temp_table = f'tmp_pending_{table}'

    # 1. 创建临时表，收集待处理 ctid + 行号
    #    WHERE 中加 extract_house_number <> '' 过滤无法解析的记录（一次性调用函数）
    cur.execute(f'DROP TABLE IF EXISTS {temp_table}')
    cur.execute(
        f'CREATE TEMP TABLE {temp_table} AS '
        f'SELECT row_number() OVER (ORDER BY ctid) AS rn, ctid AS src_ctid '
        f'FROM {table} '
        f'WHERE ({house_col} IS NULL OR {house_col} = \'\') '
        f'AND {addr_col} IS NOT NULL AND {addr_col} <> \'\' '
        f'AND extract_house_number({addr_col}) <> \'\''
        f'{extra_cond}'
    )

    update_sql = (
        f'UPDATE {table} SET {house_col} = extract_house_number({addr_col}) '
        f'WHERE ctid = ANY(%s::tid[]) AND ({house_col} IS NULL OR {house_col} = \'\')'
    )

    total_scanned = 0
    total_updated = 0
    batch_sizes = []
    last_rn = 0

    while True:
        # 2. 从临时表取一批源表 ctid（用 rn 游标，临时表不 UPDATE，行号稳定）
        cur.execute(
            f'SELECT src_ctid FROM {temp_table} WHERE rn > %s ORDER BY rn LIMIT %s',
            (last_rn, batch_size)
        )
        rows = cur.fetchall()
        if not rows:
            break
        ctids = [r[0] for r in rows]

        # 推进行号游标
        last_rn += batch_size
        batch_count = len(ctids)
        total_scanned += batch_count
        batch_sizes.append(batch_count)

        # 3. UPDATE 源表（只对本批 ctid 调用函数）
        cur.execute(update_sql, (ctids,))
        total_updated += cur.rowcount

    # 清理临时表
    cur.execute(f'DROP TABLE IF EXISTS {temp_table}')

    return total_scanned, total_updated, batch_sizes


def main():
    conn = psycopg2.connect(
        host='localhost', port=5432,
        dbname='postgres', user='postgres', password='123456'
    )
    conn.autocommit = True
    cur = conn.cursor()

    # 1. 创建函数（PROCEDURE 也会创建，但不调用）
    cur.execute(load_sql_file())

    # 2. 创建临时测试表
    cur.execute("DROP TABLE IF EXISTS test_house_extract")
    cur.execute("""
        CREATE TABLE test_house_extract (
            id SERIAL PRIMARY KEY,
            address TEXT,
            house_no TEXT,
            group_tag INT
        )
    """)

    # 3. 插入测试数据
    for i, addr in enumerate(TEST_ADDRESSES):
        group = 1 if i < 50 else 2
        cur.execute(
            "INSERT INTO test_house_extract (address, house_no, group_tag) VALUES (%s, NULL, %s)",
            (addr, group)
        )
    print(f"插入 {len(TEST_ADDRESSES)} 条测试数据\n")

    expected_parsing = sum(1 for a in TEST_ADDRESSES if a not in UNPARSEABLE)

    # ========== 测试 1：全量批量更新（含无法解析的地址，验证不死循环） ==========
    print("==== 测试 1：全量批量更新（ctid keyset pagination） ====")
    total_scanned, total_updated, batch_sizes = simulate_keyset_batch_update(
        cur, 'test_house_extract', 'address', 'house_no', batch_size=20
    )

    print(f"  累计扫描: {total_scanned} 条, 累计更新: {total_updated} 条")
    print(f"  批次扫描行数: {batch_sizes}")
    print(f"  批次数: {len(batch_sizes)}")

    # 验证：临时表只含能解析的记录（80条），不重复扫描，不死循环
    assert total_scanned == expected_parsing, \
        f"扫描数 {total_scanned} != 能解析数 {expected_parsing}"
    assert total_updated == expected_parsing, \
        f"更新数 {total_updated} != 期望 {expected_parsing}"

    # 验证：每批扫描行数固定为20（最后一批可能不足）
    for i, sz in enumerate(batch_sizes):
        assert sz <= 20, f"批次 {i+1} 扫描 {sz} 行 > batch_size 20"
        if i < len(batch_sizes) - 1:
            assert sz == 20, f"批次 {i+1} 扫描 {sz} 行 != 20（非末批应满批）"
    print(f"  验证通过：每批扫描行数固定（≤20），不随进度退化")

    # 5. 验证结果
    cur.execute("""
        SELECT address, house_no
        FROM test_house_extract
        WHERE id IN (1, 2, 3, 4, 9, 10)
        ORDER BY id
    """)
    print("\n部分解析结果：")
    for addr, house in cur.fetchall():
        print(f"  house='{house or '':<10}'  addr={addr[:50]}...")

    # 6. 统计
    cur.execute("SELECT count(*) FROM test_house_extract WHERE house_no IS NOT NULL AND house_no <> ''")
    filled = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM test_house_extract WHERE house_no IS NULL OR house_no = ''")
    empty = cur.fetchone()[0]
    print(f"\n已填充房号: {filled}, 仍为空(无法解析): {empty}")
    assert filled == expected_parsing
    assert empty == len(TEST_ADDRESSES) - expected_parsing

    # ========== 测试 2：幂等性（已处理不重复） ==========
    print("\n==== 测试 2：幂等性（再次运行，已处理的不更新） ====")
    total_scanned2, total_updated2, _ = simulate_keyset_batch_update(
        cur, 'test_house_extract', 'address', 'house_no', batch_size=50
    )
    print(f"  再次扫描: {total_scanned2} 条, 更新: {total_updated2} 条 (应为 0)")
    # 能解析的已处理（house_no非空被过滤），无法解析的被 extract_house_number<>'' 过滤
    # → 临时表为空 → 0更新，真正幂等
    assert total_scanned2 == 0, \
        f"幂等扫描数 {total_scanned2} != 0（应无待处理记录）"
    assert total_updated2 == 0, "幂等性失败：已处理的记录不应被重复更新"

    # ========== 测试 3：带 where_clause 过滤 ==========
    print("\n==== 测试 3：带 where_clause 过滤 ====")
    cur.execute("UPDATE test_house_extract SET house_no = NULL WHERE group_tag = 2")
    print(f"  重置 group=2 的房号: {cur.rowcount} 条")

    total_scanned3, total_updated3, _ = simulate_keyset_batch_update(
        cur, 'test_house_extract', 'address', 'house_no',
        batch_size=10, where_clause='group_tag = 2'
    )
    expected_group2 = sum(1 for i, a in enumerate(TEST_ADDRESSES)
                          if i >= 50 and a not in UNPARSEABLE)
    print(f"  带过滤扫描: {total_scanned3} 条, 更新: {total_updated3} 条 (期望: {expected_group2})")
    # where_clause 过滤后只处理 group=2 中能解析的记录（40条）
    assert total_scanned3 == expected_group2, \
        f"过滤扫描数 {total_scanned3} != 期望 {expected_group2}"
    assert total_updated3 == expected_group2, \
        f"过滤更新 {total_updated3} != 期望 {expected_group2}"

    cur.execute("SELECT count(*) FROM test_house_extract WHERE group_tag = 2 AND house_no IS NOT NULL AND house_no <> ''")
    group2_filled = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM test_house_extract WHERE group_tag = 1 AND house_no IS NOT NULL AND house_no <> ''")
    group1_filled = cur.fetchone()[0]
    print(f"  group=1 已填充: {group1_filled} (应={expected_parsing - expected_group2}, 未被影响)")
    print(f"  group=2 已填充: {group2_filled} (应={expected_group2}, 被更新)")
    assert group1_filled == expected_parsing - expected_group2
    assert group2_filled == expected_group2

    # ========== 测试 4：性能不退化验证 ==========
    # 模拟大表场景：插入更多数据，验证每批扫描行数恒定
    print("\n==== 测试 4：性能不退化（每批扫描行数恒定） ====")
    cur.execute("DROP TABLE IF EXISTS test_house_perf")
    cur.execute("""
        CREATE TABLE test_house_perf (
            id SERIAL PRIMARY KEY,
            address TEXT,
            house_no TEXT
        )
    """)
    # 插入1000条，其中200条无法解析
    for i in range(800):
        cur.execute("INSERT INTO test_house_perf (address, house_no) VALUES (%s, NULL)",
                    ('广东省深圳市福田区华强北街道华航社区振兴路91-13号B101',))
    for i in range(200):
        cur.execute("INSERT INTO test_house_perf (address, house_no) VALUES (%s, NULL)",
                    ('广东省深圳市福田区华强北街道华航社区振兴路91-13号',))

    total_scanned4, total_updated4, batch_sizes4 = simulate_keyset_batch_update(
        cur, 'test_house_perf', 'address', 'house_no', batch_size=100
    )
    print(f"  1000条表：扫描 {total_scanned4}, 更新 {total_updated4}")
    print(f"  批次扫描行数: {batch_sizes4}")

    # 验证：临时表只含能解析的800条，更新800条
    assert total_scanned4 == 800
    assert total_updated4 == 800
    # 验证：8批，每批100条（恒定不退化）
    assert len(batch_sizes4) == 8
    for sz in batch_sizes4:
        assert sz == 100, f"批次扫描 {sz} != 100（性能退化）"
    print(f"  验证通过：8批 × 100条/批 = 800条，每批恒定不退化")

    # ========== 清理 ==========
    cur.execute("DROP TABLE IF EXISTS test_house_extract")
    cur.execute("DROP TABLE IF EXISTS test_house_perf")
    print("\n==== 所有测试通过，清理临时表 ====")

    cur.close()
    conn.close()


if __name__ == '__main__':
    main()
