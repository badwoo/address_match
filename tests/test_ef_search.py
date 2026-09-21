"""
ef_search 参数测试
=================

验证 HNSW 索引 ef_search 参数的推荐值计算和传递逻辑。

覆盖：
    1. get_recommended_ef_search：基于行数和 top_n 计算推荐值
    2. _set_index_search_param：接受 ef_search 参数，HNSW 索引时使用传入值
    3. batch_recall：ef_search 参数透传给 _set_index_search_param
    4. 非 HNSW 索引（ivfflat/none）时 ef_search 不生效
"""

import sys
import os
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _make_vector_store():
    """构造 VectorStore 实例，db 为 MagicMock"""
    from database.vector_store import VectorStore
    mock_db = MagicMock()
    return VectorStore(mock_db), mock_db


# ---------------------------------------------------------------------------
# get_recommended_ef_search
# ---------------------------------------------------------------------------

def test_get_recommended_ef_search_small_table():
    """行数 < 10万：推荐 64（但不低于 top_n）"""
    print("=" * 60)
    print("get_recommended_ef_search: 小表（<10万）推荐 64")
    print("=" * 60)

    vs, mock_db = _make_vector_store()
    with patch.object(vs, '_detect_vector_index_type', return_value='hnsw'), \
         patch.object(vs, 'get_vector_count', return_value=50_000):
        # top_n=10 < 64，推荐 64
        rec = vs.get_recommended_ef_search('std_vec', top_n=10)
        assert rec == 64, f"小表 top_n=10 应推荐 64，实际 {rec}"

        # top_n=100 > 64，推荐 100（HNSW 要求 ef_search >= top_n）
        rec = vs.get_recommended_ef_search('std_vec', top_n=100)
        assert rec == 100, f"小表 top_n=100 应推荐 100，实际 {rec}"

    print("  行数=50000, top_n=10 → 64 ✓")
    print("  行数=50000, top_n=100 → 100 ✓")
    print("\n[PASS] test_get_recommended_ef_search_small_table")
    return True


def test_get_recommended_ef_search_medium_table():
    """行数 10万-100万：推荐 128"""
    print("=" * 60)
    print("get_recommended_ef_search: 中表（10万-100万）推荐 128")
    print("=" * 60)

    vs, mock_db = _make_vector_store()
    with patch.object(vs, '_detect_vector_index_type', return_value='hnsw'), \
         patch.object(vs, 'get_vector_count', return_value=500_000):
        rec = vs.get_recommended_ef_search('std_vec', top_n=10)
        assert rec == 128, f"中表应推荐 128，实际 {rec}"

    print("  行数=500000, top_n=10 → 128 ✓")
    print("\n[PASS] test_get_recommended_ef_search_medium_table")
    return True


def test_get_recommended_ef_search_large_table():
    """行数 100万-1000万：推荐 256"""
    print("=" * 60)
    print("get_recommended_ef_search: 大表（100万-1000万）推荐 256")
    print("=" * 60)

    vs, mock_db = _make_vector_store()
    with patch.object(vs, '_detect_vector_index_type', return_value='hnsw'), \
         patch.object(vs, 'get_vector_count', return_value=5_000_000):
        rec = vs.get_recommended_ef_search('std_vec', top_n=10)
        assert rec == 256, f"大表应推荐 256，实际 {rec}"

    print("  行数=5000000, top_n=10 → 256 ✓")
    print("\n[PASS] test_get_recommended_ef_search_large_table")
    return True


def test_get_recommended_ef_search_huge_table():
    """行数 >= 1000万：推荐 512"""
    print("=" * 60)
    print("get_recommended_ef_search: 巨表（>=1000万）推荐 512")
    print("=" * 60)

    vs, mock_db = _make_vector_store()
    with patch.object(vs, '_detect_vector_index_type', return_value='hnsw'), \
         patch.object(vs, 'get_vector_count', return_value=20_000_000):
        rec = vs.get_recommended_ef_search('std_vec', top_n=10)
        assert rec == 512, f"巨表应推荐 512，实际 {rec}"

    print("  行数=20000000, top_n=10 → 512 ✓")
    print("\n[PASS] test_get_recommended_ef_search_huge_table")
    return True


def test_get_recommended_ef_search_non_hnsw_returns_none():
    """非 HNSW 索引（ivfflat/none）返回 None"""
    print("=" * 60)
    print("get_recommended_ef_search: 非 HNSW 索引返回 None")
    print("=" * 60)

    vs, mock_db = _make_vector_store()

    with patch.object(vs, '_detect_vector_index_type', return_value='ivfflat'):
        rec = vs.get_recommended_ef_search('std_vec', top_n=10)
        assert rec is None, f"ivfflat 索引应返回 None，实际 {rec}"

    with patch.object(vs, '_detect_vector_index_type', return_value='none'):
        rec = vs.get_recommended_ef_search('std_vec', top_n=10)
        assert rec is None, f"无索引应返回 None，实际 {rec}"

    print("  ivfflat → None ✓")
    print("  none → None ✓")
    print("\n[PASS] test_get_recommended_ef_search_non_hnsw_returns_none")
    return True


def test_get_recommended_ef_search_top_n_floor():
    """推荐值不低于 top_n（HNSW 硬性要求）"""
    print("=" * 60)
    print("get_recommended_ef_search: 推荐值 >= top_n")
    print("=" * 60)

    vs, mock_db = _make_vector_store()
    with patch.object(vs, '_detect_vector_index_type', return_value='hnsw'), \
         patch.object(vs, 'get_vector_count', return_value=50_000):
        # base=64, top_n=200 → 推荐 200
        rec = vs.get_recommended_ef_search('std_vec', top_n=200)
        assert rec == 200, f"top_n=200 应推荐 200，实际 {rec}"

        # base=64, top_n=64 → 推荐 64
        rec = vs.get_recommended_ef_search('std_vec', top_n=64)
        assert rec == 64, f"top_n=64 应推荐 64，实际 {rec}"

    print("  top_n=200, base=64 → 200 ✓")
    print("  top_n=64, base=64 → 64 ✓")
    print("\n[PASS] test_get_recommended_ef_search_top_n_floor")
    return True


# ---------------------------------------------------------------------------
# _set_index_search_param
# ---------------------------------------------------------------------------

def test_set_index_search_param_uses_user_ef_search_for_hnsw():
    """HNSW 索引时，_set_index_search_param 使用用户传入的 ef_search"""
    print("=" * 60)
    print("_set_index_search_param: HNSW 使用用户 ef_search")
    print("=" * 60)

    vs, mock_db = _make_vector_store()
    mock_cursor = MagicMock()
    mock_db.execute.return_value = mock_cursor

    with patch.object(vs, '_detect_vector_index_type', return_value='hnsw'):
        vs._set_index_search_param('std_vec', top_n=10, ef_search=256)

    # 验证 SET hnsw.ef_search = 256 被执行
    execute_calls = [call[0][0] for call in mock_db.execute.call_args_list]
    set_call = [s for s in execute_calls if 'SET hnsw.ef_search' in s]
    assert len(set_call) == 1, f"应执行一次 SET hnsw.ef_search，实际 {set_call}"
    assert '256' in set_call[0], f"应设置 ef_search=256，实际 {set_call[0]}"

    print(f"  执行 SQL: {set_call[0]}")
    print("  HNSW 使用用户 ef_search=256 ✓")
    print("\n[PASS] test_set_index_search_param_uses_user_ef_search_for_hnsw")
    return True


def test_set_index_search_param_ef_search_floored_to_top_n():
    """HNSW 索引时，ef_search < top_n 会被提升到 top_n"""
    print("=" * 60)
    print("_set_index_search_param: ef_search < top_n 时提升到 top_n")
    print("=" * 60)

    vs, mock_db = _make_vector_store()
    mock_cursor = MagicMock()
    mock_db.execute.return_value = mock_cursor

    with patch.object(vs, '_detect_vector_index_type', return_value='hnsw'):
        # ef_search=50, top_n=100 → 最终 ef_search=100
        vs._set_index_search_param('std_vec', top_n=100, ef_search=50)

    execute_calls = [call[0][0] for call in mock_db.execute.call_args_list]
    set_call = [s for s in execute_calls if 'SET hnsw.ef_search' in s][0]
    assert '100' in set_call, f"ef_search=50, top_n=100 应提升到 100，实际 {set_call}"

    print(f"  执行 SQL: {set_call}")
    print("  ef_search=50, top_n=100 → 100 ✓")
    print("\n[PASS] test_set_index_search_param_ef_search_floored_to_top_n")
    return True


def test_set_index_search_param_none_ef_search_uses_default():
    """HNSW 索引时，ef_search=None 使用默认 max(top_n, 128)"""
    print("=" * 60)
    print("_set_index_search_param: ef_search=None 使用默认值")
    print("=" * 60)

    vs, mock_db = _make_vector_store()
    mock_cursor = MagicMock()
    mock_db.execute.return_value = mock_cursor

    with patch.object(vs, '_detect_vector_index_type', return_value='hnsw'):
        # ef_search=None, top_n=10 → 默认 max(10, 128)=128
        vs._set_index_search_param('std_vec', top_n=10, ef_search=None)

    execute_calls = [call[0][0] for call in mock_db.execute.call_args_list]
    set_call = [s for s in execute_calls if 'SET hnsw.ef_search' in s][0]
    assert '128' in set_call, f"ef_search=None, top_n=10 应使用默认 128，实际 {set_call}"

    print(f"  执行 SQL: {set_call}")
    print("  ef_search=None, top_n=10 → 128 ✓")
    print("\n[PASS] test_set_index_search_param_none_ef_search_uses_default")
    return True


# ---------------------------------------------------------------------------
# batch_recall 透传 ef_search
# ---------------------------------------------------------------------------

def test_batch_recall_passes_ef_search_to_set_index_search_param():
    """batch_recall 将 ef_search 透传给 _set_index_search_param"""
    print("=" * 60)
    print("batch_recall: ef_search 透传给 _set_index_search_param")
    print("=" * 60)

    vs, mock_db = _make_vector_store()
    mock_cursor = MagicMock()
    mock_db.execute.return_value = mock_cursor
    mock_cursor.fetchall.return_value = []  # 返回空结果，避免分组逻辑

    with patch.object(vs, '_set_index_search_param') as mock_set, \
         patch.object(vs, '_detect_vector_index_type', return_value='hnsw'):
        vs.batch_recall('ent_vec', 'std_vec', top_n=10, ef_search=256)

        # 验证 _set_index_search_param 被调用，且 ef_search=256
        mock_set.assert_called_once()
        call_kwargs = mock_set.call_args
        assert call_kwargs[1].get('ef_search') == 256, \
            f"batch_recall 应透传 ef_search=256，实际调用 {call_kwargs}"

    print("  batch_recall(top_n=10, ef_search=256) → _set_index_search_param(ef_search=256) ✓")
    print("\n[PASS] test_batch_recall_passes_ef_search_to_set_index_search_param")
    return True


def test_batch_recall_default_ef_search_none():
    """batch_recall 未传 ef_search 时，_set_index_search_param 收到 None"""
    print("=" * 60)
    print("batch_recall: 默认 ef_search=None")
    print("=" * 60)

    vs, mock_db = _make_vector_store()
    mock_cursor = MagicMock()
    mock_db.execute.return_value = mock_cursor
    mock_cursor.fetchall.return_value = []

    with patch.object(vs, '_set_index_search_param') as mock_set, \
         patch.object(vs, '_detect_vector_index_type', return_value='hnsw'):
        vs.batch_recall('ent_vec', 'std_vec', top_n=10)

        mock_set.assert_called_once()
        call_kwargs = mock_set.call_args
        assert call_kwargs[1].get('ef_search') is None, \
            f"未传 ef_search 时应为 None，实际 {call_kwargs}"

    print("  batch_recall(top_n=10) → _set_index_search_param(ef_search=None) ✓")
    print("\n[PASS] test_batch_recall_default_ef_search_none")
    return True


# ---------------------------------------------------------------------------
# matcher.start_recall_async 透传 ef_search
# ---------------------------------------------------------------------------

def test_start_recall_async_passes_ef_search_to_batch_recall():
    """start_recall_async 将 ef_search 透传给 batch_recall"""
    print("=" * 60)
    print("start_recall_async: ef_search 透传给 batch_recall")
    print("=" * 60)

    from matching.matcher import AddressMatcher
    mock_db = MagicMock()
    mock_db.execute.return_value = MagicMock()

    matcher = AddressMatcher(mock_db, device='cpu', mode='recall_only')

    # mock data_loader 和 vector_store 避免 DB 操作
    matcher.data_loader = MagicMock()
    matcher.vector_store = MagicMock()
    matcher.vector_store.batch_recall.return_value = []

    # 启动异步任务
    matcher.start_recall_async(
        enterprise_table='ent_vec',
        standard_table='std_vec',
        top_n=10,
        ef_search=256,
        recall_table='recall_results',
    )

    # 等待线程完成（设置短超时）
    if matcher.matching_thread:
        matcher.matching_thread.join(timeout=5)

    # 验证 batch_recall 被调用，且 ef_search=256
    matcher.vector_store.batch_recall.assert_called_once()
    call_kwargs = matcher.vector_store.batch_recall.call_args[1]
    assert call_kwargs.get('ef_search') == 256, \
        f"start_recall_async 应透传 ef_search=256，实际 {call_kwargs}"

    print("  start_recall_async(ef_search=256) → batch_recall(ef_search=256) ✓")
    print("\n[PASS] test_start_recall_async_passes_ef_search_to_batch_recall")
    return True


def run_all_tests():
    """运行全部测试"""
    tests = [
        test_get_recommended_ef_search_small_table,
        test_get_recommended_ef_search_medium_table,
        test_get_recommended_ef_search_large_table,
        test_get_recommended_ef_search_huge_table,
        test_get_recommended_ef_search_non_hnsw_returns_none,
        test_get_recommended_ef_search_top_n_floor,
        test_set_index_search_param_uses_user_ef_search_for_hnsw,
        test_set_index_search_param_ef_search_floored_to_top_n,
        test_set_index_search_param_none_ef_search_uses_default,
        test_batch_recall_passes_ef_search_to_set_index_search_param,
        test_batch_recall_default_ef_search_none,
        test_start_recall_async_passes_ef_search_to_batch_recall,
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
