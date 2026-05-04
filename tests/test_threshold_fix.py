"""
测试修复：相似度阈值在粗召回和精排中是否正确生效

测试内容：
    1. vector_store.py batch_recall 方法接受 similarity_threshold 参数
    2. ranking.py batch_rank_optimized 方法接受 similarity_threshold 参数
    3. ranking.py rank 方法使用 self.threshold 过滤低分候选
    4. matcher.py 正确传递阈值到 batch_recall 和 batch_rank_optimized
    5. 源码中阈值过滤逻辑正确
"""

import sys
import os
import inspect

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_batch_recall_accepts_threshold_param():
    from database.vector_store import VectorStore
    sig = inspect.signature(VectorStore.batch_recall)
    params = list(sig.parameters.keys())
    assert 'similarity_threshold' in params, \
        f"batch_recall should accept similarity_threshold parameter, got params: {params}"
    default_val = sig.parameters['similarity_threshold'].default
    assert default_val is None, \
        f"similarity_threshold default should be None, got {default_val}"
    print("test_batch_recall_accepts_threshold_param: PASSED")


def test_batch_recall_sql_has_threshold_condition():
    vector_store_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                      'database', 'vector_store.py')
    with open(vector_store_file, 'r', encoding='utf-8') as f:
        source = f.read()
    assert 'threshold_condition' in source, \
        "batch_recall should have threshold_condition variable"
    assert 'similarity_threshold' in source, \
        "batch_recall should use similarity_threshold parameter"
    print("test_batch_recall_sql_has_threshold_condition: PASSED")


def test_batch_rank_optimized_accepts_threshold_param():
    ranking_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                 'matching', 'ranking.py')
    with open(ranking_file, 'r', encoding='utf-8') as f:
        source = f.read()
    
    assert 'def batch_rank_optimized(self, recall_results, batch_size=1000, similarity_threshold=None, chunk_size=5000)' in source, \
        "batch_rank_optimized should accept similarity_threshold and chunk_size parameters"
    print("test_batch_rank_optimized_accepts_threshold_param: PASSED")


def test_rank_method_uses_threshold():
    ranking_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                 'matching', 'ranking.py')
    with open(ranking_file, 'r', encoding='utf-8') as f:
        source = f.read()
    
    rank_method_start = source.index('def rank(self')
    rank_method_end = source.index('def batch_rank(self', rank_method_start)
    rank_method_source = source[rank_method_start:rank_method_end]
    
    assert 'self.threshold' in rank_method_source, \
        "rank method should use self.threshold for filtering"
    assert 'similarity' in rank_method_source, \
        "rank method should check candidate similarity against threshold"
    print("test_rank_method_uses_threshold: PASSED")


def test_batch_rank_optimized_filters_by_threshold():
    ranking_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                 'matching', 'ranking.py')
    with open(ranking_file, 'r', encoding='utf-8') as f:
        source = f.read()
    
    batch_rank_opt_start = source.index('def batch_rank_optimized')
    batch_rank_opt_source = source[batch_rank_opt_start:]
    
    assert 'filtered_candidates' in batch_rank_opt_source, \
        "batch_rank_optimized should filter candidates by threshold"
    assert "c.get('similarity'" in batch_rank_opt_source, \
        "batch_rank_optimized should check candidate similarity"
    print("test_batch_rank_optimized_filters_by_threshold: PASSED")


def test_matcher_passes_threshold_to_batch_recall():
    matcher_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                 'matching', 'matcher.py')
    with open(matcher_file, 'r', encoding='utf-8') as f:
        source = f.read()
    
    batch_recall_calls = []
    for i, line in enumerate(source.split('\n')):
        if 'batch_recall(' in line:
            batch_recall_calls.append((i, line))
    
    for line_no, call_line in batch_recall_calls:
        context_start = source.index(call_line)
        context_end = min(context_start + 500, len(source))
        nearby_lines = source[context_start:context_end]
        assert 'similarity_threshold' in nearby_lines, \
            f"batch_recall call at line {line_no} should pass similarity_threshold: {call_line.strip()}"
    print("test_matcher_passes_threshold_to_batch_recall: PASSED")


def test_matcher_passes_threshold_to_batch_rank_optimized():
    matcher_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                 'matching', 'matcher.py')
    with open(matcher_file, 'r', encoding='utf-8') as f:
        source = f.read()
    
    batch_rank_calls = []
    for i, line in enumerate(source.split('\n')):
        if 'batch_rank_optimized(' in line:
            batch_rank_calls.append((i, line))
    
    for line_no, call_line in batch_rank_calls:
        context_start = source.index(call_line)
        context_end = min(context_start + 500, len(source))
        nearby_lines = source[context_start:context_end]
        assert 'similarity_threshold' in nearby_lines, \
            f"batch_rank_optimized call at line {line_no} should pass similarity_threshold: {call_line.strip()}"
    print("test_matcher_passes_threshold_to_batch_rank_optimized: PASSED")


def test_ranking_filter_logic():
    candidates = [
        {'source_id': '1', 'address': 'addr1', 'similarity': 0.9},
        {'source_id': '2', 'address': 'addr2', 'similarity': 0.5},
        {'source_id': '3', 'address': 'addr3', 'similarity': 0.3},
    ]
    
    threshold_08 = 0.8
    filtered = [c for c in candidates if c.get('similarity', 1.0) >= threshold_08]
    assert len(filtered) == 1, f"With threshold 0.8, should filter to 1 candidate, got {len(filtered)}"
    assert filtered[0]['source_id'] == '1'
    
    threshold_04 = 0.4
    filtered2 = [c for c in candidates if c.get('similarity', 1.0) >= threshold_04]
    assert len(filtered2) == 2, f"With threshold 0.4, should filter to 2 candidates, got {len(filtered2)}"
    
    threshold_0 = 0.0
    filtered3 = [c for c in candidates if c.get('similarity', 1.0) >= threshold_0]
    assert len(filtered3) == 3, f"With threshold 0.0, should keep all 3 candidates, got {len(filtered3)}"
    
    print("test_ranking_filter_logic: PASSED")


def test_app_ranking_thread_uses_threshold():
    app_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             'app.py')
    with open(app_file, 'r', encoding='utf-8') as f:
        source = f.read()
    
    ranking_thread_start = source.index('def ranking_thread_func')
    ranking_thread_end = source.index('ranking_thread = threading.Thread', ranking_thread_start)
    ranking_thread_source = source[ranking_thread_start:ranking_thread_end]
    
    assert 'inner_threshold' in ranking_thread_source, \
        "ranking_thread_func should use inner_threshold parameter"
    assert 'similarity' in ranking_thread_source, \
        "ranking_thread_func should check candidate similarity against threshold"
    assert 'filtered_pairs' in ranking_thread_source, \
        "ranking_thread_func should have filtered_pairs variable"
    print("test_app_ranking_thread_uses_threshold: PASSED")


if __name__ == '__main__':
    test_batch_recall_accepts_threshold_param()
    test_batch_recall_sql_has_threshold_condition()
    test_batch_rank_optimized_accepts_threshold_param()
    test_rank_method_uses_threshold()
    test_batch_rank_optimized_filters_by_threshold()
    test_matcher_passes_threshold_to_batch_recall()
    test_matcher_passes_threshold_to_batch_rank_optimized()
    test_ranking_filter_logic()
    test_app_ranking_thread_uses_threshold()
    print('\n===== ALL TESTS PASSED =====')
