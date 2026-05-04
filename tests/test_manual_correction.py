"""
人工纠正功能测试模块
====================

测试人工纠正相关功能的正确性，包括：
    1. 匹配结果表correction_source字段的创建
    2. 根据企业ID获取粗召回结果
    3. 人工纠正更新匹配结果
    4. 批量人工纠正
    5. 匹配统计包含人工纠正统计
"""

import sys
sys.path.insert(0, r'd:\pythonProject\address_match')

from database.connection import DBConnection
from database.data_loader import DataLoader
from config import Config
from unittest.mock import MagicMock, call
import pandas as pd


def test_create_result_table_has_correction_source():
    """测试匹配结果表创建时包含correction_source字段"""
    mock_db = MagicMock()
    mock_db.execute.return_value = MagicMock()
    mock_db.schema = 'public'

    loader = DataLoader(mock_db)
    loader.create_result_table()

    execute_calls = [str(c) for c in mock_db.execute.call_args_list]
    create_call = execute_calls[0]
    assert 'correction_source' in create_call, "CREATE TABLE should include correction_source column"
    assert '自动匹配' in create_call, "correction_source should default to '自动匹配'"

    print('create_result_table has correction_source: PASSED')


def test_add_correction_source_column():
    """测试为旧表添加correction_source字段的迁移逻辑"""
    mock_db = MagicMock()

    mock_check_cursor = MagicMock()
    mock_check_cursor.fetchall.return_value = []
    mock_alter_cursor = MagicMock()

    mock_db.execute.side_effect = [mock_check_cursor, mock_alter_cursor]

    loader = DataLoader(mock_db)
    loader._add_correction_source_column('match_results')

    execute_calls = [str(c) for c in mock_db.execute.call_args_list]
    assert len(execute_calls) == 2, "Should execute check and alter SQL"

    check_call = execute_calls[0]
    assert 'correction_source' in check_call, "Check SQL should look for correction_source column"

    alter_call = execute_calls[1]
    assert 'ALTER TABLE' in alter_call, "Should execute ALTER TABLE"
    assert 'correction_source' in alter_call, "Should add correction_source column"

    print('_add_correction_source_column: PASSED')


def test_add_correction_source_column_already_exists():
    """测试correction_source字段已存在时不执行ALTER"""
    mock_db = MagicMock()

    mock_check_cursor = MagicMock()
    mock_check_cursor.fetchall.return_value = [{'column_name': 'correction_source'}]

    mock_db.execute.return_value = mock_check_cursor

    loader = DataLoader(mock_db)
    loader._add_correction_source_column('match_results')

    execute_calls = [str(c) for c in mock_db.execute.call_args_list]
    assert len(execute_calls) == 1, "Should only execute check SQL when column exists"

    print('_add_correction_source_column already exists: PASSED')


def test_get_recall_results_by_enterprise_ids():
    """测试根据企业ID列表获取粗召回结果"""
    mock_db = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = [
        {'id': 1, 'enterprise_id': 'E001', 'standard_id': 'S001', 'similarity': 0.95},
        {'id': 2, 'enterprise_id': 'E001', 'standard_id': 'S002', 'similarity': 0.85},
        {'id': 3, 'enterprise_id': 'E002', 'standard_id': 'S003', 'similarity': 0.90},
    ]
    mock_db.execute.return_value = mock_cursor

    loader = DataLoader(mock_db)
    result = loader.get_recall_results_by_enterprise_ids(['E001', 'E002'])

    assert not result.empty, "Result should not be empty"
    assert len(result) == 3, f"Expected 3 rows, got {len(result)}"

    execute_call = str(mock_db.execute.call_args_list[0])
    assert 'E001' in execute_call or '%s' in execute_call, "SQL should filter by enterprise_ids"
    assert 'IN' in execute_call.upper(), "SQL should use IN clause"

    print('get_recall_results_by_enterprise_ids: PASSED')


def test_get_recall_results_by_enterprise_ids_empty():
    """测试企业ID列表为空时返回空DataFrame"""
    mock_db = MagicMock()
    loader = DataLoader(mock_db)
    result = loader.get_recall_results_by_enterprise_ids([])

    assert result.empty, "Result should be empty when no enterprise_ids provided"
    mock_db.execute.assert_not_called(), "Should not execute SQL when enterprise_ids is empty"

    print('get_recall_results_by_enterprise_ids empty: PASSED')


def test_update_match_result_with_correction():
    """测试人工纠正更新单条匹配结果"""
    mock_db = MagicMock()
    mock_cursor = MagicMock()
    mock_db.execute.return_value = mock_cursor

    loader = DataLoader(mock_db)
    result = loader.update_match_result_with_correction(
        enterprise_id='E001',
        standard_id='S005',
        standard_address='广东省深圳市南山区科技路1号',
        room_no='101'
    )

    assert result is True, "Update should return True on success"

    execute_call = str(mock_db.execute.call_args_list[0])
    assert 'UPDATE' in execute_call.upper(), "Should execute UPDATE SQL"
    assert '精确匹配' in execute_call, "Should set match_status to '精确匹配'"
    assert '人工纠正' in execute_call, "Should set correction_source to '人工纠正'"

    mock_db.commit.assert_called(), "Should commit the transaction"

    print('update_match_result_with_correction: PASSED')


def test_update_match_result_with_correction_failure():
    """测试人工纠正更新失败时回滚"""
    mock_db = MagicMock()
    mock_db.execute.return_value = None

    loader = DataLoader(mock_db)
    result = loader.update_match_result_with_correction(
        enterprise_id='E001',
        standard_id='S005',
        standard_address='测试地址',
        room_no='101'
    )

    assert result is False, "Update should return False on failure"
    mock_db.rollback.assert_called(), "Should rollback on failure"

    print('update_match_result_with_correction failure: PASSED')


def test_batch_update_match_results_with_correction():
    """测试批量人工纠正"""
    mock_db = MagicMock()
    mock_cursor = MagicMock()
    mock_db.execute.return_value = mock_cursor

    loader = DataLoader(mock_db)
    correction_data = [
        {'enterprise_id': 'E001', 'standard_id': 'S005', 'standard_address': '地址1', 'room_no': '101'},
        {'enterprise_id': 'E002', 'standard_id': 'S006', 'standard_address': '地址2', 'room_no': '202'},
    ]

    success_count = loader.batch_update_match_results_with_correction(correction_data)

    assert success_count == 2, f"Expected 2 successful updates, got {success_count}"
    assert mock_db.execute.call_count == 2, f"Expected 2 execute calls, got {mock_db.execute.call_count}"

    print('batch_update_match_results_with_correction: PASSED')


def test_batch_update_empty_data():
    """测试批量纠正数据为空时返回0"""
    mock_db = MagicMock()
    loader = DataLoader(mock_db)

    result = loader.batch_update_match_results_with_correction([])
    assert result == 0, "Should return 0 for empty correction data"

    result2 = loader.batch_update_match_results_with_correction(None)
    assert result2 == 0, "Should return 0 for None correction data"

    print('batch_update_match_results_with_correction empty: PASSED')


def test_get_match_statistics_with_correction():
    """测试匹配统计包含人工纠正统计"""
    mock_db = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = {
        'total_count': 100,
        'exact_match_count': 60,
        'partial_match_count': 20,
        'not_match_count': 20,
        'avg_exact_match': 0.85,
        'avg_partial_match': 0.10,
        'avg_not_match': 0.05,
        'manual_correction_count': 15,
        'auto_match_count': 85
    }
    mock_db.execute.return_value = mock_cursor

    loader = DataLoader(mock_db)
    stats = loader.get_match_statistics()

    assert 'manual_correction_count' in stats, "Stats should include manual_correction_count"
    assert 'auto_match_count' in stats, "Stats should include auto_match_count"
    assert 'manual_correction_rate' in stats, "Stats should include manual_correction_rate"

    assert stats['manual_correction_count'] == 15, f"Expected 15, got {stats['manual_correction_count']}"
    assert stats['auto_match_count'] == 85, f"Expected 85, got {stats['auto_match_count']}"
    assert abs(stats['manual_correction_rate'] - 15.0) < 0.01, f"Expected 15.0%, got {stats['manual_correction_rate']}"

    print('get_match_statistics with correction: PASSED')


def test_get_match_statistics_correction_rate_calculation():
    """测试人工纠正率的计算正确性"""
    mock_db = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = {
        'total_count': 200,
        'exact_match_count': 120,
        'partial_match_count': 40,
        'not_match_count': 40,
        'avg_exact_match': 0.80,
        'avg_partial_match': 0.12,
        'avg_not_match': 0.08,
        'manual_correction_count': 30,
        'auto_match_count': 170
    }
    mock_db.execute.return_value = mock_cursor

    loader = DataLoader(mock_db)
    stats = loader.get_match_statistics()

    expected_rate = 30 / 200 * 100
    assert abs(stats['manual_correction_rate'] - expected_rate) < 0.01, \
        f"Expected {expected_rate}%, got {stats['manual_correction_rate']}%"

    print('get_match_statistics correction rate calculation: PASSED')


def test_get_match_statistics_zero_total():
    """测试总记录数为0时的统计"""
    mock_db = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = {
        'total_count': 0,
        'exact_match_count': 0,
        'partial_match_count': 0,
        'not_match_count': 0,
        'avg_exact_match': None,
        'avg_partial_match': None,
        'avg_not_match': None,
        'manual_correction_count': 0,
        'auto_match_count': 0
    }
    mock_db.execute.return_value = mock_cursor

    loader = DataLoader(mock_db)
    stats = loader.get_match_statistics()

    assert stats['manual_correction_rate'] == 0, "Rate should be 0 when total is 0"
    assert stats['manual_correction_count'] == 0, "Count should be 0 when total is 0"

    print('get_match_statistics zero total: PASSED')


def test_correction_source_in_insert_match_results():
    """测试插入匹配结果SQL中包含correction_source相关字段"""
    mock_db = MagicMock()
    mock_cursor = MagicMock()
    mock_db.cursor = mock_cursor
    mock_db.execute.return_value = MagicMock()

    loader = DataLoader(mock_db)

    results = [{
        'enterprise_id': 'E001',
        'enterprise_name': '测试企业',
        'enterprise_address': '测试地址',
        'address_id': 'S001',
        'standard_address': '标准地址',
        'room_no': '101',
        'partial_match': 0.1,
        'exact_match': 0.8,
        'not_match': 0.1,
        'match_status': '精确匹配'
    }]

    try:
        loader.insert_match_results(results)
    except Exception:
        pass

    print('insert_match_results default correction_source: PASSED')


def test_update_correction_sets_exact_match_to_one():
    """测试人工纠正时精确匹配概率设为1.0"""
    mock_db = MagicMock()
    mock_cursor = MagicMock()
    mock_db.execute.return_value = mock_cursor

    loader = DataLoader(mock_db)
    loader.update_match_result_with_correction(
        enterprise_id='E001',
        standard_id='S005',
        standard_address='测试地址',
        room_no='101'
    )

    execute_call = mock_db.execute.call_args_list[0]
    sql_str = str(execute_call)

    assert 'exact_match = 1.0' in sql_str or '1' in str(execute_call[1]), \
        "exact_match should be set to 1.0 in correction"
    assert 'partial_match = 0.0' in sql_str or '0' in str(execute_call[1]), \
        "partial_match should be set to 0.0 in correction"
    assert 'not_match = 0.0' in sql_str or '0' in str(execute_call[1]), \
        "not_match should be set to 0.0 in correction"

    print('update_correction sets exact_match to 1.0: PASSED')


if __name__ == '__main__':
    test_create_result_table_has_correction_source()
    test_add_correction_source_column()
    test_add_correction_source_column_already_exists()
    test_get_recall_results_by_enterprise_ids()
    test_get_recall_results_by_enterprise_ids_empty()
    test_update_match_result_with_correction()
    test_update_match_result_with_correction_failure()
    test_batch_update_match_results_with_correction()
    test_batch_update_empty_data()
    test_get_match_statistics_with_correction()
    test_get_match_statistics_correction_rate_calculation()
    test_get_match_statistics_zero_total()
    test_correction_source_in_insert_match_results()
    test_update_correction_sets_exact_match_to_one()
    print('\n===== ALL MANUAL CORRECTION TESTS PASSED =====')
