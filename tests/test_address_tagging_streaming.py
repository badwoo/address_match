# -*- coding: utf-8 -*-
"""
地址结构化解析流式处理bug修复测试
================================

验证以下修复点：
1. parse_from_db_streaming 使用 ctid keyset pagination 替代 OFFSET 深分页
2. 数据库查询失败时抛 RuntimeError，不再静默 break 导致假完成
3. 结果写入失败时抛 RuntimeError
4. 用户停止时正常返回已处理数
5. 处理数不足总数时抛 RuntimeError
6. 副本表创建使用 LEFT JOIN LATERAL ... LIMIT 1 避免行数膨胀
7. 副本表保留源表全部字段（SELECT s.*）
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from unittest.mock import MagicMock

from matching.address_tagging import AddressTaggingParser


def _make_parser(mode='12'):
    """构造一个已预载 rule_engine 的 parser（跳过真实模型加载）"""
    parser = AddressTaggingParser(device='cpu', mode=mode)
    parser.rule_engine = MagicMock()
    parser.rule_engine.parse.return_value = []
    return parser


def _mock_cursor(rows=None, fetchone_result=None):
    """构造一个 mock cursor"""
    cursor = MagicMock()
    if rows is not None:
        cursor.fetchall.return_value = rows
    if fetchone_result is not None:
        cursor.fetchone.return_value = fetchone_result
    return cursor


class TestStreamingKeysetPagination:
    """验证 parse_from_db_streaming 使用 ctid keyset pagination"""

    def test_first_batch_no_offset(self):
        """第一批查询应使用 ORDER BY ctid LIMIT（无OFFSET深分页）"""
        parser = _make_parser('12')
        parser.rule_engine.parse.return_value = [{'original_address': 'a', 'province': ''}]

        count_cursor = _mock_cursor(fetchone_result={'count': 1})
        select_cursor = _mock_cursor(rows=[{'ctid': '(0,1)', 'address': 'a'}])
        db_conn = MagicMock()
        db_conn.execute.side_effect = [count_cursor, select_cursor]

        data_loader = MagicMock()
        data_loader.insert_address_tagging_results.return_value = 1

        parser.parse_from_db_streaming(
            db_conn=db_conn, table_name='t', address_col='address',
            result_table_name='r', data_loader=data_loader, db_batch_size=10
        )

        # 第2次execute是SELECT，检查SQL不含OFFSET
        select_sql = db_conn.execute.call_args_list[1][0][0]
        assert 'ORDER BY ctid' in select_sql
        assert 'OFFSET' not in select_sql

    def test_subsequent_batches_use_ctid_cursor(self):
        """后续批次应使用 WHERE ctid > %s::tid 游标分页"""
        parser = _make_parser('12')
        parser.rule_engine.parse.return_value = [{'original_address': 'a', 'province': ''}]

        count_cursor = _mock_cursor(fetchone_result={'count': 2})
        batch1_cursor = _mock_cursor(rows=[{'ctid': '(0,1)', 'address': 'a'}])
        batch2_cursor = _mock_cursor(rows=[{'ctid': '(0,2)', 'address': 'b'}])
        db_conn = MagicMock()
        db_conn.execute.side_effect = [count_cursor, batch1_cursor, batch2_cursor]

        data_loader = MagicMock()
        data_loader.insert_address_tagging_results.return_value = 1

        result = parser.parse_from_db_streaming(
            db_conn=db_conn, table_name='t', address_col='address',
            result_table_name='r', data_loader=data_loader, db_batch_size=1
        )

        assert result == 2
        # 第3次execute是第二批SELECT，检查SQL包含 ctid > %s::tid
        batch2_call = db_conn.execute.call_args_list[2]
        batch2_sql = batch2_call[0][0]
        assert 'ctid > %s::tid' in batch2_sql
        # 检查参数传入的是上一批最后的ctid
        batch2_params = batch2_call[0][1]
        assert batch2_params[0] == '(0,1)'


class TestStreamingFailureRaises:
    """验证流式处理失败时抛异常，不再静默break导致假完成"""

    def test_db_query_failure_raises(self):
        """db_conn.execute返回None（SQL超时失败）时应抛RuntimeError"""
        parser = _make_parser('12')

        count_cursor = _mock_cursor(fetchone_result={'count': 100})
        db_conn = MagicMock()
        # COUNT成功，SELECT返回None（模拟SQL超时，execute捕获异常返回None）
        db_conn.execute.side_effect = [count_cursor, None]

        data_loader = MagicMock()

        with pytest.raises(RuntimeError, match="数据库查询失败"):
            parser.parse_from_db_streaming(
                db_conn=db_conn, table_name='t', address_col='address',
                result_table_name='r', data_loader=data_loader, db_batch_size=10
            )

    def test_insert_failure_raises(self):
        """结果写入失败（inserted==0）时应抛RuntimeError"""
        parser = _make_parser('12')
        parser.rule_engine.parse.return_value = [{'original_address': 'a', 'province': ''}]

        count_cursor = _mock_cursor(fetchone_result={'count': 1})
        select_cursor = _mock_cursor(rows=[{'ctid': '(0,1)', 'address': 'a'}])
        db_conn = MagicMock()
        db_conn.execute.side_effect = [count_cursor, select_cursor]

        data_loader = MagicMock()
        data_loader.insert_address_tagging_results.return_value = 0  # 写入失败

        with pytest.raises(RuntimeError, match="结果写入失败"):
            parser.parse_from_db_streaming(
                db_conn=db_conn, table_name='t', address_col='address',
                result_table_name='r', data_loader=data_loader, db_batch_size=10
            )

    def test_processed_less_than_total_raises(self):
        """循环结束但处理数不足总数时应抛RuntimeError（暴露数据丢失）"""
        parser = _make_parser('12')
        parser.rule_engine.parse.return_value = [{'original_address': 'a', 'province': ''}]

        # total=5，但只有1行数据（模拟数据丢失/不一致）
        count_cursor = _mock_cursor(fetchone_result={'count': 5})
        select_cursor = _mock_cursor(rows=[{'ctid': '(0,1)', 'address': 'a'}])
        empty_cursor = _mock_cursor(rows=[])  # 第二批返回空
        db_conn = MagicMock()
        db_conn.execute.side_effect = [count_cursor, select_cursor, empty_cursor]

        data_loader = MagicMock()
        data_loader.insert_address_tagging_results.return_value = 1

        with pytest.raises(RuntimeError, match="流式处理异常终止"):
            parser.parse_from_db_streaming(
                db_conn=db_conn, table_name='t', address_col='address',
                result_table_name='r', data_loader=data_loader, db_batch_size=10
            )


class TestStreamingUserStop:
    """验证用户停止时正常返回，不抛异常"""

    def test_user_stop_returns_processed(self):
        """用户主动停止时返回已处理数，状态为已停止"""
        parser = _make_parser('12')
        parser.rule_engine.parse.return_value = [{'original_address': 'a', 'province': ''}]

        count_cursor = _mock_cursor(fetchone_result={'count': 100})
        batch1_cursor = _mock_cursor(rows=[{'ctid': '(0,1)', 'address': 'a'}])
        db_conn = MagicMock()
        db_conn.execute.side_effect = [count_cursor, batch1_cursor]

        data_loader = MagicMock()
        # 在第一批写入后设置 is_running=False，模拟用户停止
        def insert_side_effect(*args, **kwargs):
            parser.is_running = False
            return 1
        data_loader.insert_address_tagging_results.side_effect = insert_side_effect

        result = parser.parse_from_db_streaming(
            db_conn=db_conn, table_name='t', address_col='address',
            result_table_name='r', data_loader=data_loader, db_batch_size=1
        )

        assert result == 1
        status = parser.get_status()
        assert status['is_running'] is False
        assert '停止' in status['status_message']


class TestStreamingNormalComplete:
    """验证正常完成流程"""

    def test_normal_complete(self):
        """正常完成时返回处理数，状态为完成"""
        parser = _make_parser('12')
        parser.rule_engine.parse.return_value = [{'original_address': 'a', 'province': 'p'}]

        count_cursor = _mock_cursor(fetchone_result={'count': 1})
        select_cursor = _mock_cursor(rows=[{'ctid': '(0,1)', 'address': 'a'}])
        db_conn = MagicMock()
        db_conn.execute.side_effect = [count_cursor, select_cursor]

        data_loader = MagicMock()
        data_loader.insert_address_tagging_results.return_value = 1

        result = parser.parse_from_db_streaming(
            db_conn=db_conn, table_name='t', address_col='address',
            result_table_name='r', data_loader=data_loader, db_batch_size=10
        )

        assert result == 1
        status = parser.get_status()
        # 注意：parse_from_db_streaming 完成时不再设置 is_running=False，
        # 由调用方（task_func）统一设置 is_running=False + completed=True，
        # 避免 fragment 在两个状态设置之间读到 is_running=False, completed=False 的中间状态。
        # 因此这里断言 is_running 仍为 True（需由调用方设置为 False）。
        assert status['is_running'] is True
        assert status['progress'] == 1.0
        assert '完成' in status['status_message']


class TestCopyTableLateralJoin:
    """验证副本表创建使用 LEFT JOIN LATERAL ... LIMIT 1 避免行数膨胀"""

    @staticmethod
    def _find_create_sql(execute_calls):
        """从execute调用列表中找到CREATE TABLE的SQL"""
        for call in execute_calls:
            sql = call[0][0]
            if 'CREATE TABLE' in sql:
                return sql
        return None

    def test_12level_copy_table_from_result_uses_lateral(self):
        """12级副本表（from_result版本）应使用 LATERAL + LIMIT 1 + s.*"""
        from database.data_loader import DataLoader

        db = MagicMock()
        loader = DataLoader(db)
        loader.create_tagging_copy_table_from_result('src', 'addr', 'result')

        create_sql = self._find_create_sql(db.execute.call_args_list)
        assert create_sql is not None
        assert 'LEFT JOIN LATERAL' in create_sql
        assert 'LIMIT 1' in create_sql
        assert 's.*' in create_sql  # 保留源表全部字段

    def test_17level_copy_table_from_result_uses_lateral(self):
        """17级副本表应使用 LATERAL + LIMIT 1"""
        from database.data_loader import DataLoader

        db = MagicMock()
        loader = DataLoader(db)
        loader.create_tagging_17_copy_table_from_result('src', 'addr', 'result')

        create_sql = self._find_create_sql(db.execute.call_args_list)
        assert create_sql is not None
        assert 'LEFT JOIN LATERAL' in create_sql
        assert 'LIMIT 1' in create_sql

    def test_17_2level_copy_table_from_result_uses_lateral(self):
        """17_2级副本表应使用 LATERAL + LIMIT 1"""
        from database.data_loader import DataLoader

        db = MagicMock()
        loader = DataLoader(db)
        loader.create_tagging_17_2_copy_table_from_result('src', 'addr', 'result')

        create_sql = self._find_create_sql(db.execute.call_args_list)
        assert create_sql is not None
        assert 'LEFT JOIN LATERAL' in create_sql
        assert 'LIMIT 1' in create_sql

    def test_12level_copy_table_preserves_source_fields(self):
        """12级副本表（非from_result版本）应保留源表全部字段"""
        from database.data_loader import DataLoader

        db = MagicMock()
        loader = DataLoader(db)
        loader.create_tagging_copy_table('src', 'addr', results=[])

        create_sql = self._find_create_sql(db.execute.call_args_list)
        assert create_sql is not None
        assert 'SELECT * FROM' in create_sql  # 保留源表全部字段

    def test_12level_copy_table_no_longer_skips_large_table(self):
        """12级大表（超过100万行）不再跳过副本表创建"""
        from database.data_loader import DataLoader

        db = MagicMock()
        loader = DataLoader(db)
        loader._get_table_row_count = MagicMock(return_value=2_000_000)

        result = loader.create_tagging_copy_table_from_result('src', 'addr', 'result')

        create_sql = self._find_create_sql(db.execute.call_args_list)
        assert create_sql is not None
        assert 'LEFT JOIN LATERAL' in create_sql
        assert result == 'src_tagging'

    def test_17level_copy_table_no_longer_skips_large_table(self):
        """17级大表（超过100万行）不再跳过副本表创建"""
        from database.data_loader import DataLoader

        db = MagicMock()
        loader = DataLoader(db)
        loader._get_table_row_count = MagicMock(return_value=10_000_000)

        result = loader.create_tagging_17_copy_table_from_result('src', 'addr', 'result')

        create_sql = self._find_create_sql(db.execute.call_args_list)
        assert create_sql is not None
        assert 'LEFT JOIN LATERAL' in create_sql
        assert result == 'src_tagging_17'

    def test_17_2level_copy_table_no_longer_skips_large_table(self):
        """17级双字段大表（超过100万行）不再跳过副本表创建"""
        from database.data_loader import DataLoader

        db = MagicMock()
        loader = DataLoader(db)
        loader._get_table_row_count = MagicMock(return_value=10_000_000)

        result = loader.create_tagging_17_2_copy_table_from_result('src', 'addr', 'result')

        create_sql = self._find_create_sql(db.execute.call_args_list)
        assert create_sql is not None
        assert 'LEFT JOIN LATERAL' in create_sql
        assert result == 'src_tagging_17_2'


class TestResultTableFieldLength:
    """验证结果表 unit/floor/house 字段长度从 VARCHAR(50) 扩展到 VARCHAR(200)

    修复背景：tmp_houses 表108万数据分词到48万时，某条地址的 unit/floor/house
    字段值超过50字符，导致 INSERT 失败（"对于可变字符类型来说，值太长了(50)"），
    触发 raise RuntimeError 中断整个流式处理。
    """

    def test_create_table_uses_varchar_200(self):
        """CREATE TABLE 中 unit/floor/house 应使用 VARCHAR(200) 而非 VARCHAR(50)"""
        from database.data_loader import DataLoader

        db = MagicMock()
        loader = DataLoader(db)
        loader.create_address_tagging_table('test_result_table')

        create_sql = TestCopyTableLateralJoin._find_create_sql(db.execute.call_args_list)
        assert create_sql is not None
        # unit/floor/house 不应是 VARCHAR(50)
        assert 'VARCHAR(50)' not in create_sql
        # 应包含 VARCHAR(200)
        assert 'VARCHAR(200)' in create_sql

    def test_copy_table_field_type_map_uses_varchar_200(self):
        """副本表 field_type_map 中 unit/floor/house 应为 VARCHAR(200)"""
        from database.data_loader import DataLoader

        db = MagicMock()
        loader = DataLoader(db)
        loader.create_tagging_copy_table('src', 'addr', results=[])

        # 副本表通过 ALTER TABLE ADD COLUMN 添加字段，检查 ADD COLUMN 的SQL
        add_column_sqls = []
        for call in db.execute.call_args_list:
            sql = call[0][0]
            if 'ADD COLUMN' in sql:
                add_column_sqls.append(sql)

        # unit/floor/house 的 ADD COLUMN 应使用 VARCHAR(200)，不是 VARCHAR(50)
        for col in ['unit', 'floor', 'house']:
            col_sqls = [s for s in add_column_sqls if f'"{col}"' in s]
            assert len(col_sqls) == 1, f"应有1个 {col} 的 ADD COLUMN 语句"
            assert 'VARCHAR(200)' in col_sqls[0], f"{col} 应为 VARCHAR(200)"
            assert 'VARCHAR(50)' not in col_sqls[0], f"{col} 不应为 VARCHAR(50)"
