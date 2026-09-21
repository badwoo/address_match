"""
MGeo精排端到端测试
==================

测试流程：
1. 连接数据库
2. 检查粗召回结果表是否存在且有数据
3. 加载前5个企业的召回结果
4. 加载MGeo模型
5. 对前5个企业执行精排预测
6. 验证返回结果的3个分数是否合理
7. 验证排序规则
8. 验证match_status判断
9. 将精排结果写入数据库，然后读回验证字段对应是否正确

如果粗召回结果表不存在或为空，跳过测试
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import torch
from database.connection import DBConnection
from database.data_loader import DataLoader
from app_common import get_cached_mgeo_model
from matching.ranking import determine_match_status, RankingEngine
from utils.pinyin_utils import tag_to_prefix, get_tag_tables


# ==================== 测试配置 ====================
DB_CONFIG = {
    'host': 'localhost',
    'port': 5432,
    'dbname': 'prj_sj_db',
    'user': 'sj',
    'password': '123456',
    'schema': 'ai'
}
TAG_NAME = '坪山_其他'
TEST_ENTERPRISE_COUNT = 5


@pytest.fixture(scope='module')
def db_conn():
    """建立数据库连接（模块级共享）"""
    conn = DBConnection(**DB_CONFIG)
    assert conn.connect(), "数据库连接失败"
    yield conn
    conn.close()


@pytest.fixture(scope='module')
def data_loader(db_conn):
    """创建DataLoader实例"""
    return DataLoader(db_conn)


@pytest.fixture(scope='module')
def tag_tables():
    """获取标签对应的表名"""
    prefix = tag_to_prefix(TAG_NAME)
    recall_table, match_table = get_tag_tables(prefix)
    return {
        'prefix': prefix,
        'recall_table': recall_table,
        'match_table': match_table
    }


@pytest.fixture(scope='module')
def mgeo_model():
    """加载MGeo模型（模块级共享，只加载一次）"""
    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    model = get_cached_mgeo_model(device)
    assert model is not None, "MGeo模型加载失败"
    return model


class TestRankingE2E:
    """MGeo精排端到端测试"""

    def test_01_tag_tables_naming(self, tag_tables):
        """验证标签对应的表名生成正确"""
        # "坪山_其他" → pypinyin逐字转拼音 + 下划线保留 → pingshan_qita
        assert tag_tables['prefix'] == 'pingshan_qita'
        assert tag_tables['recall_table'] == 'pingshan_qita_recall_results'
        assert tag_tables['match_table'] == 'pingshan_qita_match_results'

    def test_02_recall_table_exists(self, db_conn, tag_tables):
        """检查粗召回结果表是否存在"""
        exists = db_conn.table_exists(tag_tables['recall_table'])
        if not exists:
            pytest.skip(f"粗召回结果表 {tag_tables['recall_table']} 不存在，跳过测试")

    def test_03_recall_table_has_data(self, db_conn, data_loader, tag_tables):
        """检查粗召回结果表是否有数据"""
        count = data_loader.get_total_count(tag_tables['recall_table'])
        if count == 0:
            pytest.skip(f"粗召回结果表 {tag_tables['recall_table']} 为空，跳过测试")
        print(f"\n粗召回结果表共 {count} 条记录")

    def test_04_load_recall_results(self, data_loader, tag_tables):
        """加载前5个企业的召回结果"""
        # 加载全部召回结果，然后取前5个企业
        all_results = data_loader.load_recall_results(tag_tables['recall_table'])
        assert len(all_results) > 0, "加载召回结果为空"

        # 取前5个企业
        self.__class__.recall_results = all_results[:TEST_ENTERPRISE_COUNT]
        print(f"\n加载了 {len(all_results)} 个企业的召回结果，取前 {len(self.__class__.recall_results)} 个企业测试")

        for item in self.__class__.recall_results:
            print(f"  企业ID={item['enterprise_id']}, 候选数={len(item['candidates'])}")

    def test_05_mgeo_model_loaded(self, mgeo_model):
        """验证MGeo模型加载成功"""
        assert mgeo_model.model is not None, "模型对象为空"
        assert mgeo_model.tokenizer is not None, "分词器为空"
        print(f"\nMGeo模型加载成功, device={mgeo_model.device}, fp16={mgeo_model.use_fp16}")

    def test_06_predict_optimized(self, mgeo_model):
        """对前5个企业执行精排预测"""
        recall_results = self.__class__.recall_results
        assert len(recall_results) > 0, "无召回结果可预测"

        # 构建地址对
        all_pairs = []
        pair_index_map = []
        for item in recall_results:
            enterprise_addr = item['enterprise_address']
            candidates = item.get('candidates', [])
            start_idx = len(all_pairs)
            for candidate in candidates:
                all_pairs.append((enterprise_addr, candidate['address']))
            end_idx = len(all_pairs)
            pair_index_map.append((start_idx, end_idx))

        assert len(all_pairs) > 0, "无地址对可预测"
        print(f"\n共构建 {len(all_pairs)} 个地址对，开始精排预测...")

        # 执行预测
        predictions = mgeo_model.predict_optimized(all_pairs)
        assert len(predictions) == len(all_pairs), f"预测结果数量不匹配: 期望{len(all_pairs)}, 实际{len(predictions)}"

        # 保存预测结果供后续测试使用
        self.__class__.predictions = predictions
        self.__class__.pair_index_map = pair_index_map

        print(f"精排预测完成，共 {len(predictions)} 个结果")

    def test_07_scores_reasonable(self):
        """验证返回结果的3个分数是否合理（每个在0-1之间，三者之和约等于1）"""
        predictions = self.__class__.predictions
        assert len(predictions) > 0, "无预测结果可验证"

        for i, pred in enumerate(predictions):
            exact = pred['exact_match']
            partial = pred['partial_match']
            not_match = pred['not_match']

            # 每个分数在0-1之间
            assert 0.0 <= exact <= 1.0, f"预测{i}: exact_match={exact} 不在[0,1]范围"
            assert 0.0 <= partial <= 1.0, f"预测{i}: partial_match={partial} 不在[0,1]范围"
            assert 0.0 <= not_match <= 1.0, f"预测{i}: not_match={not_match} 不在[0,1]范围"

            # 三者之和约等于1（允许浮点误差）
            total = exact + partial + not_match
            assert abs(total - 1.0) < 0.01, f"预测{i}: 三分数之和={total}，偏离1.0过多"

        print(f"\n验证 {len(predictions)} 个预测结果的分数合理性：全部通过")

    def test_08_ranking_order(self):
        """验证排序规则：四舍五入后 exact_match 降序 → partial_match 降序 → not_match 升序"""
        recall_results = self.__class__.recall_results
        predictions = self.__class__.predictions
        pair_index_map = self.__class__.pair_index_map

        for ent_idx, item in enumerate(recall_results):
            start_idx, end_idx = pair_index_map[ent_idx]
            enterprise_preds = predictions[start_idx:end_idx]
            candidates = item['candidates']

            if len(enterprise_preds) <= 1:
                continue

            # 使用与 RankingEngine 相同的排序逻辑选出最佳候选
            best_exact = -1.0
            best_partial = -1.0
            best_not = float('inf')
            best_idx = -1

            for i, pred in enumerate(enterprise_preds):
                r_exact = round(pred['exact_match'], 2)
                r_partial = round(pred['partial_match'], 2)
                r_not = round(pred['not_match'], 2)
                if (r_exact > best_exact or
                    (r_exact == best_exact and r_partial > best_partial) or
                    (r_exact == best_exact and r_partial == best_partial and r_not < best_not)):
                    best_exact = r_exact
                    best_partial = r_partial
                    best_not = r_not
                    best_idx = i

            # 验证 best_idx 是有效的
            assert 0 <= best_idx < len(enterprise_preds), f"企业{ent_idx}: best_idx={best_idx} 越界"

            # 验证排序规则：best_idx 对应的候选在四舍五入后确实是最优的
            best_pred = enterprise_preds[best_idx]
            for i, pred in enumerate(enterprise_preds):
                if i == best_idx:
                    continue
                r_best_exact = round(best_pred['exact_match'], 2)
                r_pred_exact = round(pred['exact_match'], 2)
                r_best_partial = round(best_pred['partial_match'], 2)
                r_pred_partial = round(pred['partial_match'], 2)
                r_best_not = round(best_pred['not_match'], 2)
                r_pred_not = round(pred['not_match'], 2)

                # best 应该 >= pred 按排序规则
                assert (r_best_exact > r_pred_exact or
                        (r_best_exact == r_pred_exact and r_best_partial > r_pred_partial) or
                        (r_best_exact == r_pred_exact and r_best_partial == r_pred_partial and r_best_not <= r_pred_not)), \
                    f"企业{ent_idx}: 排序规则违反，候选{i} 比最佳候选{best_idx} 更优"

        print(f"\n验证 {len(recall_results)} 个企业的排序规则：全部通过")

    def test_09_match_status(self):
        """验证match_status判断：哪个分数最大就对应哪个状态"""
        predictions = self.__class__.predictions

        for i, pred in enumerate(predictions):
            exact = pred['exact_match']
            partial = pred['partial_match']
            not_match = pred['not_match']

            expected_status = determine_match_status(exact, partial, not_match)

            # 验证哪个分数最大就对应哪个状态
            scores = {
                '精确匹配': exact,
                '部分匹配': partial,
                '不匹配': not_match
            }
            max_status = max(scores, key=scores.get)
            assert expected_status == max_status, \
                f"预测{i}: match_status={expected_status}，但最大分数对应的状态是{max_status} " \
                f"(exact={exact:.4f}, partial={partial:.4f}, not_match={not_match:.4f})"

        print(f"\n验证 {len(predictions)} 个预测结果的match_status判断：全部通过")

    def test_10_write_and_readback(self, db_conn, data_loader, tag_tables, mgeo_model):
        """将精排结果写入数据库，然后读回验证字段对应是否正确"""
        recall_results = self.__class__.recall_results
        predictions = self.__class__.predictions
        pair_index_map = self.__class__.pair_index_map

        # 使用 RankingEngine 的排序逻辑生成精排结果
        ranking_engine = RankingEngine(model=mgeo_model)
        # 不设阈值，避免过滤掉候选
        ranking_engine.threshold = None

        match_results = []
        for ent_idx, item in enumerate(recall_results):
            start_idx, end_idx = pair_index_map[ent_idx]
            enterprise_preds = predictions[start_idx:end_idx]
            candidates = item.get('candidates', [])

            if not candidates or not enterprise_preds:
                match_results.append({
                    'enterprise_id': item['enterprise_id'],
                    'enterprise_name': item.get('enterprise_name', ''),
                    'enterprise_address': item['enterprise_address'],
                    'address_id': None,
                    'standard_address': None,
                    'room_no': '',
                    'exact_match': 0.0,
                    'partial_match': 0.0,
                    'not_match': 1.0,
                    'match_status': '不匹配'
                })
                continue

            # 排序选出最佳候选
            best_exact = -1.0
            best_partial = -1.0
            best_not = float('inf')
            best_idx = -1

            for i, pred in enumerate(enterprise_preds):
                r_exact = round(pred['exact_match'], 2)
                r_partial = round(pred['partial_match'], 2)
                r_not = round(pred['not_match'], 2)
                if (r_exact > best_exact or
                    (r_exact == best_exact and r_partial > best_partial) or
                    (r_exact == best_exact and r_partial == best_partial and r_not < best_not)):
                    best_exact = r_exact
                    best_partial = r_partial
                    best_not = r_not
                    best_idx = i

            best_pred = enterprise_preds[best_idx]
            best_candidate = candidates[best_idx]

            match_status = determine_match_status(
                best_pred['exact_match'],
                best_pred['partial_match'],
                best_pred['not_match']
            )

            match_results.append({
                'enterprise_id': item['enterprise_id'],
                'enterprise_name': item.get('enterprise_name', ''),
                'enterprise_address': item['enterprise_address'],
                'address_id': best_candidate['source_id'],
                'standard_address': best_candidate['address'],
                'room_no': best_candidate.get('room_no', ''),
                'exact_match': best_pred['exact_match'],
                'partial_match': best_pred['partial_match'],
                'not_match': best_pred['not_match'],
                'match_status': match_status
            })

        # 确保匹配结果表存在
        match_table = tag_tables['match_table']
        data_loader.create_result_table(match_table)

        # 先删除这些企业的旧数据（避免旧数据干扰读回验证）
        from database.connection import quote_identifier
        enterprise_ids = [r['enterprise_id'] for r in match_results]
        del_placeholders = ','.join(['%s'] * len(enterprise_ids))
        del_sql = f"DELETE FROM {quote_identifier(match_table)} WHERE enterprise_id IN ({del_placeholders})"
        db_conn.execute(del_sql, tuple(enterprise_ids))
        db_conn.commit()

        # 写入精排结果
        inserted = data_loader.insert_match_results(match_results, table_name=match_table)
        assert inserted == len(match_results), f"写入记录数不匹配: 期望{len(match_results)}, 实际{inserted}"

        # 读回验证：查询刚写入的记录
        placeholders = ','.join(['%s'] * len(enterprise_ids))
        sql = f"""
            SELECT enterprise_id, enterprise_name, enterprise_address,
                   address_id, standard_address, room_no,
                   exact_match, partial_match, not_match, match_status
            FROM {quote_identifier(match_table)}
            WHERE enterprise_id IN ({placeholders})
            ORDER BY enterprise_id
        """
        cursor = db_conn.execute(sql, tuple(enterprise_ids))
        assert cursor is not None, "查询精排结果失败"
        readback_rows = cursor.fetchall()

        # 按企业ID建立字典便于比对
        readback_map = {row['enterprise_id']: row for row in readback_rows}

        for expected in match_results:
            eid = expected['enterprise_id']
            assert eid in readback_map, f"企业ID={eid} 未在回读结果中找到"
            actual = readback_map[eid]

            # 验证关键字段
            assert actual['enterprise_name'] == expected['enterprise_name'], \
                f"企业{eid}: enterprise_name 不匹配"
            assert actual['enterprise_address'] == expected['enterprise_address'], \
                f"企业{eid}: enterprise_address 不匹配"
            assert actual['address_id'] == str(expected['address_id']), \
                f"企业{eid}: address_id 不匹配, 期望={expected['address_id']}, 实际={actual['address_id']}"
            assert actual['standard_address'] == expected['standard_address'], \
                f"企业{eid}: standard_address 不匹配"
            assert actual['match_status'] == expected['match_status'], \
                f"企业{eid}: match_status 不匹配, 期望={expected['match_status']}, 实际={actual['match_status']}"

            # 验证分数（允许浮点误差）
            assert abs(float(actual['exact_match']) - expected['exact_match']) < 0.001, \
                f"企业{eid}: exact_match 不匹配, 期望={expected['exact_match']}, 实际={actual['exact_match']}"
            assert abs(float(actual['partial_match']) - expected['partial_match']) < 0.001, \
                f"企业{eid}: partial_match 不匹配, 期望={expected['partial_match']}, 实际={actual['partial_match']}"
            assert abs(float(actual['not_match']) - expected['not_match']) < 0.001, \
                f"企业{eid}: not_match 不匹配, 期望={expected['not_match']}, 实际={actual['not_match']}"

        # 清理：删除本次测试写入的记录
        delete_sql = f"""
            DELETE FROM {quote_identifier(match_table)}
            WHERE enterprise_id IN ({del_placeholders})
        """
        db_conn.execute(delete_sql, tuple(enterprise_ids))
        db_conn.commit()

        print(f"\n写入并回读验证 {len(match_results)} 条精排结果：全部通过")
        print("已清理本次测试写入的记录")
