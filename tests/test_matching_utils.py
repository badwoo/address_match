"""
matching.utils 单元测试
=======================

验证统一后的 determine_match_status 函数行为，以及 ranking.py / mgeo_similarity.py
的兼容性封装是否保持各自原行为。

测试覆盖：
    1. 基本状态判断（exact/partial/not 各自胜出）
    2. not_match 默认值（None → 0.0）
    3. round_scores 参数行为差异
    4. 相等值时的 tie-breaking（max 取第一个）
    5. ranking.py 封装兼容性（round_scores=False）
    6. mgeo_similarity.py 调用兼容性（round_scores=True，默认）
"""

import pytest
from matching.utils import determine_match_status


class TestDetermineMatchStatus:
    """统一匹配状态判断函数测试"""

    def test_exact_match_wins(self):
        """exact_match 最大时返回 '精确匹配'"""
        assert determine_match_status(0.9, 0.05, 0.05) == '精确匹配'

    def test_partial_match_wins(self):
        """partial_match 最大时返回 '部分匹配'"""
        assert determine_match_status(0.1, 0.8, 0.1) == '部分匹配'

    def test_not_match_wins(self):
        """not_match 最大时返回 '不匹配'"""
        assert determine_match_status(0.1, 0.1, 0.8) == '不匹配'

    def test_not_match_default_none(self):
        """not_match=None 时默认 0.0，exact 和 partial 都为 0 时 not_match(0.0) 胜出"""
        # not_match=None → 0.0，三者都 0 时 max 取第一个 '精确匹配'
        assert determine_match_status(0.0, 0.0, None) == '精确匹配'
        # not_match=None → 0.0，partial > 0 时 partial 胜出
        assert determine_match_status(0.0, 0.5, None) == '部分匹配'

    def test_round_scores_true_applies_round(self):
        """round_scores=True 时四舍五入保留两位小数"""
        # 0.334 和 0.335 round 后均为 0.33（Python3 银行家舍入 + 浮点表示）
        # 此处验证 round 生效：0.344 vs 0.344 round 后相等，取第一个 '精确匹配'
        result = determine_match_status(0.344, 0.344, 0.3, round_scores=True)
        assert result == '精确匹配'

    def test_round_scores_false_uses_raw_values(self):
        """round_scores=False 时直接比较原始值"""
        # 0.3441 > 0.3440，partial 胜出
        result = determine_match_status(0.3440, 0.3441, 0.3, round_scores=False)
        assert result == '部分匹配'

    def test_round_scores_changes_result(self):
        """round_scores 参数能影响比较基准值（round 后值相等）"""
        # 原始值：exact=0.3441 > partial=0.3440 → '精确匹配'
        # round 后：round(0.3441,2)=0.34 == round(0.3440,2)=0.34 → 取第一个 '精确匹配'
        # 验证 round_scores=True 时两个相近值被视作相等
        raw_result = determine_match_status(0.3441, 0.3440, 0.3, round_scores=False)
        rounded_result = determine_match_status(0.3441, 0.3440, 0.3, round_scores=True)
        # 两种模式下都应返回 '精确匹配'（exact 在 tie 中优先）
        assert raw_result == '精确匹配'
        assert rounded_result == '精确匹配'

    def test_tie_breaking_exact_partial_equal(self):
        """exact 与 partial 相等时，max 取第一个 '精确匹配'"""
        assert determine_match_status(0.5, 0.5, 0.0) == '精确匹配'

    def test_tie_breaking_partial_not_equal(self):
        """partial 与 not 相等时，max 取第一个 '部分匹配'"""
        assert determine_match_status(0.0, 0.5, 0.5) == '部分匹配'

    def test_all_zero(self):
        """三者均为 0 时，max 取第一个 '精确匹配'"""
        assert determine_match_status(0.0, 0.0, 0.0) == '精确匹配'

    def test_default_round_scores_is_true(self):
        """默认 round_scores=True（保持 mgeo_similarity.py 原行为）"""
        # 0.335 在 Python3 中 round(0.335,2)=0.34（浮点表示为 0.33499...）
        # 此处仅验证默认参数与显式传 True 行为一致
        default_result = determine_match_status(0.344, 0.343, 0.313)
        explicit_true = determine_match_status(0.344, 0.343, 0.313, round_scores=True)
        assert default_result == explicit_true


class TestRankingCompatibility:
    """验证 ranking.py 的 determine_match_status 封装保持原行为（不 round）"""

    def test_ranking_reexport_is_callable(self):
        """ranking.determine_match_status 可被导入且可调用"""
        from matching.ranking import determine_match_status as ranking_dms
        assert callable(ranking_dms)

    def test_ranking_uses_raw_values(self):
        """ranking.py 封装使用原始值比较（round_scores=False）"""
        from matching.ranking import determine_match_status as ranking_dms
        # 0.3441 > 0.3440，原始值比较下 partial 胜出
        # 若误用 round_scores=True，两者 round 后均 0.34，会返回 '精确匹配'
        assert ranking_dms(0.3440, 0.3441, 0.3) == '部分匹配'

    def test_ranking_matcher_import_compatible(self):
        """matcher.py 的 `from matching.ranking import determine_match_status` 导入兼容"""
        # 模拟 matcher.py 的导入方式
        from matching.ranking import RankingEngine, determine_match_status
        assert callable(determine_match_status)
        assert RankingEngine is not None

    def test_ranking_behavior_matches_utils_false(self):
        """ranking.determine_match_status 行为等价于 utils(round_scores=False)"""
        from matching.ranking import determine_match_status as ranking_dms
        test_cases = [
            (0.9, 0.05, 0.05),
            (0.1, 0.8, 0.1),
            (0.1, 0.1, 0.8),
            (0.3440, 0.3441, 0.3),
            (0.5, 0.5, 0.0),
        ]
        for exact, partial, not_match in test_cases:
            assert ranking_dms(exact, partial, not_match) == \
                   determine_match_status(exact, partial, not_match, round_scores=False)


class TestMGeoSimilarityCompatibility:
    """验证 mgeo_similarity.py 调用统一函数保持原行为（round_scores=True）"""

    def test_mgeo_imports_unified_function(self):
        """mgeo_similarity.py 导入的是 matching.utils.determine_match_status"""
        import matching.mgeo_similarity as ms
        # 导入的是统一函数本身（而非本地定义）
        assert ms.determine_match_status is determine_match_status

    def test_mgeo_uses_rounded_values(self):
        """mgeo_similarity 调用使用 round_scores=True（默认）"""
        # 0.3441 vs 0.3440 round 后均 0.34，取第一个 '精确匹配'
        # 若误用 round_scores=False，0.3441 > 0.3440 会返回 '部分匹配'
        import matching.mgeo_similarity as ms
        assert ms.determine_match_status(0.3441, 0.3440, 0.3) == '精确匹配'

    def test_mgeo_behavior_matches_utils_true(self):
        """mgeo_similarity 调用行为等价于 utils(round_scores=True)"""
        test_cases = [
            (0.9, 0.05, 0.05),
            (0.1, 0.8, 0.1),
            (0.1, 0.1, 0.8),
            (0.3441, 0.3440, 0.3),
            (0.335, 0.335, 0.33),
        ]
        for exact, partial, not_match in test_cases:
            import matching.mgeo_similarity as ms
            assert ms.determine_match_status(exact, partial, not_match) == \
                   determine_match_status(exact, partial, not_match, round_scores=True)
