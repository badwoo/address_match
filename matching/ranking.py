"""
精排引擎模块
============

使用阿里MGeo地址相似度匹配模型对召回结果进行精准排序。

核心功能：
    1. 单条地址匹配 - 对单个查询地址和候选地址进行相似度计算
    2. 批量地址匹配 - 对多个查询地址进行批量精排

匹配逻辑：
    - MGeo模型返回三个概率: exact_match, not_match, partial_match
    - 候选排序：按 exact_match 最大值筛选，相同时取 not_match 最小的候选
    - match_status 判断: exact_match、partial_match、not_match 三者中数值最大的决定状态
      - exact_match 最大 → '精确匹配'
      - partial_match 最大 → '部分匹配'
      - not_match 最大 → '不匹配'
    - 如果无候选，match_status = '不匹配'
"""

from config import Config
from model.mgeo_model import MGeoModel
from utils.logger import logger


def determine_match_status(exact_match_score, partial_match_score, not_match_score=None):
    """
    根据exact_match、partial_match、not_match分数判断匹配状态

    判断逻辑：
        取三个分数中最大值对应的标签作为匹配状态：
        - exact_match最大 → '精确匹配'
        - partial_match最大 → '部分匹配'
        - not_match最大 → '不匹配'

    Args:
        exact_match_score: 精确匹配概率
        partial_match_score: 部分匹配概率
        not_match_score: 不匹配概率（可选，不传时默认0.0）

    Returns:
        str: 匹配状态（精确匹配/部分匹配/不匹配）
    """
    if not_match_score is None:
        not_match_score = 0.0

    scores = {
        '精确匹配': exact_match_score,
        '部分匹配': partial_match_score,
        '不匹配': not_match_score
    }
    return max(scores, key=scores.get)


class RankingEngine:
    """
    精排引擎
    
    使用MGeo模型对召回的候选地址进行精准排序。
    
    Attributes:
        model: MGeoModel 对象
        threshold: 相似度阈值
    """
    
    def __init__(self, device=None):
        """
        初始化精排引擎
        
        Args:
            device: 运行设备 ('cuda' 或 'cpu')
        """
        device = device or Config.DEVICE
        self.model = MGeoModel(device=device)
        self.threshold = Config.SIMILARITY_THRESHOLD
    
    def rank(self, query_address, candidates):
        """
        对单个查询地址进行精排

        筛选逻辑：
            1. 先按相似度阈值过滤低分候选
            2. 按 exact_match 最大值筛选最佳匹配候选，相同时取 not_match 最小的候选

        Args:
            query_address: 查询地址
            candidates: 候选地址列表

        Returns:
            dict: 最佳匹配结果，包含 address_id, standard_address, exact_match, partial_match, not_match, match_status
        """
        if not candidates:
            return None

        if self.threshold is not None and self.threshold > 0:
            candidates = [
                c for c in candidates
                if c.get('similarity', 1.0) >= self.threshold
            ]

        if not candidates:
            return None

        pairs = [(query_address, candidate['address']) for candidate in candidates]
        predictions = self.model.predict(pairs)

        best_score = -1.0
        best_not_match = float('inf')
        best_idx = -1

        for i, pred in enumerate(predictions):
            score = pred['exact_match']
            not_match = pred['not_match']
            if score > best_score or (score == best_score and not_match < best_not_match):
                best_score = score
                best_not_match = not_match
                best_idx = i

        pred = predictions[best_idx]
        return {
            'address_id': candidates[best_idx]['source_id'],
            'standard_address': candidates[best_idx]['address'],
            'exact_match': pred['exact_match'],
            'partial_match': pred['partial_match'],
            'not_match': pred['not_match'],
            'match_status': determine_match_status(pred['exact_match'], pred['partial_match'], pred['not_match'])
        }
    
    def batch_rank(self, query_addresses, candidates_list):
        """
        批量精排
        
        Args:
            query_addresses: 查询地址列表
            candidates_list: 候选地址列表（每个元素包含 candidates 字段）
        
        Returns:
            list: 匹配结果列表
        """
        results = []
        
        for i, query_address in enumerate(query_addresses):
            candidates = candidates_list[i]['candidates'] if i < len(candidates_list) else []
            result = self.rank(query_address, candidates)
            
            if result:
                results.append({
                    'query_address': query_address,
                    **result
                })
            else:
                results.append({
                    'query_address': query_address,
                    'address_id': None,
                    'standard_address': None,
                    'exact_match': 0.0,
                    'partial_match': 0.0,
                    'not_match': 1.0,
                    'match_status': '不匹配'
                })
        
        return results
    
    def batch_rank_optimized(self, recall_results, batch_size=1000, similarity_threshold=None, chunk_size=5000):
        """
        优化的批量精排方法（用于两阶段匹配流程）
        
        分块处理企业的候选地址，避免一次性加载所有地址对导致OOM。
        每处理 chunk_size 个企业的地址对后，立即送入模型预测并释放内存，
        然后再处理下一批企业。
        
        Args:
            recall_results: 召回结果列表，每个元素包含 enterprise_id, enterprise_address, candidates
            batch_size: 批次大小，控制每次预测的地址对数量
            similarity_threshold: 相似度阈值（0-1），候选地址的向量相似度低于此阈值将被过滤，None表示不过滤
            chunk_size: 每次处理的企业数量，控制内存占用上限。
                        例如 chunk_size=5000, 每个企业50个候选 = 25万对，远小于全部加载的7500万对
        
        Returns:
            list: 匹配结果列表
        """
        threshold = similarity_threshold if similarity_threshold is not None else self.threshold
        total = len(recall_results)
        
        final_results = [None] * total
        
        for chunk_start in range(0, total, chunk_size):
            chunk_end = min(chunk_start + chunk_size, total)
            chunk_items = recall_results[chunk_start:chunk_end]
            
            chunk_pairs = []
            chunk_pair_index_map = []
            
            for idx, recall_item in enumerate(chunk_items):
                enterprise_addr = recall_item['enterprise_address']
                candidates = recall_item.get('candidates', [])
                
                if not candidates:
                    chunk_pair_index_map.append(None)
                    continue
                
                filtered_candidates = candidates
                if threshold is not None and threshold > 0:
                    filtered_candidates = [
                        c for c in candidates
                        if c.get('similarity', 1.0) >= threshold
                    ]
                
                if not filtered_candidates:
                    chunk_pair_index_map.append(None)
                    continue
                
                start_idx = len(chunk_pairs)
                for candidate in filtered_candidates:
                    chunk_pairs.append((enterprise_addr, candidate['address']))
                end_idx = len(chunk_pairs)
                
                chunk_pair_index_map.append((start_idx, end_idx, filtered_candidates))
            
            if not chunk_pairs:
                for idx in range(len(chunk_items)):
                    recall_item = chunk_items[idx]
                    final_results[chunk_start + idx] = {
                        'enterprise_id': recall_item['enterprise_id'],
                        'enterprise_name': recall_item.get('enterprise_name', ''),
                        'enterprise_address': recall_item['enterprise_address'],
                        'address_id': None,
                        'standard_address': None,
                        'room_no': '',
                        'exact_match': 0.0,
                        'partial_match': 0.0,
                        'not_match': 1.0,
                        'match_status': '不匹配'
                    }
                continue
            
            predictions = self.model.predict_optimized(chunk_pairs, batch_size=batch_size)
            
            for idx, recall_item in enumerate(chunk_items):
                mapping = chunk_pair_index_map[idx]
                global_idx = chunk_start + idx
                
                if mapping is None:
                    final_results[global_idx] = {
                        'enterprise_id': recall_item['enterprise_id'],
                        'enterprise_name': recall_item.get('enterprise_name', ''),
                        'enterprise_address': recall_item['enterprise_address'],
                        'address_id': None,
                        'standard_address': None,
                        'room_no': '',
                        'exact_match': 0.0,
                        'partial_match': 0.0,
                        'not_match': 1.0,
                        'match_status': '不匹配'
                    }
                    continue
                
                start_idx, end_idx, candidates = mapping
                enterprise_predictions = predictions[start_idx:end_idx]
                
                best_score = -1.0
                best_not_match = float('inf')
                best_idx = -1
                
                for i, pred in enumerate(enterprise_predictions):
                    score = pred['exact_match']
                    not_match = pred['not_match']
                    if score > best_score or (score == best_score and not_match < best_not_match):
                        best_score = score
                        best_not_match = not_match
                        best_idx = i
                
                best_pred = enterprise_predictions[best_idx]
                best_candidate = candidates[best_idx]
                
                match_status = determine_match_status(
                    best_pred['exact_match'],
                    best_pred['partial_match'],
                    best_pred['not_match']
                )
                
                final_results[global_idx] = {
                    'enterprise_id': recall_item['enterprise_id'],
                    'enterprise_name': recall_item.get('enterprise_name', ''),
                    'enterprise_address': recall_item['enterprise_address'],
                    'address_id': best_candidate['source_id'],
                    'standard_address': best_candidate['address'],
                    'room_no': best_candidate.get('room_no', ''),
                    'exact_match': best_pred['exact_match'],
                    'partial_match': best_pred['partial_match'],
                    'not_match': best_pred['not_match'],
                    'match_status': match_status
                }
            
            logger.info(f"精排进度: {chunk_end}/{total} 企业已完成 (本块 {len(chunk_pairs)} 对地址)")
        
        return final_results
