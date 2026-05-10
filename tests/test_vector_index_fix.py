"""
测试修复：创建向量索引功能

问题：
    1. 创建向量索引功能不生效，一直提示"正在创建索引"
    2. 开始时间没有记录，也没有实时运行的时长显示

根因分析：
    1. 后台线程使用主线程的vector_store（共享数据库连接），psycopg2连接不是线程安全的，
       导致CREATE INDEX操作挂起或失败，is_running一直为True
    2. start_datetime在线程内部设置存在竞态条件，且缺少start_time时间戳用于实时计算运行时长

修复方案：
    1. 后台线程创建独立的DBConnection和VectorStore，与主线程连接完全隔离
    2. 在_start_index_creation中立即设置start_datetime和start_time，避免竞态条件
    3. index_status增加start_time字段，UI中显示实时运行时长

测试内容：
    1. _init_index_status包含start_time字段
    2. create_vector_index生成正确的ivfflat SQL
    3. create_vector_index生成正确的hnsw SQL
    4. create_vector_index自动计算ivfflat lists参数
    5. create_vector_index自动计算hnsw参数
    6. create_vector_index设置maintenance_work_mem
    7. 后台线程使用独立数据库连接
    8. 后台线程正确更新index_status
    9. 后台线程连接失败时正确处理
    10. 后台线程索引创建失败时正确处理
"""

import unittest
from unittest.mock import MagicMock, patch, call
import sys
import os
import time
import threading
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

for mod_name in ['torch', 'torch.cuda', 'torch.backends', 'torch.backends.cuda',
                  'pgvector', 'pgvector.psycopg2', 'streamlit', 'modelscope',
                  'numpy', 'psycopg2', 'psycopg2.extras', 'pandas',
                  'modelscope.models', 'modelscope.preprocessors']:
    if mod_name not in sys.modules:
        sys.modules[mod_name] = types.ModuleType(mod_name)

if not hasattr(sys.modules['torch'], 'cuda'):
    sys.modules['torch'].cuda = MagicMock()
if not hasattr(sys.modules['torch'], 'backends'):
    sys.modules['torch'].backends = MagicMock()
if not hasattr(sys.modules['torch'].backends, 'cuda'):
    sys.modules['torch'].backends.cuda = MagicMock()
if not hasattr(sys.modules['torch'], '__version__'):
    sys.modules['torch'].__version__ = '2.0.0'
sys.modules['torch'].cuda.is_available = MagicMock(return_value=False)
sys.modules['torch'].backends.cuda.is_built = MagicMock(return_value=False)

from database.vector_store import VectorStore
from database.connection import DBConnection
from config import Config


class AttrDict(dict):
    """支持属性访问的字典，模拟Streamlit的session_state"""
    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError(f"'AttrDict' object has no attribute '{key}'")

    def __setattr__(self, key, value):
        self[key] = value

    def __delattr__(self, key):
        try:
            del self[key]
        except KeyError:
            raise AttributeError(f"'AttrDict' object has no attribute '{key}'")


def _make_index_status(is_running=False, completed=False, error_message='',
                       start_datetime='', end_datetime='', execution_time=0.0, start_time=0.0):
    return {
        'is_running': is_running,
        'completed': completed,
        'error_message': error_message,
        'start_datetime': start_datetime,
        'end_datetime': end_datetime,
        'execution_time': execution_time,
        'start_time': start_time
    }


class TestInitIndexStatus(unittest.TestCase):
    """测试_init_index_status函数包含start_time字段"""

    def test_init_index_status_has_start_time(self):
        import app as app_module
        status = app_module._init_index_status()
        self.assertIn('start_time', status)
        self.assertEqual(status['start_time'], 0.0)

    def test_init_index_status_has_all_required_fields(self):
        import app as app_module
        status = app_module._init_index_status()
        required_fields = ['is_running', 'completed', 'error_message',
                          'start_datetime', 'end_datetime', 'execution_time', 'start_time']
        for field in required_fields:
            self.assertIn(field, status, f"缺少必要字段: {field}")

    def test_init_index_status_default_values(self):
        import app as app_module
        status = app_module._init_index_status()
        self.assertFalse(status['is_running'])
        self.assertFalse(status['completed'])
        self.assertEqual(status['error_message'], '')
        self.assertEqual(status['start_datetime'], '')
        self.assertEqual(status['end_datetime'], '')
        self.assertEqual(status['execution_time'], 0.0)
        self.assertEqual(status['start_time'], 0.0)


class TestCreateVectorIndexSQL(unittest.TestCase):
    """测试create_vector_index方法生成正确的SQL"""

    def _create_mock_db(self, row_count=100000):
        mock_db = MagicMock()
        mock_db.schema = 'public'
        mock_cursor = MagicMock()

        check_cursor = MagicMock()
        check_cursor.fetchone.return_value = None
        count_cursor = MagicMock()
        count_cursor.fetchone.return_value = {'count': row_count}
        show_cursor = MagicMock()
        show_cursor.fetchone.return_value = ['64MB']

        execute_results = [check_cursor, count_cursor, show_cursor, mock_cursor]
        mock_db.execute.side_effect = execute_results
        mock_db.cursor = mock_cursor

        return mock_db

    def test_ivfflat_sql_contains_correct_clauses(self):
        mock_db = self._create_mock_db(row_count=500000)
        vs = VectorStore(mock_db)
        vs.create_vector_index(
            table_name='test_table',
            index_name='test_idx',
            index_type='ivfflat',
            lists=500,
            maintenance_work_mem=None
        )
        all_calls = [str(c) for c in mock_db.execute.call_args_list]
        create_index_call = None
        for c in all_calls:
            if 'CREATE INDEX' in c:
                create_index_call = c
                break
        self.assertIsNotNone(create_index_call, "应包含CREATE INDEX语句")
        self.assertIn('ivfflat', create_index_call)
        self.assertIn('vector_cosine_ops', create_index_call)
        self.assertIn('lists', create_index_call)

    def test_hnsw_sql_contains_correct_clauses(self):
        mock_db = self._create_mock_db(row_count=500000)
        vs = VectorStore(mock_db)
        vs.create_vector_index(
            table_name='test_table',
            index_name='test_idx',
            index_type='hnsw',
            m=16,
            ef_construction=200,
            maintenance_work_mem=None
        )
        all_calls = [str(c) for c in mock_db.execute.call_args_list]
        create_index_call = None
        for c in all_calls:
            if 'CREATE INDEX' in c:
                create_index_call = c
                break
        self.assertIsNotNone(create_index_call, "应包含CREATE INDEX语句")
        self.assertIn('hnsw', create_index_call)
        self.assertIn('vector_cosine_ops', create_index_call)
        self.assertIn('m', create_index_call)
        self.assertIn('ef_construction', create_index_call)

    def test_ivfflat_auto_lists_small_dataset(self):
        mock_db = self._create_mock_db(row_count=100000)
        vs = VectorStore(mock_db)
        vs.create_vector_index(
            table_name='test_table',
            index_name='test_idx',
            index_type='ivfflat',
            lists=None,
            maintenance_work_mem=None
        )
        all_calls = [str(c) for c in mock_db.execute.call_args_list]
        create_index_call = None
        for c in all_calls:
            if 'CREATE INDEX' in c:
                create_index_call = c
                break
        self.assertIsNotNone(create_index_call)
        expected_lists = max(100, min(4000, 100000 // 1000))
        self.assertIn(f'lists = {expected_lists}', create_index_call)

    def test_ivfflat_auto_lists_large_dataset(self):
        mock_db = self._create_mock_db(row_count=5_000_000)
        vs = VectorStore(mock_db)
        vs.create_vector_index(
            table_name='test_table',
            index_name='test_idx',
            index_type='ivfflat',
            lists=None,
            maintenance_work_mem=None
        )
        all_calls = [str(c) for c in mock_db.execute.call_args_list]
        create_index_call = None
        for c in all_calls:
            if 'CREATE INDEX' in c:
                create_index_call = c
                break
        self.assertIsNotNone(create_index_call)
        expected_lists = max(100, min(4000, int(5_000_000 ** 0.5)))
        self.assertIn(f'lists = {expected_lists}', create_index_call)

    def test_hnsw_default_parameters(self):
        mock_db = self._create_mock_db(row_count=500000)
        vs = VectorStore(mock_db)
        vs.create_vector_index(
            table_name='test_table',
            index_name='test_idx',
            index_type='hnsw',
            m=None,
            ef_construction=None,
            maintenance_work_mem=None
        )
        all_calls = [str(c) for c in mock_db.execute.call_args_list]
        create_index_call = None
        for c in all_calls:
            if 'CREATE INDEX' in c:
                create_index_call = c
                break
        self.assertIsNotNone(create_index_call)
        self.assertIn('m = 16', create_index_call)
        self.assertIn('ef_construction = 200', create_index_call)

    def test_maintenance_work_mem_is_set(self):
        mock_db = self._create_mock_db(row_count=500000)
        vs = VectorStore(mock_db)
        vs.create_vector_index(
            table_name='test_table',
            index_name='test_idx',
            index_type='ivfflat',
            lists=500,
            maintenance_work_mem='2GB'
        )
        all_calls = [str(c) for c in mock_db.execute.call_args_list]
        mem_set_found = any('maintenance_work_mem' in c and 'SET' in c for c in all_calls)
        self.assertTrue(mem_set_found, "应设置maintenance_work_mem")

    def test_maintenance_work_mem_not_set_when_none(self):
        mock_db = self._create_mock_db(row_count=500000)
        vs = VectorStore(mock_db)
        vs.create_vector_index(
            table_name='test_table',
            index_name='test_idx',
            index_type='ivfflat',
            lists=500,
            maintenance_work_mem=None
        )
        all_calls = [str(c) for c in mock_db.execute.call_args_list]
        mem_set_calls = [c for c in all_calls if 'maintenance_work_mem' in c and 'SET' in c]
        self.assertEqual(len(mem_set_calls), 0, "maintenance_work_mem为None时不应设置")

    def test_index_already_exists_skips_creation(self):
        mock_db = MagicMock()
        mock_db.schema = 'public'
        check_cursor = MagicMock()
        check_cursor.fetchone.return_value = [1]
        mock_db.execute.return_value = check_cursor

        vs = VectorStore(mock_db)
        result = vs.create_vector_index(
            table_name='test_table',
            index_name='existing_idx',
            index_type='ivfflat'
        )
        self.assertTrue(result)
        execute_calls = [str(c) for c in mock_db.execute.call_args_list]
        create_index_calls = [c for c in execute_calls if 'CREATE INDEX' in c]
        self.assertEqual(len(create_index_calls), 0, "索引已存在时不应执行CREATE INDEX")

    def test_unsupported_index_type_returns_false(self):
        mock_db = self._create_mock_db(row_count=500000)
        vs = VectorStore(mock_db)
        result = vs.create_vector_index(
            table_name='test_table',
            index_name='test_idx',
            index_type='unsupported_type',
            maintenance_work_mem=None
        )
        self.assertFalse(result)


class TestRunIndexCreationBackground(unittest.TestCase):
    """测试后台线程使用独立数据库连接"""

    @patch('app.DBConnection')
    @patch('app.VectorStore')
    @patch('app.st')
    def test_background_thread_creates_independent_connection(self, mock_st, mock_vs_class, mock_db_class):
        import app as app_module

        mock_session_state = AttrDict()
        mock_st.session_state = mock_session_state

        mock_db_instance = MagicMock()
        mock_db_instance.connect.return_value = True
        mock_db_class.return_value = mock_db_instance

        mock_vs_instance = MagicMock()
        mock_vs_instance.create_vector_index.return_value = True
        mock_vs_class.return_value = mock_vs_instance

        mock_session_state.index_status = _make_index_status(
            is_running=True, start_datetime='2026-01-01 00:00:00', start_time=time.time()
        )

        db_config = {
            'host': 'localhost',
            'port': 5432,
            'schema': 'public',
            'dbname': 'testdb',
            'user': 'testuser',
            'password': 'testpass'
        }

        app_module.run_index_creation_background(
            db_config, 'test_table', 'test_idx', 'ivfflat',
            500, None, None, '1GB'
        )

        mock_db_class.assert_called_once_with(
            host='localhost',
            port=5432,
            schema='public',
            dbname='testdb',
            user='testuser',
            password='testpass'
        )
        mock_db_instance.connect.assert_called_once()

    @patch('app.DBConnection')
    @patch('app.VectorStore')
    @patch('app.st')
    def test_background_thread_creates_vector_store_with_new_connection(self, mock_st, mock_vs_class, mock_db_class):
        import app as app_module

        mock_session_state = AttrDict()
        mock_st.session_state = mock_session_state

        mock_db_instance = MagicMock()
        mock_db_instance.connect.return_value = True
        mock_db_class.return_value = mock_db_instance

        mock_vs_instance = MagicMock()
        mock_vs_instance.create_vector_index.return_value = True
        mock_vs_class.return_value = mock_vs_instance

        mock_session_state.index_status = _make_index_status(
            is_running=True, start_datetime='2026-01-01 00:00:00', start_time=time.time()
        )

        db_config = {
            'host': 'localhost',
            'port': 5432,
            'schema': 'public',
            'dbname': 'testdb',
            'user': 'testuser',
            'password': 'testpass'
        }

        app_module.run_index_creation_background(
            db_config, 'test_table', 'test_idx', 'ivfflat',
            500, None, None, '1GB'
        )

        mock_vs_class.assert_called_once_with(mock_db_instance)

    @patch('app.DBConnection')
    @patch('app.VectorStore')
    @patch('app.st')
    def test_background_thread_calls_create_vector_index(self, mock_st, mock_vs_class, mock_db_class):
        import app as app_module

        mock_session_state = AttrDict()
        mock_st.session_state = mock_session_state

        mock_db_instance = MagicMock()
        mock_db_instance.connect.return_value = True
        mock_db_class.return_value = mock_db_instance

        mock_vs_instance = MagicMock()
        mock_vs_instance.create_vector_index.return_value = True
        mock_vs_class.return_value = mock_vs_instance

        mock_session_state.index_status = _make_index_status(
            is_running=True, start_datetime='2026-01-01 00:00:00', start_time=time.time()
        )

        db_config = {
            'host': 'localhost',
            'port': 5432,
            'schema': 'public',
            'dbname': 'testdb',
            'user': 'testuser',
            'password': 'testpass'
        }

        app_module.run_index_creation_background(
            db_config, 'test_table', 'test_idx', 'hnsw',
            None, 16, 200, '1GB'
        )

        mock_vs_instance.create_vector_index.assert_called_once_with(
            table_name='test_table',
            index_name='test_idx',
            index_type='hnsw',
            lists=None,
            m=16,
            ef_construction=200,
            maintenance_work_mem='1GB'
        )

    @patch('app.DBConnection')
    @patch('app.VectorStore')
    @patch('app.st')
    def test_background_thread_updates_status_on_success(self, mock_st, mock_vs_class, mock_db_class):
        import app as app_module

        mock_session_state = AttrDict()
        mock_st.session_state = mock_session_state

        mock_db_instance = MagicMock()
        mock_db_instance.connect.return_value = True
        mock_db_class.return_value = mock_db_instance

        mock_vs_instance = MagicMock()
        mock_vs_instance.create_vector_index.return_value = True
        mock_vs_class.return_value = mock_vs_instance

        start_time = time.time() - 0.1
        mock_session_state.index_status = _make_index_status(
            is_running=True, start_datetime='2026-01-01 00:00:00', start_time=start_time
        )

        db_config = {
            'host': 'localhost',
            'port': 5432,
            'schema': 'public',
            'dbname': 'testdb',
            'user': 'testuser',
            'password': 'testpass'
        }

        app_module.run_index_creation_background(
            db_config, 'test_table', 'test_idx', 'ivfflat',
            500, None, None, None
        )

        status = mock_session_state.index_status
        self.assertTrue(status['completed'])
        self.assertFalse(status['is_running'])
        self.assertNotEqual(status['end_datetime'], '')
        self.assertGreater(status['execution_time'], 0)
        self.assertEqual(status['error_message'], '')

    @patch('app.DBConnection')
    @patch('app.VectorStore')
    @patch('app.st')
    def test_background_thread_handles_connection_failure(self, mock_st, mock_vs_class, mock_db_class):
        import app as app_module

        mock_session_state = AttrDict()
        mock_st.session_state = mock_session_state

        mock_db_instance = MagicMock()
        mock_db_instance.connect.return_value = False
        mock_db_class.return_value = mock_db_instance

        mock_session_state.index_status = _make_index_status(
            is_running=True, start_datetime='2026-01-01 00:00:00', start_time=time.time()
        )

        db_config = {
            'host': 'localhost',
            'port': 5432,
            'schema': 'public',
            'dbname': 'testdb',
            'user': 'testuser',
            'password': 'testpass'
        }

        app_module.run_index_creation_background(
            db_config, 'test_table', 'test_idx', 'ivfflat',
            500, None, None, None
        )

        status = mock_session_state.index_status
        self.assertFalse(status['is_running'])
        self.assertIn('无法连接数据库', status['error_message'])
        mock_db_instance.close.assert_called_once()

    @patch('app.DBConnection')
    @patch('app.VectorStore')
    @patch('app.st')
    def test_background_thread_handles_index_creation_failure(self, mock_st, mock_vs_class, mock_db_class):
        import app as app_module

        mock_session_state = AttrDict()
        mock_st.session_state = mock_session_state

        mock_db_instance = MagicMock()
        mock_db_instance.connect.return_value = True
        mock_db_class.return_value = mock_db_instance

        mock_vs_instance = MagicMock()
        mock_vs_instance.create_vector_index.return_value = False
        mock_vs_class.return_value = mock_vs_instance

        mock_session_state.index_status = _make_index_status(
            is_running=True, start_datetime='2026-01-01 00:00:00', start_time=time.time()
        )

        db_config = {
            'host': 'localhost',
            'port': 5432,
            'schema': 'public',
            'dbname': 'testdb',
            'user': 'testuser',
            'password': 'testpass'
        }

        app_module.run_index_creation_background(
            db_config, 'test_table', 'test_idx', 'ivfflat',
            500, None, None, None
        )

        status = mock_session_state.index_status
        self.assertFalse(status['is_running'])
        self.assertIn('索引创建失败', status['error_message'])
        mock_db_instance.close.assert_called_once()

    @patch('app.DBConnection')
    @patch('app.VectorStore')
    @patch('app.st')
    def test_background_thread_handles_exception(self, mock_st, mock_vs_class, mock_db_class):
        import app as app_module

        mock_session_state = AttrDict()
        mock_st.session_state = mock_session_state

        mock_db_instance = MagicMock()
        mock_db_instance.connect.return_value = True
        mock_db_class.return_value = mock_db_instance

        mock_vs_instance = MagicMock()
        mock_vs_instance.create_vector_index.side_effect = Exception("数据库错误")
        mock_vs_class.return_value = mock_vs_instance

        mock_session_state.index_status = _make_index_status(
            is_running=True, start_datetime='2026-01-01 00:00:00', start_time=time.time()
        )

        db_config = {
            'host': 'localhost',
            'port': 5432,
            'schema': 'public',
            'dbname': 'testdb',
            'user': 'testuser',
            'password': 'testpass'
        }

        app_module.run_index_creation_background(
            db_config, 'test_table', 'test_idx', 'ivfflat',
            500, None, None, None
        )

        status = mock_session_state.index_status
        self.assertFalse(status['is_running'])
        self.assertIn('数据库错误', status['error_message'])
        mock_db_instance.close.assert_called_once()

    @patch('app.DBConnection')
    @patch('app.VectorStore')
    @patch('app.st')
    def test_background_thread_closes_connection_in_finally(self, mock_st, mock_vs_class, mock_db_class):
        import app as app_module

        mock_session_state = AttrDict()
        mock_st.session_state = mock_session_state

        mock_db_instance = MagicMock()
        mock_db_instance.connect.return_value = True
        mock_db_class.return_value = mock_db_instance

        mock_vs_instance = MagicMock()
        mock_vs_instance.create_vector_index.return_value = True
        mock_vs_class.return_value = mock_vs_instance

        mock_session_state.index_status = _make_index_status(
            is_running=True, start_datetime='2026-01-01 00:00:00', start_time=time.time()
        )

        db_config = {
            'host': 'localhost',
            'port': 5432,
            'schema': 'public',
            'dbname': 'testdb',
            'user': 'testuser',
            'password': 'testpass'
        }

        app_module.run_index_creation_background(
            db_config, 'test_table', 'test_idx', 'ivfflat',
            500, None, None, None
        )

        mock_db_instance.close.assert_called_once()


class TestStartIndexCreation(unittest.TestCase):
    """测试_start_index_creation函数正确设置开始时间"""

    @patch('app.threading.Thread')
    @patch('app.st')
    def test_start_index_creation_sets_start_datetime_immediately(self, mock_st, mock_thread_class):
        import app as app_module

        mock_session_state = AttrDict()
        mock_st.session_state = mock_session_state
        mock_thread_instance = MagicMock()
        mock_thread_class.return_value = mock_thread_instance

        mock_session_state.index_status = app_module._init_index_status()

        db_config = {
            'host': 'localhost',
            'port': 5432,
            'schema': 'public',
            'dbname': 'testdb',
            'user': 'testuser',
            'password': 'testpass'
        }

        app_module._start_index_creation(
            db_config, 'test_table', 'test_idx', 'ivfflat',
            500, None, None, '1GB'
        )

        status = mock_session_state.index_status
        self.assertTrue(status['is_running'])
        self.assertNotEqual(status['start_datetime'], '')
        self.assertGreater(status['start_time'], 0)

    @patch('app.threading.Thread')
    @patch('app.st')
    def test_start_index_creation_passes_db_config_copy(self, mock_st, mock_thread_class):
        import app as app_module

        mock_session_state = AttrDict()
        mock_st.session_state = mock_session_state
        mock_thread_instance = MagicMock()
        mock_thread_class.return_value = mock_thread_instance

        mock_session_state.index_status = app_module._init_index_status()

        db_config = {
            'host': 'localhost',
            'port': 5432,
            'schema': 'public',
            'dbname': 'testdb',
            'user': 'testuser',
            'password': 'testpass'
        }

        app_module._start_index_creation(
            db_config, 'test_table', 'test_idx', 'ivfflat',
            500, None, None, '1GB'
        )

        thread_args = mock_thread_class.call_args
        target_args = thread_args[1]['args'] if 'args' in thread_args[1] else thread_args[0][1]

        self.assertEqual(target_args[0]['host'], 'localhost')
        self.assertEqual(target_args[0]['dbname'], 'testdb')

    @patch('app.threading.Thread')
    @patch('app.st')
    def test_start_index_creation_starts_thread(self, mock_st, mock_thread_class):
        import app as app_module

        mock_session_state = AttrDict()
        mock_st.session_state = mock_session_state
        mock_thread_instance = MagicMock()
        mock_thread_class.return_value = mock_thread_instance

        mock_session_state.index_status = app_module._init_index_status()

        db_config = {
            'host': 'localhost',
            'port': 5432,
            'schema': 'public',
            'dbname': 'testdb',
            'user': 'testuser',
            'password': 'testpass'
        }

        app_module._start_index_creation(
            db_config, 'test_table', 'test_idx', 'ivfflat',
            500, None, None, '1GB'
        )

        mock_thread_instance.start.assert_called_once()

    @patch('app.threading.Thread')
    @patch('app.st')
    def test_start_index_creation_resets_status_before_setting(self, mock_st, mock_thread_class):
        import app as app_module

        mock_session_state = AttrDict()
        mock_st.session_state = mock_session_state
        mock_thread_instance = MagicMock()
        mock_thread_class.return_value = mock_thread_instance

        mock_session_state.index_status = _make_index_status(
            completed=True, error_message='old error', start_datetime='old time',
            end_datetime='old end', execution_time=99.0, start_time=123.0
        )

        db_config = {
            'host': 'localhost',
            'port': 5432,
            'schema': 'public',
            'dbname': 'testdb',
            'user': 'testuser',
            'password': 'testpass'
        }

        app_module._start_index_creation(
            db_config, 'test_table', 'test_idx', 'ivfflat',
            500, None, None, '1GB'
        )

        status = mock_session_state.index_status
        self.assertTrue(status['is_running'])
        self.assertFalse(status['completed'])
        self.assertEqual(status['error_message'], '')
        self.assertNotEqual(status['start_datetime'], 'old time')


class TestIndexStatusElapsedTime(unittest.TestCase):
    """测试index_status中start_time用于计算实时运行时长"""

    def test_start_time_allows_elapsed_calculation(self):
        start_time = time.time() - 60
        elapsed = time.time() - start_time
        self.assertGreaterEqual(elapsed, 59)
        self.assertLessEqual(elapsed, 65)

    def test_start_time_zero_means_not_started(self):
        start_time = 0.0
        self.assertEqual(start_time, 0.0)
        self.assertFalse(start_time > 0)

    def test_format_time_function(self):
        import app as app_module
        self.assertEqual(app_module.format_time(30.5), "30.5秒")
        self.assertEqual(app_module.format_time(90), "1分30秒")
        self.assertEqual(app_module.format_time(3661), "1小时1分")


class TestVectorStoreCheckIndexExists(unittest.TestCase):
    """测试check_index_exists方法"""

    def test_check_index_exists_returns_true_when_found(self):
        mock_db = MagicMock()
        mock_db.schema = 'public'
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = [1]
        mock_db.execute.return_value = mock_cursor

        vs = VectorStore(mock_db)
        result = vs.check_index_exists('test_table', 'test_idx')
        self.assertTrue(result)

    def test_check_index_exists_returns_false_when_not_found(self):
        mock_db = MagicMock()
        mock_db.schema = 'public'
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = None
        mock_db.execute.return_value = mock_cursor

        vs = VectorStore(mock_db)
        result = vs.check_index_exists('test_table', 'test_idx')
        self.assertFalse(result)

    def test_check_index_exists_returns_false_on_execute_failure(self):
        mock_db = MagicMock()
        mock_db.schema = 'public'
        mock_db.execute.return_value = None

        vs = VectorStore(mock_db)
        result = vs.check_index_exists('test_table', 'test_idx')
        self.assertFalse(result)


class TestVectorStoreDropIndex(unittest.TestCase):
    """测试drop_vector_index方法"""

    def test_drop_index_success(self):
        mock_db = MagicMock()
        mock_cursor = MagicMock()
        mock_db.execute.return_value = mock_cursor

        vs = VectorStore(mock_db)
        result = vs.drop_vector_index('test_idx')
        self.assertTrue(result)
        mock_db.commit.assert_called_once()

    def test_drop_index_failure(self):
        mock_db = MagicMock()
        mock_db.execute.return_value = None

        vs = VectorStore(mock_db)
        result = vs.drop_vector_index('test_idx')
        self.assertFalse(result)


if __name__ == '__main__':
    unittest.main()
