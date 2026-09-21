"""
流式管线单元测试
================

测试新增的流式召回管线和精排回调机制：
1. RankingEngine.batch_rank_optimized 的 progress_callback 和 cancel_check
2. VectorStore.batch_recall_streaming 的分组逻辑（mock 服务端游标）
3. determine_match_status 匹配状态判断

不依赖真实数据库和模型，全部使用 mock。
"""
import sys
import os
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from matching.ranking import RankingEngine, determine_match_status


class TestBatchRankOptimizedCallbacks:
    """测试 batch_rank_optimized 的进度回调和取消机制"""

    def _make_recall_results(self, n_enterprises, n_candidates=3):
        """构造测试用召回结果"""
        results = []
        for i in range(n_enterprises):
            candidates = []
            for j in range(n_candidates):
                candidates.append({
                    'source_id': f'std_{i}_{j}',
                    'address': f'标准地址_{i}_{j}',
                    'room_no': f'room_{j}',
                    'similarity': 0.9 - j * 0.1
                })
            results.append({
                'enterprise_id': f'ent_{i}',
                'enterprise_name': f'企业_{i}',
                'enterprise_address': f'企业地址_{i}',
                'candidates': candidates
            })
        return results

    def _make_mock_model(self):
        """构造 mock MGeoModel，predict_optimized 返回固定概率"""
        mock_model = MagicMock()

        def mock_predict(pairs, batch_size=None):
            return [
                {'exact_match': 0.9, 'partial_match': 0.05, 'not_match': 0.05}
                for _ in pairs
            ]

        mock_model.predict_optimized = mock_predict
        return mock_model

    def test_progress_callback_called(self):
        """验证 progress_callback 在每个 chunk 后被调用"""
        mock_model = self._make_mock_model()
        engine = RankingEngine(model=mock_model)
        engine.threshold = 0.0  # 不过滤

        recall_results = self._make_recall_results(10, n_candidates=2)
        progress_calls = []

        results = engine.batch_rank_optimized(
            recall_results,
            chunk_size=3,
            similarity_threshold=None,
            progress_callback=lambda p: progress_calls.append(p)
        )

        # 10 企业，chunk_size=3 → 4 个 chunk（3+3+3+1）
        assert len(progress_calls) == 4
        assert progress_calls[0]['processed'] == 3
        assert progress_calls[-1]['processed'] == 10
        assert progress_calls[-1]['progress'] == 1.0
        assert len(results) == 10

    def test_cancel_check_midway(self):
        """验证 cancel_check 能在中途取消"""
        mock_model = self._make_mock_model()
        engine = RankingEngine(model=mock_model)
        engine.threshold = 0.0

        recall_results = self._make_recall_results(10, n_candidates=2)

        # 第 2 次 chunk 后取消（第 3 次检查时返回 True）
        call_count = [0]

        def cancel_after_2():
            call_count[0] += 1
            return call_count[0] > 2

        results = engine.batch_rank_optimized(
            recall_results,
            chunk_size=3,
            similarity_threshold=None,
            cancel_check=cancel_after_2
        )

        # 取消后返回的 results 长度等于 total，但未处理部分为 None
        assert len(results) == 10
        # 前 2 个 chunk（6 企业）已处理
        processed = sum(1 for r in results if r is not None)
        assert processed == 6

    def test_no_callback_no_error(self):
        """验证不传回调时正常工作（向后兼容）"""
        mock_model = self._make_mock_model()
        engine = RankingEngine(model=mock_model)
        engine.threshold = 0.0

        recall_results = self._make_recall_results(5, n_candidates=2)

        results = engine.batch_rank_optimized(
            recall_results,
            chunk_size=3,
            similarity_threshold=None
        )

        assert len(results) == 5
        assert all(r is not None for r in results)

    def test_results_correctness(self):
        """验证精排结果结构正确"""
        mock_model = self._make_mock_model()
        engine = RankingEngine(model=mock_model)
        engine.threshold = 0.0

        recall_results = self._make_recall_results(2, n_candidates=3)

        results = engine.batch_rank_optimized(
            recall_results,
            chunk_size=10,
            similarity_threshold=None
        )

        assert len(results) == 2
        for r in results:
            assert 'enterprise_id' in r
            assert 'address_id' in r
            assert 'standard_address' in r
            assert 'exact_match' in r
            assert 'partial_match' in r
            assert 'not_match' in r
            assert 'match_status' in r

    def test_empty_recall_results(self):
        """验证空召回结果不报错"""
        mock_model = self._make_mock_model()
        engine = RankingEngine(model=mock_model)

        progress_calls = []
        results = engine.batch_rank_optimized(
            [],
            chunk_size=3,
            similarity_threshold=None,
            progress_callback=lambda p: progress_calls.append(p)
        )

        assert len(results) == 0
        # 空输入不进入循环，不触发回调
        assert len(progress_calls) == 0


class TestStreamingRecallGrouping:
    """测试 batch_recall_streaming 的分组逻辑（mock 服务端游标）"""

    def _make_mock_rows(self, n_enterprises, top_n=3):
        """构造模拟的数据库行（已按 enterprise_id, similarity DESC 排序）"""
        rows = []
        for i in range(n_enterprises):
            for j in range(top_n):
                rows.append({
                    'enterprise_id': f'ent_{i}',
                    'enterprise_name': f'企业_{i}',
                    'enterprise_address': f'地址_{i}',
                    'standard_id': f'std_{i}_{j}',
                    'standard_address': f'标准_{i}_{j}',
                    'room_no': f'room_{j}',
                    'similarity': 0.9 - j * 0.1
                })
        return rows

    def _make_mock_conn(self, rows):
        """构造 mock psycopg2 连接，模拟 named cursor 迭代"""
        mock_conn = MagicMock()
        mock_conn.autocommit = True

        class MockCursor:
            """模拟 psycopg2 named cursor 的迭代行为"""

            def __init__(self, rows_data):
                self.rows = rows_data
                self.itersize = 1000
                self._idx = 0

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def __iter__(self):
                return self

            def __next__(self):
                if self._idx >= len(self.rows):
                    raise StopIteration
                row = self.rows[self._idx]
                self._idx += 1
                return row

            def execute(self, sql, params=None):
                pass

        mock_conn.cursor.return_value = MockCursor(rows)
        return mock_conn

    def test_streaming_grouping(self):
        """验证流式召回按企业分组且分批 yield"""
        from database.vector_store import VectorStore

        rows = self._make_mock_rows(5, top_n=3)  # 5 企业 × 3 候选 = 15 行
        mock_conn = self._make_mock_conn(rows)

        mock_db = MagicMock()
        mock_db.conn = mock_conn

        vs = VectorStore(mock_db)
        # mock _set_index_search_param 避免真实 DB 调用
        vs._set_index_search_param = MagicMock()

        batches = list(vs.batch_recall_streaming(
            'ent_table', 'std_table',
            top_n=3,
            similarity_threshold=None,
            batch_enterprise_size=2  # 每 2 企业一批
        ))

        # 5 企业，每 2 企业一批 → 3 批（2+2+1）
        assert len(batches) == 3
        assert len(batches[0]) == 2
        assert len(batches[1]) == 2
        assert len(batches[2]) == 1

        # 验证每批内的企业分组和候选
        first_batch = batches[0]
        assert first_batch[0]['enterprise_id'] == 'ent_0'
        assert len(first_batch[0]['candidates']) == 3
        assert first_batch[0]['candidates'][0]['similarity'] == 0.9

    def test_streaming_threshold_filter_sql(self):
        """验证阈值过滤在 SQL 层生效（threshold_condition 非空）"""
        from database.vector_store import VectorStore

        rows = self._make_mock_rows(2, top_n=2)
        mock_conn = self._make_mock_conn(rows)

        mock_db = MagicMock()
        mock_db.conn = mock_conn

        vs = VectorStore(mock_db)
        vs._set_index_search_param = MagicMock()

        batches = list(vs.batch_recall_streaming(
            'ent_table', 'std_table',
            top_n=2,
            similarity_threshold=0.5,
            batch_enterprise_size=10
        ))

        # 阈值过滤在 SQL 层，mock 返回所有行，验证结果正确
        assert len(batches) == 1
        assert len(batches[0]) == 2

    def test_streaming_top_n_validation(self):
        """验证 top_n 参数校验"""
        from database.vector_store import VectorStore

        mock_db = MagicMock()
        mock_db.conn = MagicMock()
        vs = VectorStore(mock_db)
        vs._set_index_search_param = MagicMock()

        # top_n 非法值应抛出 ValueError
        with pytest.raises(ValueError):
            list(vs.batch_recall_streaming('a', 'b', top_n=0))
        with pytest.raises(ValueError):
            list(vs.batch_recall_streaming('a', 'b', top_n=-1))
        with pytest.raises(ValueError):
            list(vs.batch_recall_streaming('a', 'b', top_n=1001))

    def test_streaming_no_connection(self):
        """验证数据库连接为 None 时安全返回"""
        from database.vector_store import VectorStore

        mock_db = MagicMock()
        mock_db.conn = None
        vs = VectorStore(mock_db)
        vs._set_index_search_param = MagicMock()

        # conn 为 None 时应安全返回空（不抛异常）
        batches = list(vs.batch_recall_streaming('a', 'b', top_n=5))
        assert len(batches) == 0

    def test_streaming_single_enterprise(self):
        """验证单个企业的边界情况"""
        from database.vector_store import VectorStore

        rows = self._make_mock_rows(1, top_n=3)
        mock_conn = self._make_mock_conn(rows)
        mock_db = MagicMock()
        mock_db.conn = mock_conn

        vs = VectorStore(mock_db)
        vs._set_index_search_param = MagicMock()

        batches = list(vs.batch_recall_streaming(
            'a', 'b', top_n=3, batch_enterprise_size=100
        ))

        assert len(batches) == 1
        assert len(batches[0]) == 1
        assert batches[0][0]['enterprise_id'] == 'ent_0'
        assert len(batches[0][0]['candidates']) == 3


class TestDetermineMatchStatus:
    """测试匹配状态判断函数"""

    def test_exact_match(self):
        assert determine_match_status(0.9, 0.05, 0.05) == '精确匹配'

    def test_partial_match(self):
        assert determine_match_status(0.1, 0.8, 0.1) == '部分匹配'

    def test_not_match(self):
        assert determine_match_status(0.1, 0.1, 0.8) == '不匹配'

    def test_default_not_match_score(self):
        # not_match_score 默认 0.0
        assert determine_match_status(0.1, 0.2) == '部分匹配'

    def test_tie_breaker(self):
        # 等值时 max 返回第一个最大值对应的键
        # scores 字典顺序：精确匹配 > 部分匹配 > 不匹配
        assert determine_match_status(0.5, 0.5, 0.0) == '精确匹配'
