"""
匹配工具函数模块
================

集中定义匹配相关的公共工具函数，消除 ranking.py 和 mgeo_similarity.py 中的重复逻辑。
"""


def determine_match_status(exact_match, partial_match, not_match=None, round_scores=True):
    """
    根据 exact_match、partial_match、not_match 三个概率值判断匹配状态

    判断逻辑：三个概率值中最大的对应的标签作为匹配状态：
        - exact_match 最大 → '精确匹配'
        - partial_match 最大 → '部分匹配'
        - not_match 最大 → '不匹配'

    本函数统一了 ranking.py 和 mgeo_similarity.py 中两处重复的实现。
    - ranking.py 原实现：不 round，直接比较原始概率
    - mgeo_similarity.py 原实现：先 round(2) 再比较
    通过 round_scores 参数控制，保持各自原行为。

    Args:
        exact_match: 精确匹配概率
        partial_match: 部分匹配概率
        not_match: 不匹配概率（可选，不传时默认 0.0）
        round_scores: 是否四舍五入保留两位小数后再比较（默认 True）

    Returns:
        str: 匹配状态（'精确匹配' / '部分匹配' / '不匹配'）
    """
    if not_match is None:
        not_match = 0.0

    if round_scores:
        scores = {
            '精确匹配': round(exact_match, 2),
            '部分匹配': round(partial_match, 2),
            '不匹配': round(not_match, 2)
        }
    else:
        scores = {
            '精确匹配': exact_match,
            '部分匹配': partial_match,
            '不匹配': not_match
        }
    return max(scores, key=scores.get)
