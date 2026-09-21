"""
数据加载 AS 别名修复测试
========================

验证当 room_col 与 address_col/id_col 相同、或 name_col 与 id_col 相同时，
DataLoader 的4个加载方法不会因 RealDictCursor 合并重复列名而报
"Length mismatch: Expected axis has N elements, new values have M elements"。

根因：DBConnection 使用 RealDictCursor，SELECT 中重复列名会被合并为同一个
dict key，导致 pd.DataFrame 列数 < 预期，赋列名时报错。
修复：SELECT 列加 AS 别名确保 key 唯一。
"""

import sys
import os
from unittest.mock import MagicMock
from collections import OrderedDict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class FakeRealDictRow(OrderedDict):
    """模拟 psycopg2 RealDictRow（dict 子类），重复 key 后者覆盖前者"""
    pass


def _make_rows(columns, rows_data):
    """
    构造模拟 RealDictCursor.fetchall() 返回的行列表。

    Args:
        columns: SELECT 输出列名列表（已考虑 AS 别名后的名称）
        rows_data: 每行的原始值列表

    Returns:
        list[FakeRealDictRow]
    """
    result = []
    for values in rows_data:
        row = FakeRealDictRow()
        for col, val in zip(columns, values):
            row[col] = val  # 重复 key 会覆盖，模拟 RealDictCursor 行为
        result.append(row)
    return result


# ---------------------------------------------------------------------------
# 标准地址：room_col == address_col（用户无独立房号字段，复用地址字段）
# ---------------------------------------------------------------------------

def test_load_standard_addresses_room_equals_address():
    """room_col == address_col 时 load_standard_addresses 不报 Length mismatch"""
    print("=" * 60)
    print("room_col == address_col: load_standard_addresses")
    print("=" * 60)

    from database.data_loader import DataLoader

    mock_db = MagicMock()
    mock_cursor = MagicMock()
    mock_db.execute.return_value = mock_cursor

    data = _make_rows(
        columns=['id', 'address', 'room_no'],  # AS 别名确保唯一
        rows_data=[
            ['1', '深圳市南山区', '深圳市南山区'],
            ['2', '北京市海淀区', '北京市海淀区'],
            ['3', '上海市浦东新区', '上海市浦东新区'],
        ]
    )
    mock_cursor.fetchall.side_effect = [data, []]  # 第二次返回空，终止迭代

    loader = DataLoader(mock_db)
    batches = list(loader.load_standard_addresses(
        table_name='std_addr', id_col='地址编码',
        address_col='标准地址', room_col='标准地址',  # room_col == address_col
        batch_size=10
    ))

    assert len(batches) == 1, f"Expected 1 batch, got {len(batches)}"
    df = batches[0]
    assert list(df.columns) == ['id', 'address', 'room_no'], \
        f"columns={list(df.columns)}"
    assert len(df) == 3
    assert df.iloc[0]['room_no'] == '深圳市南山区'

    print("  3 columns correctly assigned ✓")
    print("\n[PASS] test_load_standard_addresses_room_equals_address")
    return True


def test_load_standard_addresses_room_equals_id():
    """room_col == id_col 时 load_standard_addresses 不报 Length mismatch"""
    print("=" * 60)
    print("room_col == id_col: load_standard_addresses")
    print("=" * 60)

    from database.data_loader import DataLoader

    mock_db = MagicMock()
    mock_cursor = MagicMock()
    mock_db.execute.return_value = mock_cursor

    data = _make_rows(
        columns=['id', 'address', 'room_no'],
        rows_data=[
            ['1001', '深圳市南山区科技路1号', '1001'],
            ['1002', '北京市海淀区中关村大街2号', '1002'],
        ]
    )
    mock_cursor.fetchall.side_effect = [data, []]

    loader = DataLoader(mock_db)
    batches = list(loader.load_standard_addresses(
        table_name='std_addr', id_col='地址编码',
        address_col='标准地址', room_col='地址编码',  # room_col == id_col
        batch_size=10
    ))

    assert len(batches) == 1
    df = batches[0]
    assert list(df.columns) == ['id', 'address', 'room_no']
    assert len(df) == 2

    print("  3 columns correctly assigned ✓")
    print("\n[PASS] test_load_standard_addresses_room_equals_id")
    return True


def test_load_standard_addresses_no_room_col():
    """不指定 room_col 时 load_standard_addresses 正常返回2列"""
    print("=" * 60)
    print("room_col=None: load_standard_addresses")
    print("=" * 60)

    from database.data_loader import DataLoader

    mock_db = MagicMock()
    mock_cursor = MagicMock()
    mock_db.execute.return_value = mock_cursor

    data = _make_rows(
        columns=['id', 'address'],
        rows_data=[
            ['1', '深圳市南山区'],
            ['2', '北京市海淀区'],
        ]
    )
    mock_cursor.fetchall.side_effect = [data, []]

    loader = DataLoader(mock_db)
    batches = list(loader.load_standard_addresses(
        table_name='std_addr', id_col='地址编码',
        address_col='标准地址', room_col=None,
        batch_size=10
    ))

    assert len(batches) == 1
    df = batches[0]
    assert list(df.columns) == ['id', 'address']
    assert len(df) == 2

    print("  2 columns correctly assigned ✓")
    print("\n[PASS] test_load_standard_addresses_no_room_col")
    return True


# ---------------------------------------------------------------------------
# 增量标准地址：同样场景
# ---------------------------------------------------------------------------

def test_load_unvectorized_standard_addresses_room_equals_address():
    """room_col == address_col 时 load_unvectorized_standard_addresses 不报错"""
    print("=" * 60)
    print("room_col == address_col: load_unvectorized_standard_addresses")
    print("=" * 60)

    from database.data_loader import DataLoader

    mock_db = MagicMock()
    mock_cursor = MagicMock()
    mock_db.execute.return_value = mock_cursor

    data = _make_rows(
        columns=['id', 'address', 'room_no'],
        rows_data=[
            ['1', '深圳市南山区', '深圳市南山区'],
            ['2', '北京市海淀区', '北京市海淀区'],
        ]
    )
    mock_cursor.fetchall.side_effect = [data, []]

    loader = DataLoader(mock_db)
    batches = list(loader.load_unvectorized_standard_addresses(
        table_name='std_addr', id_col='地址编码',
        address_col='标准地址', room_col='标准地址',
        vector_table='std_vectors', batch_size=10
    ))

    assert len(batches) == 1
    df = batches[0]
    assert list(df.columns) == ['id', 'address', 'room_no']
    assert len(df) == 2

    print("  3 columns correctly assigned ✓")
    print("\n[PASS] test_load_unvectorized_standard_addresses_room_equals_address")
    return True


# ---------------------------------------------------------------------------
# 企业表：name_col == id_col（用户未指定企业名，复用 id）
# ---------------------------------------------------------------------------

def test_load_enterprise_data_name_equals_id():
    """name_col == id_col 时 load_enterprise_data 不中断"""
    print("=" * 60)
    print("name_col == id_col: load_enterprise_data")
    print("=" * 60)

    from database.data_loader import DataLoader

    mock_db = MagicMock()
    mock_cursor = MagicMock()
    mock_db.execute.return_value = mock_cursor

    data = _make_rows(
        columns=['id', 'name', 'address'],
        rows_data=[
            ['1', '1', '深圳市南山区'],
            ['2', '2', '北京市海淀区'],
        ]
    )
    mock_cursor.fetchall.side_effect = [data, []]

    loader = DataLoader(mock_db)
    batches = list(loader.load_enterprise_data(
        table_name='enterprise', id_col='企业ID',
        name_col='企业ID',  # name_col == id_col
        address_col='企业地址',
        batch_size=10
    ))

    assert len(batches) == 1, f"Expected 1 batch, got {len(batches)}"
    df = batches[0]
    assert list(df.columns) == ['id', 'name', 'address'], \
        f"columns={list(df.columns)}"
    assert len(df) == 2

    print("  3 columns correctly assigned ✓")
    print("\n[PASS] test_load_enterprise_data_name_equals_id")
    return True


def test_load_unvectorized_enterprise_data_name_equals_id():
    """name_col == id_col 时 load_unvectorized_enterprise_data 不中断"""
    print("=" * 60)
    print("name_col == id_col: load_unvectorized_enterprise_data")
    print("=" * 60)

    from database.data_loader import DataLoader

    mock_db = MagicMock()
    mock_cursor = MagicMock()
    mock_db.execute.return_value = mock_cursor

    data = _make_rows(
        columns=['id', 'name', 'address'],
        rows_data=[
            ['1', '1', '深圳市南山区'],
        ]
    )
    mock_cursor.fetchall.side_effect = [data, []]

    loader = DataLoader(mock_db)
    batches = list(loader.load_unvectorized_enterprise_data(
        table_name='enterprise', id_col='企业ID',
        name_col='企业ID',
        address_col='企业地址',
        vector_table='ent_vectors',
        batch_size=10
    ))

    assert len(batches) == 1
    df = batches[0]
    assert list(df.columns) == ['id', 'name', 'address']
    assert len(df) == 1

    print("  3 columns correctly assigned ✓")
    print("\n[PASS] test_load_unvectorized_enterprise_data_name_equals_id")
    return True


# ---------------------------------------------------------------------------
# 静态验证：SQL 使用 AS 别名
# ---------------------------------------------------------------------------

def test_sql_uses_as_alias():
    """静态验证所有加载方法 SQL 使用 AS 别名，last_id 用别名取值"""
    print("=" * 60)
    print("Static: SQL uses AS alias, last_id uses 'id'")
    print("=" * 60)

    dl_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'database', 'data_loader.py'
    )
    with open(dl_path, 'r', encoding='utf-8') as f:
        source = f.read()

    # 标准地址3列（无s.前缀 + 有s.前缀）
    assert 'AS id, {quote_identifier(address_col)} AS address, {quote_identifier(room_col)} AS room_no' in source
    assert 's.{quote_identifier(id_col)} AS id, s.{quote_identifier(address_col)} AS address, s.{quote_identifier(room_col)} AS room_no' in source

    # 标准地址2列
    assert '{quote_identifier(id_col)} AS id, {quote_identifier(address_col)} AS address\n' in source
    assert 's.{quote_identifier(id_col)} AS id, s.{quote_identifier(address_col)} AS address\n' in source

    # 企业表3列
    assert '{quote_identifier(id_col)} AS id, {quote_identifier(name_col)} AS name, {quote_identifier(address_col)} AS address' in source
    assert 's.{quote_identifier(id_col)} AS id, s.{quote_identifier(name_col)} AS name, s.{quote_identifier(address_col)} AS address' in source

    # last_id 使用别名
    assert "last_id = rows[-1]['id']" in source
    assert "last_id = rows[-1][id_col]" not in source

    print("  all SQL SELECTs use AS alias ✓")
    print("  last_id uses 'id' alias ✓")
    print("\n[PASS] test_sql_uses_as_alias")
    return True


if __name__ == '__main__':
    results = {}
    tests = [
        ('load_std_room_equals_address', test_load_standard_addresses_room_equals_address),
        ('load_std_room_equals_id', test_load_standard_addresses_room_equals_id),
        ('load_std_no_room', test_load_standard_addresses_no_room_col),
        ('load_unvec_std_room_equals_address', test_load_unvectorized_standard_addresses_room_equals_address),
        ('load_ent_name_equals_id', test_load_enterprise_data_name_equals_id),
        ('load_unvec_ent_name_equals_id', test_load_unvectorized_enterprise_data_name_equals_id),
        ('sql_uses_as_alias', test_sql_uses_as_alias),
    ]

    for name, test_fn in tests:
        try:
            passed = test_fn()
            results[name] = 'PASS' if passed else 'FAIL'
        except Exception as e:
            results[name] = f'ERROR: {e}'
            import traceback
            traceback.print_exc()

    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    for name, result in results.items():
        status = '✅' if result == 'PASS' else '❌'
        print(f"  {status} {name}: {result}")

    all_passed = all(r == 'PASS' for r in results.values())
    print(f"\n{'ALL TESTS PASSED' if all_passed else 'SOME TESTS FAILED'}")
    sys.exit(0 if all_passed else 1)
