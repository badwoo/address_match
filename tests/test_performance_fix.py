"""
测试修复：OOM、深度分页、向量逐条插入三个性能问题

测试内容：
    1. batch_rank_optimized 使用分块处理，避免OOM
    2. load_enterprise_data / load_standard_addresses 使用游标分页
    3. insert_vectors 使用 execute_values 批量插入
"""

import sys
import os
import inspect

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _read_source(relative_path):
    file_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), relative_path)
    with open(file_path, 'r', encoding='utf-8') as f:
        return f.read()


# ===================== 测试1：batch_rank_optimized 分块处理 =====================

def test_batch_rank_optimized_has_chunk_size_param():
    source = _read_source('matching/ranking.py')
    assert 'chunk_size=5000' in source, \
        "batch_rank_optimized should accept chunk_size parameter with default 5000"
    print("test_batch_rank_optimized_has_chunk_size_param: PASSED")


def test_batch_rank_optimized_uses_chunked_loop():
    source = _read_source('matching/ranking.py')
    batch_rank_start = source.index('def batch_rank_optimized')
    batch_rank_source = source[batch_rank_start:]

    assert 'chunk_start' in batch_rank_source, \
        "batch_rank_optimized should use chunk_start variable for chunked processing"
    assert 'chunk_end' in batch_rank_source, \
        "batch_rank_optimized should use chunk_end variable for chunked processing"
    assert 'chunk_items' in batch_rank_source, \
        "batch_rank_optimized should use chunk_items variable"
    assert 'chunk_pairs' in batch_rank_source, \
        "batch_rank_optimized should use chunk_pairs instead of all_pairs"
    print("test_batch_rank_optimized_uses_chunked_loop: PASSED")


def test_batch_rank_optimized_no_all_pairs():
    source = _read_source('matching/ranking.py')
    batch_rank_start = source.index('def batch_rank_optimized')
    batch_rank_source = source[batch_rank_start:]

    assert 'all_pairs' not in batch_rank_source, \
        "batch_rank_optimized should NOT use all_pairs variable (replaced by chunked processing)"
    print("test_batch_rank_optimized_no_all_pairs: PASSED")


def test_batch_rank_optimized_calls_predict_per_chunk():
    source = _read_source('matching/ranking.py')
    batch_rank_start = source.index('def batch_rank_optimized')
    batch_rank_source = source[batch_rank_start:]

    assert 'predict_optimized(chunk_pairs' in batch_rank_source, \
        "batch_rank_optimized should call predict_optimized with chunk_pairs (not all_pairs)"
    assert 'chunk_size' in batch_rank_source, \
        "batch_rank_optimized should use chunk_size parameter"
    assert 'for chunk_start in range(0, total, chunk_size)' in batch_rank_source, \
        "batch_rank_optimized should iterate over chunks"
    print("test_batch_rank_optimized_calls_predict_per_chunk: PASSED")


def test_batch_rank_optimized_preserves_result_order():
    source = _read_source('matching/ranking.py')
    batch_rank_start = source.index('def batch_rank_optimized')
    batch_rank_source = source[batch_rank_start:]

    assert 'final_results = [None] * total' in batch_rank_source, \
        "batch_rank_optimized should pre-allocate results list to preserve order"
    assert 'global_idx = chunk_start + idx' in batch_rank_source, \
        "batch_rank_optimized should use global_idx to map chunk results back to original order"
    assert 'final_results[global_idx]' in batch_rank_source, \
        "batch_rank_optimized should assign results by global index"
    print("test_batch_rank_optimized_preserves_result_order: PASSED")


def test_batch_rank_optimized_still_has_threshold_filter():
    source = _read_source('matching/ranking.py')
    batch_rank_start = source.index('def batch_rank_optimized')
    batch_rank_source = source[batch_rank_start:]

    assert 'similarity_threshold' in batch_rank_source, \
        "batch_rank_optimized should still accept similarity_threshold parameter"
    assert 'filtered_candidates' in batch_rank_source, \
        "batch_rank_optimized should still filter candidates by threshold"
    assert "c.get('similarity'" in batch_rank_source, \
        "batch_rank_optimized should still check candidate similarity"
    print("test_batch_rank_optimized_still_has_threshold_filter: PASSED")


def test_batch_rank_optimized_result_format_unchanged():
    source = _read_source('matching/ranking.py')
    batch_rank_start = source.index('def batch_rank_optimized')
    batch_rank_source = source[batch_rank_start:]

    required_fields = [
        "'enterprise_id'", "'enterprise_name'", "'enterprise_address'",
        "'address_id'", "'standard_address'", "'room_no'",
        "'exact_match'", "'partial_match'", "'not_match'", "'match_status'"
    ]
    for field in required_fields:
        assert field in batch_rank_source, \
            f"batch_rank_optimized result should still contain {field} field"
    print("test_batch_rank_optimized_result_format_unchanged: PASSED")


# ===================== 测试2：游标分页 =====================

def test_load_enterprise_data_no_offset():
    source = _read_source('database/data_loader.py')
    load_enterprise_start = source.index('def load_enterprise_data')
    load_enterprise_end = source.index('def load_standard_addresses')
    load_enterprise_source = source[load_enterprise_start:load_enterprise_end]

    assert 'LIMIT %s OFFSET %s' not in load_enterprise_source, \
        "load_enterprise_data should NOT use LIMIT/OFFSET pagination in SQL"
    assert 'last_id' in load_enterprise_source, \
        "load_enterprise_data should use last_id for cursor-based pagination"
    assert 'id_col} > %s' in load_enterprise_source or '{id_col} > %s' in load_enterprise_source, \
        "load_enterprise_data should use id > last_id condition for cursor pagination"
    print("test_load_enterprise_data_no_offset: PASSED")


def test_load_standard_addresses_no_offset():
    source = _read_source('database/data_loader.py')
    load_standard_start = source.index('def load_standard_addresses')
    load_standard_end = source.index('def get_total_count')
    load_standard_source = source[load_standard_start:load_standard_end]

    assert 'LIMIT %s OFFSET %s' not in load_standard_source, \
        "load_standard_addresses should NOT use LIMIT/OFFSET pagination in SQL"
    assert 'last_id' in load_standard_source, \
        "load_standard_addresses should use last_id for cursor-based pagination"
    print("test_load_standard_addresses_no_offset: PASSED")


def test_load_enterprise_data_cursor_pattern():
    source = _read_source('database/data_loader.py')
    load_enterprise_start = source.index('def load_enterprise_data')
    load_enterprise_end = source.index('def load_standard_addresses')
    load_enterprise_source = source[load_enterprise_start:load_enterprise_end]

    assert 'if last_id is None' in load_enterprise_source, \
        "load_enterprise_data should handle first page (last_id is None) differently"
    assert 'last_id = rows[-1][id_col]' in load_enterprise_source or "last_id = rows[-1][id_col]" in load_enterprise_source, \
        "load_enterprise_data should update last_id from last row's id column"
    assert 'ORDER BY {id_col}' in load_enterprise_source, \
        "load_enterprise_data should ORDER BY id column for cursor pagination to work"
    print("test_load_enterprise_data_cursor_pattern: PASSED")


def test_load_standard_addresses_cursor_pattern():
    source = _read_source('database/data_loader.py')
    load_standard_start = source.index('def load_standard_addresses')
    load_standard_end = source.index('def get_total_count')
    load_standard_source = source[load_standard_start:load_standard_end]

    assert 'if last_id is None' in load_standard_source, \
        "load_standard_addresses should handle first page (last_id is None) differently"
    assert 'last_id = rows[-1][id_col]' in load_standard_source or "last_id = rows[-1][id_col]" in load_standard_source, \
        "load_standard_addresses should update last_id from last row's id column"
    print("test_load_standard_addresses_cursor_pattern: PASSED")


# ===================== 测试3：向量批量插入 =====================

def test_insert_vectors_uses_execute_values():
    source = _read_source('database/vector_store.py')
    insert_start = source.index('def insert_vectors')
    insert_end = source.index('def _verify_inserted_vectors')
    insert_source = source[insert_start:insert_end]

    assert 'execute_values' in insert_source, \
        "insert_vectors should use psycopg2.extras.execute_values for batch insertion"
    assert 'psycopg2.extras.execute_values' in insert_source, \
        "insert_vectors should use psycopg2.extras.execute_values"
    print("test_insert_vectors_uses_execute_values: PASSED")


def test_insert_vectors_no_individual_execute_in_loop():
    source = _read_source('database/vector_store.py')
    insert_start = source.index('def insert_vectors')
    insert_end = source.index('def _verify_inserted_vectors')
    insert_source = source[insert_start:insert_end]

    assert 'self.db.execute(sql, params)' not in insert_source, \
        "insert_vectors should NOT use individual execute() calls with params"
    assert 'self.db.execute(sql, (' not in insert_source, \
        "insert_vectors should NOT use individual execute() calls with tuple params"
    print("test_insert_vectors_no_individual_execute_in_loop: PASSED")


def test_insert_vectors_has_chunk_size_param():
    source = _read_source('database/vector_store.py')
    assert 'insert_chunk_size=5000' in source, \
        "insert_vectors should accept insert_chunk_size parameter with default 5000"
    print("test_insert_vectors_has_chunk_size_param: PASSED")


def test_insert_vectors_uses_template_with_vector_cast():
    source = _read_source('database/vector_store.py')
    insert_start = source.index('def insert_vectors')
    insert_end = source.index('def _verify_inserted_vectors')
    insert_source = source[insert_start:insert_end]

    assert '::vector(' in insert_source, \
        "insert_vectors template should cast vector column with ::vector(dim)"
    assert 'template=' in insert_source, \
        "insert_vectors should pass template parameter to execute_values"
    print("test_insert_vectors_uses_template_with_vector_cast: PASSED")


def test_insert_vectors_chunked_loop():
    source = _read_source('database/vector_store.py')
    insert_start = source.index('def insert_vectors')
    insert_end = source.index('def _verify_inserted_vectors')
    insert_source = source[insert_start:insert_end]

    assert 'range(0, total, insert_chunk_size)' in insert_source, \
        "insert_vectors should iterate over chunks using insert_chunk_size"
    assert 'chunk_end = min(chunk_start + insert_chunk_size, total)' in insert_source, \
        "insert_vectors should calculate chunk_end"
    print("test_insert_vectors_chunked_loop: PASSED")


def test_insert_vectors_commit_per_chunk():
    source = _read_source('database/vector_store.py')
    insert_start = source.index('def insert_vectors')
    insert_end = source.index('def _verify_inserted_vectors')
    insert_source = source[insert_start:insert_end]

    # 新实现使用 self.db.conn.commit() 配合 autocommit=False 进行批量事务提交
    assert 'self.db.conn.commit()' in insert_source or 'self.db.commit()' in insert_source, \
        "insert_vectors should commit within chunk loop"
    print("test_insert_vectors_commit_per_chunk: PASSED")


def test_insert_vectors_batched_commits():
    """验证 insert_vectors 支持批量提交（commit_every_n_chunks 参数）"""
    source = _read_source('database/vector_store.py')
    assert 'commit_every_n_chunks' in source, \
        "insert_vectors should support commit_every_n_chunks parameter for batched commits"
    print("test_insert_vectors_batched_commits: PASSED")


def test_insert_vectors_autocommit_restore():
    """验证 insert_vectors 在 finally 中恢复 autocommit 状态"""
    source = _read_source('database/vector_store.py')
    insert_start = source.index('def insert_vectors')
    insert_end = source.index('def _verify_inserted_vectors')
    insert_source = source[insert_start:insert_end]

    assert 'was_autocommit' in insert_source, \
        "insert_vectors should save original autocommit state"
    assert 'self.db.conn.autocommit = was_autocommit' in insert_source, \
        "insert_vectors should restore autocommit in finally block"
    print("test_insert_vectors_autocommit_restore: PASSED")


def test_vector_to_pg_string_method():
    """验证 _vector_to_pg_string 静态方法使用 numpy vectorized 操作"""
    source = _read_source('database/vector_store.py')
    assert 'def _vector_to_pg_string' in source, \
        "VectorStore should have _vector_to_pg_string static method"
    assert 'np.array2string' in source, \
        "_vector_to_pg_string should use np.array2string for vectorized conversion"
    print("test_vector_to_pg_string_method: PASSED")


def test_autovacuum_methods():
    """验证新增的 autovacuum 管理方法"""
    source = _read_source('database/vector_store.py')
    assert 'def disable_autovacuum' in source, \
        "VectorStore should have disable_autovacuum method"
    assert 'def enable_autovacuum' in source, \
        "VectorStore should have enable_autovacuum method"
    assert 'def vacuum_table' in source, \
        "VectorStore should have vacuum_table method"
    print("test_autovacuum_methods: PASSED")


def test_insert_vectors_preserves_enterprise_and_standard_types():
    source = _read_source('database/vector_store.py')
    insert_start = source.index('def insert_vectors')
    insert_end = source.index('def _verify_inserted_vectors')
    insert_source = source[insert_start:insert_end]

    assert "table_type == 'enterprise'" in insert_source, \
        "insert_vectors should still handle enterprise table type"
    assert 'enterprise_name' in insert_source, \
        "insert_vectors should include enterprise_name for enterprise type"
    assert 'room_no' in insert_source, \
        "insert_vectors should include room_no for standard type"
    print("test_insert_vectors_preserves_enterprise_and_standard_types: PASSED")


# ===================== 运行所有测试 =====================

if __name__ == '__main__':
    test_batch_rank_optimized_has_chunk_size_param()
    test_batch_rank_optimized_uses_chunked_loop()
    test_batch_rank_optimized_no_all_pairs()
    test_batch_rank_optimized_calls_predict_per_chunk()
    test_batch_rank_optimized_preserves_result_order()
    test_batch_rank_optimized_still_has_threshold_filter()
    test_batch_rank_optimized_result_format_unchanged()

    test_load_enterprise_data_no_offset()
    test_load_standard_addresses_no_offset()
    test_load_enterprise_data_cursor_pattern()
    test_load_standard_addresses_cursor_pattern()

    test_insert_vectors_uses_execute_values()
    test_insert_vectors_no_individual_execute_in_loop()
    test_insert_vectors_has_chunk_size_param()
    test_insert_vectors_uses_template_with_vector_cast()
    test_insert_vectors_chunked_loop()
    test_insert_vectors_commit_per_chunk()
    test_insert_vectors_batched_commits()
    test_insert_vectors_autocommit_restore()
    test_vector_to_pg_string_method()
    test_autovacuum_methods()
    test_insert_vectors_preserves_enterprise_and_standard_types()

    print('\n===== ALL TESTS PASSED =====')
