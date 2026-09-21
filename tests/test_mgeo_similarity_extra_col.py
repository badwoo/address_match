"""验证MGeo地址相似度匹配支持其他附加字段（extra_col）"""
import sys
import os
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from matching.mgeo_similarity import MGeoSimilarityMatcher


class TestMGeoSimilarityExtraCol(unittest.TestCase):
    """测试MGeo相似度匹配对 extra_col 附加字段的支持"""

    def _create_mock_matcher(self):
        """构造已加载mock模型的匹配器"""
        matcher = MGeoSimilarityMatcher(device='cpu')
        matcher.model = MagicMock()
        matcher.model.predict_optimized = MagicMock(return_value=[
            {'exact_match': 0.9, 'partial_match': 0.08, 'not_match': 0.02},
            {'exact_match': 0.1, 'partial_match': 0.2, 'not_match': 0.7},
        ])
        return matcher

    def test_build_result_includes_extra_col(self):
        """_build_result 应保留 extra_col 值"""
        matcher = self._create_mock_matcher()
        pred = {'exact_match': 0.9, 'partial_match': 0.08, 'not_match': 0.02}
        result = matcher._build_result('addr_a', 'addr_b', 'id_1', pred, extra_value='extra_val')

        self.assertEqual(result['address_a'], 'addr_a')
        self.assertEqual(result['address_b'], 'addr_b')
        self.assertEqual(result['identifier'], 'id_1')
        self.assertEqual(result['extra_col'], 'extra_val')
        self.assertEqual(result['match_status'], '精确匹配')

    def test_build_empty_result_without_extra_col(self):
        """_build_empty_result 不传 extra_col 时应为 None"""
        matcher = self._create_mock_matcher()
        result = matcher._build_empty_result('addr_a', 'addr_b', 'id_1')

        self.assertIsNone(result['extra_col'])
        self.assertEqual(result['match_status'], '不匹配')

    def test_match_from_dataframe_with_extra_col(self):
        """DataFrame 输入时，extra_col 应正确附加到匹配结果"""
        matcher = self._create_mock_matcher()
        df = pd.DataFrame({
            'addr_a': ['浙江省杭州市西湖区文三路478号', '北京市朝阳区建国路88号'],
            'addr_b': ['浙江省杭州市西湖区文三路478号华星创业大厦', '上海市浦东新区陆家嘴环路1000号'],
            'id': ['A001', 'A002'],
            'extra': ['附加信息1', '附加信息2']
        })

        with patch.object(matcher, '_load_model', return_value=True):
            results = matcher.match_from_dataframe(
                df, 'addr_a', 'addr_b', id_col='id', extra_col='extra'
            )

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]['identifier'], 'A001')
        self.assertEqual(results[0]['extra_col'], '附加信息1')
        self.assertEqual(results[0]['match_status'], '精确匹配')

        self.assertEqual(results[1]['identifier'], 'A002')
        self.assertEqual(results[1]['extra_col'], '附加信息2')
        self.assertEqual(results[1]['match_status'], '不匹配')

    def test_match_from_dataframe_without_extra_col(self):
        """未选择 extra_col 时，结果中 extra_col 应为 None"""
        matcher = self._create_mock_matcher()
        df = pd.DataFrame({
            'addr_a': ['浙江省杭州市西湖区文三路478号'],
            'addr_b': ['浙江省杭州市西湖区文三路478号华星创业大厦'],
            'id': ['A001']
        })

        with patch.object(matcher, '_load_model', return_value=True):
            results = matcher.match_from_dataframe(
                df, 'addr_a', 'addr_b', id_col='id', extra_col=None
            )

        self.assertEqual(len(results), 1)
        self.assertIsNone(results[0]['extra_col'])


if __name__ == '__main__':
    unittest.main()
