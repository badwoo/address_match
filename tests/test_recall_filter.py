"""
粗召回数据筛选功能测试模块
============================

测试粗召回数据关键词搜索和相似度范围检索功能，包括：
    1. 筛选条件构建（关键词、相似度范围）
    2. 筛选后的总数查询
    3. 筛选后的分页查询
    4. 边界情况处理
"""

import sys
sys.path.insert(0, r'd:\pythonProject\address_match')

from database.data_loader import DataLoader
from config import Config
from unittest.mock import MagicMock
import pandas as pd


def test_build_recall_filter_keyword():
    """测试关键词搜索筛选条件构建"""
    mock_db = MagicMock()
    loader = DataLoader(mock_db)

    conditions, params = loader._build_recall_filter_conditions({'keyword': '深圳'})

    assert len(conditions) == 1, f"Expected 1 condition, got {len(conditions)}"
    assert 'LIKE' in conditions[0], "Keyword condition should use LIKE"
    assert len(params) == 3, f"Expected 3 params, got {len(params)}"
    assert all('%深圳%' in str(p) for p in params), "All keyword params should contain %深圳%"

    print('build_recall_filter keyword: PASSED')


def test_build_recall_filter_min_similarity():
    """测试最小相似度筛选条件构建"""
    mock_db = MagicMock()
    loader = DataLoader(mock_db)

    conditions, params = loader._build_recall_filter_conditions({'min_similarity': 0.5})

    assert len(conditions) == 1, f"Expected 1 condition, got {len(conditions)}"
    assert 'similarity >= %s' in conditions[0], "Should have similarity >= condition"
    assert params[0] == 0.5, f"Expected 0.5, got {params[0]}"

    print('build_recall_filter min_similarity: PASSED')


def test_build_recall_filter_max_similarity():
    """测试最大相似度筛选条件构建"""
    mock_db = MagicMock()
    loader = DataLoader(mock_db)

    conditions, params = loader._build_recall_filter_conditions({'max_similarity': 0.8})

    assert len(conditions) == 1, f"Expected 1 condition, got {len(conditions)}"
    assert 'similarity <= %s' in conditions[0], "Should have similarity <= condition"
    assert params[0] == 0.8, f"Expected 0.8, got {params[0]}"

    print('build_recall_filter max_similarity: PASSED')


def test_build_recall_filter_similarity_range():
    """测试相似度范围筛选条件构建"""
    mock_db = MagicMock()
    loader = DataLoader(mock_db)

    conditions, params = loader._build_recall_filter_conditions({
        'min_similarity': 0.5,
        'max_similarity': 0.9
    })

    assert len(conditions) == 2, f"Expected 2 conditions, got {len(conditions)}"
    assert 0.5 in params, "min_similarity should be in params"
    assert 0.9 in params, "max_similarity should be in params"

    print('build_recall_filter similarity range: PASSED')


def test_build_recall_filter_combined():
    """测试关键词+相似度组合筛选条件构建"""
    mock_db = MagicMock()
    loader = DataLoader(mock_db)

    conditions, params = loader._build_recall_filter_conditions({
        'keyword': '广州',
        'min_similarity': 0.6,
        'max_similarity': 0.95
    })

    assert len(conditions) == 3, f"Expected 3 conditions, got {len(conditions)}"
    assert len(params) == 5, f"Expected 5 params (3 keyword + 2 similarity), got {len(params)}"

    print('build_recall_filter combined: PASSED')


def test_build_recall_filter_empty():
    """测试空筛选条件"""
    mock_db = MagicMock()
    loader = DataLoader(mock_db)

    conditions, params = loader._build_recall_filter_conditions({})

    assert len(conditions) == 0, "Empty filters should produce no conditions"
    assert len(params) == 0, "Empty filters should produce no params"

    print('build_recall_filter empty: PASSED')


def test_build_recall_filter_min_similarity_zero():
    """测试最小相似度为0时不生成条件"""
    mock_db = MagicMock()
    loader = DataLoader(mock_db)

    conditions, params = loader._build_recall_filter_conditions({'min_similarity': 0})

    assert len(conditions) == 0, "min_similarity=0 should not produce condition"

    print('build_recall_filter min_similarity zero: PASSED')


def test_build_recall_filter_max_similarity_one():
    """测试最大相似度为1时不生成条件"""
    mock_db = MagicMock()
    loader = DataLoader(mock_db)

    conditions, params = loader._build_recall_filter_conditions({'max_similarity': 1.0})

    assert len(conditions) == 0, "max_similarity=1.0 should not produce condition"

    print('build_recall_filter max_similarity one: PASSED')


def test_get_recall_results_count_no_filter():
    """测试无筛选条件时的总数查询"""
    mock_db = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = {'count': 1000}
    mock_db.execute.return_value = mock_cursor

    loader = DataLoader(mock_db)
    count = loader.get_recall_results_count()

    assert count == 1000, f"Expected 1000, got {count}"

    execute_call = str(mock_db.execute.call_args_list[0])
    assert 'COUNT' in execute_call, "Should execute COUNT query"
    assert 'WHERE' not in execute_call, "Should not have WHERE without filters"

    print('get_recall_results_count no filter: PASSED')


def test_get_recall_results_count_with_filter():
    """测试带筛选条件时的总数查询"""
    mock_db = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = {'count': 50}
    mock_db.execute.return_value = mock_cursor

    loader = DataLoader(mock_db)
    count = loader.get_recall_results_count(filters={'keyword': '深圳', 'min_similarity': 0.5})

    assert count == 50, f"Expected 50, got {count}"

    execute_call = str(mock_db.execute.call_args_list[0])
    assert 'WHERE' in execute_call, "Should have WHERE with filters"

    print('get_recall_results_count with filter: PASSED')


def test_get_recall_results_count_error():
    """测试总数查询出错时返回0"""
    mock_db = MagicMock()
    mock_db.execute.return_value = None

    loader = DataLoader(mock_db)
    count = loader.get_recall_results_count()

    assert count == 0, "Should return 0 on error"

    print('get_recall_results_count error: PASSED')


def test_get_recall_results_paginated_no_filter():
    """测试无筛选条件时的分页查询"""
    mock_db = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = [
        {'id': 1, 'enterprise_id': 'E001', 'similarity': 0.95},
        {'id': 2, 'enterprise_id': 'E002', 'similarity': 0.85},
    ]
    mock_db.execute.return_value = mock_cursor

    loader = DataLoader(mock_db)
    result = loader.get_recall_results_paginated(page=1, page_size=20)

    assert not result.empty, "Result should not be empty"
    assert len(result) == 2, f"Expected 2 rows, got {len(result)}"

    execute_call = str(mock_db.execute.call_args_list[0])
    assert 'ORDER BY' in execute_call, "Should have ORDER BY"
    assert 'LIMIT' in execute_call, "Should have LIMIT"

    print('get_recall_results_paginated no filter: PASSED')


def test_get_recall_results_paginated_with_filter():
    """测试带筛选条件时的分页查询"""
    mock_db = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = [
        {'id': 1, 'enterprise_id': 'E001', 'similarity': 0.95},
    ]
    mock_db.execute.return_value = mock_cursor

    loader = DataLoader(mock_db)
    result = loader.get_recall_results_paginated(
        filters={'keyword': '深圳', 'min_similarity': 0.5, 'max_similarity': 0.9},
        page=1,
        page_size=20
    )

    assert not result.empty, "Result should not be empty"

    execute_call = str(mock_db.execute.call_args_list[0])
    assert 'WHERE' in execute_call, "Should have WHERE with filters"

    print('get_recall_results_paginated with filter: PASSED')


def test_get_recall_results_paginated_error():
    """测试分页查询出错时返回空DataFrame"""
    mock_db = MagicMock()
    mock_db.execute.return_value = None

    loader = DataLoader(mock_db)
    result = loader.get_recall_results_paginated(page=1, page_size=20)

    assert result.empty, "Should return empty DataFrame on error"

    print('get_recall_results_paginated error: PASSED')


def test_get_recall_results_paginated_page_offset():
    """测试分页偏移量计算"""
    mock_db = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = []
    mock_db.execute.return_value = mock_cursor

    loader = DataLoader(mock_db)
    loader.get_recall_results_paginated(page=3, page_size=20)

    execute_call = str(mock_db.execute.call_args_list[0])
    assert 'OFFSET 40' in execute_call, f"Page 3 with size 20 should have OFFSET 40"

    print('get_recall_results_paginated page offset: PASSED')


if __name__ == '__main__':
    test_build_recall_filter_keyword()
    test_build_recall_filter_min_similarity()
    test_build_recall_filter_max_similarity()
    test_build_recall_filter_similarity_range()
    test_build_recall_filter_combined()
    test_build_recall_filter_empty()
    test_build_recall_filter_min_similarity_zero()
    test_build_recall_filter_max_similarity_one()
    test_get_recall_results_count_no_filter()
    test_get_recall_results_count_with_filter()
    test_get_recall_results_count_error()
    test_get_recall_results_paginated_no_filter()
    test_get_recall_results_paginated_with_filter()
    test_get_recall_results_paginated_error()
    test_get_recall_results_paginated_page_offset()
    print('\n===== ALL RECALL FILTER TESTS PASSED =====')
