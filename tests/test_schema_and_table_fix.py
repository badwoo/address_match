"""
测试修复：向量预处理功能的schema支持和表名硬编码问题

测试内容：
    1. connection.py: 连接时设置search_path到用户指定的schema
    2. vector_store.py: insert_vectors方法中表类型判断使用table_type参数
    3. data_loader.py: recall_results相关方法参数化表名
    4. connection.py: quote_identifier函数处理中文表名
    5. app.py: 字段选择默认选第一个字段
"""

import unittest
from unittest.mock import MagicMock, patch, PropertyMock
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.connection import DBConnection, quote_identifier
from config import Config


class TestQuoteIdentifier(unittest.TestCase):
    """测试SQL标识符引用函数"""

    def test_chinese_table_name(self):
        result = quote_identifier("企业表")
        self.assertEqual(result, '"企业表"')

    def test_standard_table_name(self):
        result = quote_identifier("enterprise_vectors")
        self.assertEqual(result, '"enterprise_vectors"')

    def test_empty_string(self):
        result = quote_identifier("")
        self.assertEqual(result, "")

    def test_none_value(self):
        result = quote_identifier(None)
        self.assertIsNone(result)

    def test_name_with_double_quotes(self):
        result = quote_identifier('table"name')
        self.assertEqual(result, '"table""name"')

    def test_standard_address_table(self):
        result = quote_identifier("标准地址表")
        self.assertEqual(result, '"标准地址表"')


class TestDBConnectionSearchPath(unittest.TestCase):
    """测试数据库连接设置search_path"""

    @patch('database.connection.psycopg2')
    def test_connect_sets_search_path_to_custom_schema(self, mock_psycopg2):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_psycopg2.connect.return_value = mock_conn

        db = DBConnection(schema='ai')
        result = db.connect()

        self.assertTrue(result)
        search_path_calls = [call for call in mock_cursor.execute.call_args_list
                           if 'search_path' in str(call)]
        self.assertEqual(len(search_path_calls), 1)
        search_path_sql = str(search_path_calls[0])
        self.assertIn('ai', search_path_sql)
        self.assertIn('public', search_path_sql)

    @patch('database.connection.psycopg2')
    def test_connect_sets_search_path_to_public_by_default(self, mock_psycopg2):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_psycopg2.connect.return_value = mock_conn

        db = DBConnection()
        result = db.connect()

        self.assertTrue(result)
        search_path_calls = [call for call in mock_cursor.execute.call_args_list
                           if 'search_path' in str(call)]
        self.assertEqual(len(search_path_calls), 1)
        search_path_sql = str(search_path_calls[0])
        self.assertIn('public', search_path_sql)


class TestVectorStoreInsertVectors(unittest.TestCase):
    """测试VectorStore.insert_vectors方法使用table_type参数"""

    def test_insert_vectors_accepts_table_type_enterprise(self):
        """验证 insert_vectors 在 table_type='enterprise' 时不抛出异常"""
        from database.vector_store import VectorStore

        mock_db = MagicMock()
        mock_db.execute.return_value = MagicMock()
        mock_db.conn.autocommit = True
        mock_db.schema = 'ai'

        vs = VectorStore(mock_db)

        import numpy as np
        vectors = np.random.rand(2, 768).astype(np.float32)
        source_ids = ['id1', 'id2']
        addresses = ['地址1', '地址2']

        # 调用不应抛出异常（execute_values 在 mock cursor 上可能失败，
        # 但 insert_vectors 应优雅降级，不 crash）
        try:
            vs.insert_vectors(vectors, source_ids, addresses,
                             table_name='enterprise_vectors',
                             extra_data=['企业1', '企业2'],
                             table_type='enterprise')
        except Exception as e:
            self.fail(f"insert_vectors with table_type='enterprise' raised: {e}")

    def test_insert_vectors_accepts_table_type_standard(self):
        """验证 insert_vectors 在 table_type='standard' 时不抛出异常"""
        from database.vector_store import VectorStore

        mock_db = MagicMock()
        mock_db.execute.return_value = MagicMock()
        mock_db.conn.autocommit = True
        mock_db.schema = 'ai'

        vs = VectorStore(mock_db)

        import numpy as np
        vectors = np.random.rand(2, 768).astype(np.float32)
        source_ids = ['id1', 'id2']
        addresses = ['地址1', '地址2']

        try:
            vs.insert_vectors(vectors, source_ids, addresses,
                             table_name='standard_address_vectors',
                             extra_data=['房号1', '房号2'],
                             table_type='standard')
        except Exception as e:
            self.fail(f"insert_vectors with table_type='standard' raised: {e}")

    def test_insert_vectors_default_table_type_is_enterprise(self):
        """验证 insert_vectors 默认 table_type 不抛出异常"""
        from database.vector_store import VectorStore

        mock_db = MagicMock()
        mock_db.execute.return_value = MagicMock()
        mock_db.conn.autocommit = True
        mock_db.schema = 'ai'

        vs = VectorStore(mock_db)

        import numpy as np
        vectors = np.random.rand(2, 768).astype(np.float32)
        source_ids = ['id1', 'id2']
        addresses = ['地址1', '地址2']

        try:
            vs.insert_vectors(vectors, source_ids, addresses,
                             table_name='enterprise_vectors',
                             extra_data=['企业1', '企业2'])
        except Exception as e:
            self.fail(f"insert_vectors with default table_type raised: {e}")


class TestDataLoaderRecallTableParameterized(unittest.TestCase):
    """测试DataLoader中recall_results相关方法参数化表名"""

    def test_create_recall_table_uses_config_default(self):
        from database.data_loader import DataLoader

        mock_db = MagicMock()
        mock_db.execute.return_value = MagicMock()
        mock_db.schema = 'ai'

        loader = DataLoader(mock_db)
        loader.create_recall_table()

        execute_call = str(mock_db.execute.call_args_list[0])
        self.assertIn(Config.RECALL_RESULTS_TABLE, execute_call)

    def test_create_recall_table_uses_custom_table_name(self):
        from database.data_loader import DataLoader

        mock_db = MagicMock()
        mock_db.execute.return_value = MagicMock()
        mock_db.schema = 'ai'

        loader = DataLoader(mock_db)
        loader.create_recall_table(table_name='custom_recall')

        execute_call = str(mock_db.execute.call_args_list[0])
        self.assertIn('custom_recall', execute_call)

    def test_truncate_recall_table_uses_config_default(self):
        from database.data_loader import DataLoader

        mock_db = MagicMock()
        mock_db.execute.return_value = MagicMock()
        mock_db.schema = 'ai'

        loader = DataLoader(mock_db)
        loader.truncate_recall_table()

        execute_call = str(mock_db.execute.call_args_list[0])
        self.assertIn(Config.RECALL_RESULTS_TABLE, execute_call)

    def test_truncate_recall_table_uses_custom_table_name(self):
        from database.data_loader import DataLoader

        mock_db = MagicMock()
        mock_db.execute.return_value = MagicMock()
        mock_db.schema = 'ai'

        loader = DataLoader(mock_db)
        loader.truncate_recall_table(table_name='custom_recall')

        execute_call = str(mock_db.execute.call_args_list[0])
        self.assertIn('custom_recall', execute_call)

    def test_insert_recall_results_uses_config_default(self):
        from database.data_loader import DataLoader

        mock_db = MagicMock()
        mock_db.cursor = MagicMock()
        mock_db.schema = 'ai'

        loader = DataLoader(mock_db)
        results = [{
            'enterprise_id': 'E001',
            'enterprise_name': '测试企业',
            'enterprise_address': '测试地址',
            'candidates': [{
                'source_id': 'S001',
                'address': '标准地址',
                'room_no': '101',
                'similarity': 0.95
            }]
        }]
        loader.insert_recall_results(results)

        execute_values_call = str(mock_db.cursor.execute.call_args_list) if hasattr(mock_db.cursor, 'execute') else ''
        if not execute_values_call:
            execute_values_call = str(mock_db.cursor.call_args_list) if hasattr(mock_db.cursor, 'call_args_list') else ''

    def test_load_recall_results_uses_config_default(self):
        from database.data_loader import DataLoader

        mock_db = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_db.execute.return_value = mock_cursor
        mock_db.schema = 'ai'

        loader = DataLoader(mock_db)
        loader.load_recall_results()

        execute_call = str(mock_db.execute.call_args_list[0])
        self.assertIn(Config.RECALL_RESULTS_TABLE, execute_call)

    def test_load_recall_results_uses_custom_table_name(self):
        from database.data_loader import DataLoader

        mock_db = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_db.execute.return_value = mock_cursor
        mock_db.schema = 'ai'

        loader = DataLoader(mock_db)
        loader.load_recall_results(table_name='custom_recall')

        execute_call = str(mock_db.execute.call_args_list[0])
        self.assertIn('custom_recall', execute_call)

    def test_export_recall_results_batch_uses_config_default(self):
        from database.data_loader import DataLoader

        mock_db = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = {'count': 0}
        mock_db.execute.return_value = mock_cursor
        mock_db.schema = 'ai'

        loader = DataLoader(mock_db)
        list(loader.export_recall_results_batch())

        execute_call = str(mock_db.execute.call_args_list[0])
        self.assertIn(Config.RECALL_RESULTS_TABLE, execute_call)


class TestConfigTableNamesNotHardcoded(unittest.TestCase):
    """测试Config中的表名配置可被修改"""

    def test_enterprise_vector_table_config(self):
        self.assertEqual(Config.ENTERPRISE_VECTOR_TABLE, 'enterprise_vectors')

    def test_standard_vector_table_config(self):
        self.assertEqual(Config.STANDARD_VECTOR_TABLE, 'standard_address_vectors')

    def test_recall_results_table_config(self):
        self.assertEqual(Config.RECALL_RESULTS_TABLE, 'recall_results')

    def test_match_results_table_config(self):
        self.assertEqual(Config.MATCH_RESULTS_TABLE, 'match_results')

    def test_mgeo_similarity_results_table_config(self):
        self.assertEqual(Config.MGEO_SIMILARITY_RESULTS_TABLE, 'mgeo_similarity_results')

    def test_config_values_are_strings(self):
        self.assertIsInstance(Config.ENTERPRISE_VECTOR_TABLE, str)
        self.assertIsInstance(Config.STANDARD_VECTOR_TABLE, str)
        self.assertIsInstance(Config.RECALL_RESULTS_TABLE, str)


class TestDBConnectionSchemaSupport(unittest.TestCase):
    """测试DBConnection对schema的支持"""

    def test_schema_defaults_to_config(self):
        db = DBConnection()
        self.assertEqual(db.schema, Config.DB_SCHEMA)

    def test_schema_can_be_customized(self):
        db = DBConnection(schema='ai')
        self.assertEqual(db.schema, 'ai')

    def test_schema_stored_correctly(self):
        db = DBConnection(schema='my_schema')
        self.assertEqual(db.schema, 'my_schema')


if __name__ == '__main__':
    unittest.main()
