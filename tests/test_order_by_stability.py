"""
ORDER BY 稳定性测试
==================

验证分页查询的 ORDER BY 子句包含 id 作为 tiebreaker，确保行顺序稳定。

背景：
    精排匹配结果人工纠正时，点击选中某行会自动刷新掉选择。
    根因之一是 get_match_results_paginated 等方法的 ORDER BY 仅按
    exact_match/partial_match 排序，未保证唯一性。当多行概率相同时，
    PostgreSQL 不保证行顺序稳定，导致 Streamlit dataframe 检测到数据
    "指纹"变化而清除 selection。

修复：
    在所有非唯一的 ORDER BY 中追加 `id ASC` 作为 tiebreaker。

参考：
    - https://discuss.streamlit.io/t/aggrid-selection-clears-after-clicking-checkbox/29955
    - Streamlit dataframe 在 data 内容变化时会清除 selection
"""

import sys
import os
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _capture_executed_sql(loader_method, **kwargs):
    """
    调用 DataLoader 的某个分页方法，捕获实际执行的所有 SQL 语句。

    注意：get_match_results_paginated 等方法内部会先调用 create_result_table
    触发 CREATE TABLE / ALTER TABLE 等 SQL，所以需要捕获所有 db.execute 调用，
    然后筛选出真正的分页/计数查询 SQL。

    Args:
        loader_method: DataLoader 实例方法
        **kwargs: 传给该方法的关键字参数

    Returns:
        list[str]: 实际执行的所有 SQL 语句列表
    """
    mock_db = MagicMock()
    mock_cursor = MagicMock()
    mock_db.execute.return_value = mock_cursor
    mock_cursor.fetchall.return_value = []
    mock_cursor.fetchone.return_value = {'count': 0}

    from database.data_loader import DataLoader
    loader = DataLoader(mock_db)

    # 调用指定方法
    method = getattr(loader, loader_method)
    method(**kwargs)

    # 捕获所有执行的 SQL
    assert mock_db.execute.called, "db.execute 未被调用"
    sqls = [call[0][0] for call in mock_db.execute.call_args_list]
    return sqls


def _find_pagination_sql(sqls):
    """从 SQL 列表中找出包含 LIMIT 的分页查询 SQL"""
    for sql in sqls:
        if 'LIMIT' in sql and 'OFFSET' in sql:
            return sql
    return None


def _find_count_sql(sqls):
    """从 SQL 列表中找出 COUNT 查询 SQL"""
    for sql in sqls:
        if 'COUNT(*)' in sql:
            return sql
    return None


def test_match_results_paginated_order_by_has_id_tiebreaker():
    """get_match_results_paginated 的 ORDER BY 应包含 id ASC 作为 tiebreaker"""
    print("=" * 60)
    print("get_match_results_paginated: ORDER BY 含 id ASC")
    print("=" * 60)

    sqls = _capture_executed_sql(
        'get_match_results_paginated',
        table_name='match_results',
        page=1,
        page_size=20,
    )
    sql = _find_pagination_sql(sqls)
    assert sql is not None, f"未找到分页查询 SQL，所有 SQL={sqls}"

    # 核心断言：ORDER BY 子句必须包含 id ASC
    assert 'ORDER BY exact_match DESC, partial_match DESC, id ASC' in sql, \
        f"ORDER BY 缺少 id ASC tiebreaker，SQL={sql}"

    print(f"  SQL: {sql.strip()}")
    print("  ORDER BY 含 id ASC tiebreaker ✓")
    print("\n[PASS] test_match_results_paginated_order_by_has_id_tiebreaker")
    return True


def test_recall_results_paginated_order_by_has_id_tiebreaker():
    """get_recall_results_paginated 的 ORDER BY 应包含 id ASC 作为 tiebreaker"""
    print("=" * 60)
    print("get_recall_results_paginated: ORDER BY 含 id ASC")
    print("=" * 60)

    sqls = _capture_executed_sql(
        'get_recall_results_paginated',
        table_name='recall_results',
        page=1,
        page_size=20,
    )
    sql = _find_pagination_sql(sqls)
    assert sql is not None, f"未找到分页查询 SQL，所有 SQL={sqls}"

    assert 'ORDER BY enterprise_id, similarity DESC, id ASC' in sql, \
        f"ORDER BY 缺少 id ASC tiebreaker，SQL={sql}"

    print(f"  SQL: {sql.strip()}")
    print("  ORDER BY 含 id ASC tiebreaker ✓")
    print("\n[PASS] test_recall_results_paginated_order_by_has_id_tiebreaker")
    return True


def test_mgeo_similarity_results_paginated_order_by_has_id_tiebreaker():
    """get_mgeo_similarity_results_paginated 的 ORDER BY 应包含 id ASC 作为 tiebreaker"""
    print("=" * 60)
    print("get_mgeo_similarity_results_paginated: ORDER BY 含 id ASC")
    print("=" * 60)

    sqls = _capture_executed_sql(
        'get_mgeo_similarity_results_paginated',
        table_name='mgeo_similarity_results',
        page=1,
        page_size=20,
    )
    sql = _find_pagination_sql(sqls)
    assert sql is not None, f"未找到分页查询 SQL，所有 SQL={sqls}"

    assert 'ORDER BY exact_match DESC, partial_match DESC, id ASC' in sql, \
        f"ORDER BY 缺少 id ASC tiebreaker，SQL={sql}"

    print(f"  SQL: {sql.strip()}")
    print("  ORDER BY 含 id ASC tiebreaker ✓")
    print("\n[PASS] test_mgeo_similarity_results_paginated_order_by_has_id_tiebreaker")
    return True


def test_match_results_paginated_with_filters_still_has_id_tiebreaker():
    """带 filters 时 ORDER BY 仍应包含 id ASC"""
    print("=" * 60)
    print("get_match_results_paginated (带 filters): ORDER BY 含 id ASC")
    print("=" * 60)

    filters = {
        'match_status': '精确匹配',
        'min_exact_match': 0.8,
        'keyword': '深圳',
    }

    sqls = _capture_executed_sql(
        'get_match_results_paginated',
        table_name='match_results',
        filters=filters,
        page=2,
        page_size=50,
    )
    sql = _find_pagination_sql(sqls)
    assert sql is not None, f"未找到分页查询 SQL，所有 SQL={sqls}"

    # 带 WHERE 子句时，ORDER BY 仍应包含 id ASC
    assert 'ORDER BY exact_match DESC, partial_match DESC, id ASC' in sql, \
        f"带 filters 时 ORDER BY 缺少 id ASC tiebreaker，SQL={sql}"
    # 验证 WHERE 子句存在
    assert 'WHERE' in sql, f"缺少 WHERE 子句，SQL={sql}"
    # 验证分页参数
    assert 'LIMIT 50' in sql, f"LIMIT 子句错误，SQL={sql}"
    assert 'OFFSET 50' in sql, f"OFFSET 子句错误（page=2, page_size=50 应 OFFSET 50），SQL={sql}"

    print(f"  SQL: {sql.strip()}")
    print("  ORDER BY 含 id ASC tiebreaker ✓")
    print("  WHERE 子句存在 ✓")
    print("  LIMIT/OFFSET 正确 ✓")
    print("\n[PASS] test_match_results_paginated_with_filters_still_has_id_tiebreaker")
    return True


def test_match_results_count_independent_of_order_by():
    """get_match_results_count 不应包含 ORDER BY（计数查询无需排序）"""
    print("=" * 60)
    print("get_match_results_count: 不应包含 ORDER BY")
    print("=" * 60)

    sqls = _capture_executed_sql(
        'get_match_results_count',
        table_name='match_results',
    )
    sql = _find_count_sql(sqls)
    assert sql is not None, f"未找到 COUNT 查询 SQL，所有 SQL={sqls}"

    assert 'ORDER BY' not in sql.upper(), \
        f"计数查询不应包含 ORDER BY，SQL={sql}"

    print(f"  SQL: {sql.strip()}")
    print("  计数查询无 ORDER BY ✓")
    print("\n[PASS] test_match_results_count_independent_of_order_by")
    return True


def run_all_tests():
    """运行全部测试"""
    tests = [
        test_match_results_paginated_order_by_has_id_tiebreaker,
        test_recall_results_paginated_order_by_has_id_tiebreaker,
        test_mgeo_similarity_results_paginated_order_by_has_id_tiebreaker,
        test_match_results_paginated_with_filters_still_has_id_tiebreaker,
        test_match_results_count_independent_of_order_by,
    ]

    passed = 0
    failed = 0
    for test in tests:
        try:
            result = test()
            if result is None or result is True:
                passed += 1
            else:
                failed += 1
                print(f"\n[FAIL] {test.__name__}")
        except Exception as e:
            failed += 1
            import traceback
            print(f"\n[FAIL] {test.__name__}: {e}")
            traceback.print_exc()

    print("\n" + "=" * 60)
    print(f"测试结果: {passed} passed, {failed} failed")
    print("=" * 60)
    return failed == 0


if __name__ == '__main__':
    success = run_all_tests()
    sys.exit(0 if success else 1)
