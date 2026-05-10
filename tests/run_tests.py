import sys
sys.path.insert(0, r'd:\pythonProject\address_match')

from database.connection import quote_identifier, DBConnection
from database.vector_store import VectorStore
from database.data_loader import DataLoader
from config import Config
from unittest.mock import MagicMock
import numpy as np

def test_quote_identifier():
    r = quote_identifier('test_table')
    assert r == '"test_table"', f'Expected "test_table", got {r}'
    
    r2 = quote_identifier('')
    assert r2 == '', f'Expected empty, got {r2}'
    
    r3 = quote_identifier(None)
    assert r3 is None, f'Expected None, got {r3}'
    
    r4 = quote_identifier('table"name')
    assert r4 == '"table""name"', f'Expected escaped quotes, got {r4}'
    
    print('quote_identifier: ALL TESTS PASSED')


def test_db_connection_schema():
    db = DBConnection(schema='ai')
    assert db.schema == 'ai', f'Expected ai, got {db.schema}'
    
    db2 = DBConnection()
    assert db2.schema == Config.DB_SCHEMA, f'Expected {Config.DB_SCHEMA}, got {db2.schema}'
    
    print('DBConnection schema: ALL TESTS PASSED')


def test_vector_store_insert_vectors_table_type():
    mock_db = MagicMock()
    mock_db.execute.return_value = MagicMock()
    mock_db.conn.autocommit = True
    mock_db.schema = 'ai'

    vs = VectorStore(mock_db)

    vectors = np.random.rand(2, 768).astype(np.float32)
    source_ids = ['id1', 'id2']
    addresses = ['addr1', 'addr2']

    # 调用不应抛出异常
    vs.insert_vectors(vectors, source_ids, addresses,
                     table_name='enterprise_vectors',
                     extra_data=['name1', 'name2'],
                     table_type='enterprise')

    mock_db2 = MagicMock()
    mock_db2.execute.return_value = MagicMock()
    mock_db2.conn.autocommit = True
    mock_db2.schema = 'ai'

    vs2 = VectorStore(mock_db2)
    vs2.insert_vectors(vectors, source_ids, addresses,
                      table_name='standard_address_vectors',
                      extra_data=['room1', 'room2'],
                      table_type='standard')

    print('VectorStore insert_vectors table_type: ALL TESTS PASSED')


def test_data_loader_recall_table_parameterized():
    mock_db = MagicMock()
    mock_db.execute.return_value = MagicMock()
    mock_db.schema = 'ai'
    
    loader = DataLoader(mock_db)
    
    loader.create_recall_table()
    execute_call = str(mock_db.execute.call_args_list[0])
    assert Config.RECALL_RESULTS_TABLE in execute_call, f'Expected {Config.RECALL_RESULTS_TABLE} in SQL'
    
    mock_db2 = MagicMock()
    mock_db2.execute.return_value = MagicMock()
    mock_db2.schema = 'ai'
    loader2 = DataLoader(mock_db2)
    loader2.create_recall_table(table_name='custom_recall')
    execute_call2 = str(mock_db2.execute.call_args_list[0])
    assert 'custom_recall' in execute_call2, 'Expected custom_recall in SQL'
    
    mock_db3 = MagicMock()
    mock_db3.execute.return_value = MagicMock()
    mock_db3.schema = 'ai'
    loader3 = DataLoader(mock_db3)
    loader3.truncate_recall_table()
    execute_call3 = str(mock_db3.execute.call_args_list[0])
    assert Config.RECALL_RESULTS_TABLE in execute_call3, f'Expected {Config.RECALL_RESULTS_TABLE} in TRUNCATE SQL'
    
    mock_db4 = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = []
    mock_db4.execute.return_value = mock_cursor
    mock_db4.schema = 'ai'
    loader4 = DataLoader(mock_db4)
    loader4.load_recall_results()
    execute_call4 = str(mock_db4.execute.call_args_list[0])
    assert Config.RECALL_RESULTS_TABLE in execute_call4, f'Expected {Config.RECALL_RESULTS_TABLE} in SELECT SQL'
    
    mock_db5 = MagicMock()
    mock_cursor5 = MagicMock()
    mock_cursor5.fetchone.return_value = {'count': 0}
    mock_db5.execute.return_value = mock_cursor5
    mock_db5.schema = 'ai'
    loader5 = DataLoader(mock_db5)
    list(loader5.export_recall_results_batch())
    execute_call5 = str(mock_db5.execute.call_args_list[0])
    assert Config.RECALL_RESULTS_TABLE in execute_call5, f'Expected {Config.RECALL_RESULTS_TABLE} in COUNT SQL'
    
    print('DataLoader recall table parameterized: ALL TESTS PASSED')


def test_config_table_names():
    assert Config.ENTERPRISE_VECTOR_TABLE == 'enterprise_vectors'
    assert Config.STANDARD_VECTOR_TABLE == 'standard_address_vectors'
    assert Config.RECALL_RESULTS_TABLE == 'recall_results'
    assert Config.MATCH_RESULTS_TABLE == 'match_results'
    assert Config.MGEO_SIMILARITY_RESULTS_TABLE == 'mgeo_similarity_results'
    print('Config table names: ALL TESTS PASSED')


if __name__ == '__main__':
    test_quote_identifier()
    test_db_connection_schema()
    test_vector_store_insert_vectors_table_type()
    test_data_loader_recall_table_parameterized()
    test_config_table_names()
    print('\n===== ALL TESTS PASSED =====')
