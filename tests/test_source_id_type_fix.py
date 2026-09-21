import sys
import os
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.vector_store import VectorStore
from database.connection import DBConnection
from database.data_loader import DataLoader
from config import Config


def test_insert_vectors_with_integer_source_ids():
    print("=" * 60)
    print("test insert_vectors with integer source_ids")
    print("=" * 60)

    conn = DBConnection(
        host=Config.DB_HOST,
        port=Config.DB_PORT,
        schema=Config.DB_SCHEMA,
        dbname=Config.DB_NAME,
        user=Config.DB_USER,
        password=Config.DB_PASSWORD
    )

    if not conn.connect():
        print("[SKIP] database connection failed")
        return True

    vector_store = VectorStore(conn)
    test_table = 'test_int_source_id_vec'

    try:
        vector_store.drop_vector_table(test_table)

        print("\n[1/4] create test table and insert with INTEGER source_ids...")
        vector_store.create_vector_table_with_dim(test_table, 768, table_type='enterprise')

        np.random.seed(42)
        vectors = np.random.randn(5, 768).astype(np.float32)
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        vectors = vectors / norms

        source_ids_int = [4001, 4002, 4003, 4004, 4005]
        addresses = [f'测试地址{i}' for i in range(5)]
        extra_data = [f'企业{i}' for i in range(5)]

        inserted = vector_store.insert_vectors(
            vectors, source_ids_int, addresses, test_table,
            extra_data=extra_data, table_type='enterprise'
        )
        assert inserted == 5, f"should insert 5 rows, got {inserted}"
        print(f"  inserted {inserted} rows with integer source_ids")

        print("\n[2/4] verify data in DB (source_id column is VARCHAR)...")
        count = vector_store.get_vector_count(test_table)
        assert count == 5, f"should have 5 rows, got {count}"

        cursor = conn.execute(f"SELECT source_id, enterprise_name FROM {test_table} ORDER BY id")
        rows = cursor.fetchall()
        for i, row in enumerate(rows):
            assert row['source_id'] == str(source_ids_int[i]), \
                f"source_id mismatch: expected '{source_ids_int[i]}', got '{row['source_id']}'"
            assert isinstance(row['source_id'], str), \
                f"source_id should be str, got {type(row['source_id'])}"
        print(f"  all source_ids stored correctly as VARCHAR strings")

        print("\n[3/4] verify _verify_inserted_vectors works with integer source_ids...")
        vector_store._verify_inserted_vectors(test_table, source_ids_int[:3])
        print(f"  _verify_inserted_vectors succeeded with integer source_ids")

        print("\n[4/4] verify query with integer source_id works...")
        cursor = conn.execute(f"SELECT source_id FROM {test_table} WHERE source_id = %s", ('4003',))
        assert cursor is not None, "cursor should not be None"
        row = cursor.fetchone()
        assert row is not None, "should find row with source_id=4003"
        assert row['source_id'] == '4003', f"expected '4003', got '{row['source_id']}'"
        print(f"  query with string param works: found source_id='{row['source_id']}'")

    finally:
        vector_store.drop_vector_table(test_table)
        conn.close()

    print("\n[PASS] test_insert_vectors_with_integer_source_ids")
    return True


def test_data_loader_id_column_str_conversion():
    print("=" * 60)
    print("test data_loader id column str conversion")
    print("=" * 60)

    conn = DBConnection(
        host=Config.DB_HOST,
        port=Config.DB_PORT,
        schema=Config.DB_SCHEMA,
        dbname=Config.DB_NAME,
        user=Config.DB_USER,
        password=Config.DB_PASSWORD
    )

    if not conn.connect():
        print("[SKIP] database connection failed")
        return True

    data_loader = DataLoader(conn)

    test_enterprise_table = 'test_int_id_enterprise'
    test_standard_table = 'test_int_id_standard'

    try:
        conn.execute(f"DROP TABLE IF EXISTS {test_enterprise_table}")
        conn.execute(f"DROP TABLE IF EXISTS {test_standard_table}")
        conn.commit()

        print("\n[1/5] create test tables with INTEGER id columns...")
        conn.execute(f"""
            CREATE TABLE {test_enterprise_table} (
                id SERIAL PRIMARY KEY,
                enterprise_name TEXT,
                address TEXT NOT NULL
            )
        """)
        conn.execute(f"""
            CREATE TABLE {test_standard_table} (
                id SERIAL PRIMARY KEY,
                address TEXT NOT NULL,
                room_no VARCHAR(100)
            )
        """)
        conn.commit()

        print("\n[2/5] insert test data with auto-increment integer ids...")
        for i in range(10):
            conn.execute(
                f"INSERT INTO {test_enterprise_table} (enterprise_name, address) VALUES (%s, %s)",
                (f'企业{i}', f'测试地址{i}号')
            )
        for i in range(10):
            conn.execute(
                f"INSERT INTO {test_standard_table} (address, room_no) VALUES (%s, %s)",
                (f'标准地址{i}号', f'房间{i}')
            )
        conn.commit()

        print("\n[3/5] test load_enterprise_data returns str ids...")
        for df in data_loader.load_enterprise_data(
            test_enterprise_table, 'id', 'enterprise_name', 'address', batch_size=5
        ):
            for val in df['id'].tolist():
                assert isinstance(val, str), f"enterprise id should be str, got {type(val)}: {val}"
            print(f"  enterprise batch: ids={df['id'].tolist()}, all str ✓")

        print("\n[4/5] test load_standard_addresses returns str ids...")
        for df in data_loader.load_standard_addresses(
            test_standard_table, 'id', 'address', 'room_no', batch_size=5
        ):
            for val in df['id'].tolist():
                assert isinstance(val, str), f"standard id should be str, got {type(val)}: {val}"
            print(f"  standard batch: ids={df['id'].tolist()}, all str ✓")

        print("\n[5/5] test end-to-end: load → insert_vectors with integer source table...")
        vector_store = VectorStore(conn)
        vec_table = 'test_int_id_vec'
        vector_store.drop_vector_table(vec_table)
        vector_store.create_vector_table_with_dim(vec_table, 768, table_type='enterprise')

        np.random.seed(42)
        for df in data_loader.load_enterprise_data(
            test_enterprise_table, 'id', 'enterprise_name', 'address', batch_size=5
        ):
            addresses = df['address'].tolist()
            source_ids = df['id'].tolist()
            names = df['name'].tolist()

            vectors = np.random.randn(len(addresses), 768).astype(np.float32)
            norms = np.linalg.norm(vectors, axis=1, keepdims=True)
            vectors = vectors / norms

            inserted = vector_store.insert_vectors(
                vectors, source_ids, addresses, vec_table,
                extra_data=names, table_type='enterprise'
            )
            assert inserted == len(addresses), f"inserted {inserted} != expected {len(addresses)}"

        count = vector_store.get_vector_count(vec_table)
        assert count == 10, f"should have 10 rows, got {count}"
        print(f"  end-to-end: inserted {count} rows successfully")

        vector_store.drop_vector_table(vec_table)

    finally:
        conn.execute(f"DROP TABLE IF EXISTS {test_enterprise_table}")
        conn.execute(f"DROP TABLE IF EXISTS {test_standard_table}")
        conn.commit()
        conn.close()

    print("\n[PASS] test_data_loader_id_column_str_conversion")
    return True


def test_correction_methods_with_integer_ids():
    print("=" * 60)
    print("test correction methods with integer enterprise_id")
    print("=" * 60)

    conn = DBConnection(
        host=Config.DB_HOST,
        port=Config.DB_PORT,
        schema=Config.DB_SCHEMA,
        dbname=Config.DB_NAME,
        user=Config.DB_USER,
        password=Config.DB_PASSWORD
    )

    if not conn.connect():
        print("[SKIP] database connection failed")
        return True

    data_loader = DataLoader(conn)
    test_match_table = 'test_int_id_match'

    try:
        conn.execute(f"DROP TABLE IF EXISTS {test_match_table}")
        conn.commit()

        print("\n[1/3] create match results table and insert test data...")
        data_loader.create_result_table(table_name=test_match_table)

        test_results = [
            {
                'enterprise_id': 4001,
                'enterprise_name': '测试企业1',
                'enterprise_address': '地址1',
                'address_id': 5001,
                'standard_address': '标准地址1',
                'room_no': 'A101',
                'partial_match': 0.1,
                'exact_match': 0.8,
                'not_match': 0.1,
                'match_status': '精确匹配'
            },
            {
                'enterprise_id': 4002,
                'enterprise_name': '测试企业2',
                'enterprise_address': '地址2',
                'address_id': 5002,
                'standard_address': '标准地址2',
                'room_no': 'B202',
                'partial_match': 0.3,
                'exact_match': 0.2,
                'not_match': 0.5,
                'match_status': '不匹配'
            }
        ]
        inserted = data_loader.insert_match_results(test_results, table_name=test_match_table)
        assert inserted == 2, f"should insert 2 rows, got {inserted}"
        print(f"  inserted {inserted} match results with integer ids")

        print("\n[2/3] test update_match_result_with_correction with integer ids...")
        success = data_loader.update_match_result_with_correction(
            enterprise_id=4001,
            standard_id=5003,
            standard_address='纠正后地址',
            room_no='C303',
            table_name=test_match_table
        )
        assert success, "update_match_result_with_correction should succeed with integer ids"

        cursor = conn.execute(f"SELECT enterprise_id, address_id, standard_address FROM {test_match_table} WHERE enterprise_id = %s", ('4001',))
        assert cursor is not None, "cursor should not be None"
        row = cursor.fetchone()
        assert row is not None, "should find updated row"
        assert row['address_id'] == '5003', f"expected '5003', got '{row['address_id']}'"
        assert row['standard_address'] == '纠正后地址'
        print(f"  correction with integer ids OK: address_id='{row['address_id']}'")

        print("\n[3/3] test direct_correct_match_result with integer ids...")
        success = data_loader.direct_correct_match_result(
            enterprise_id=4002,
            address_id=5004,
            standard_address='直接纠正地址',
            room_no='D404',
            table_name=test_match_table
        )
        assert success, "direct_correct_match_result should succeed with integer ids"

        cursor = conn.execute(f"SELECT enterprise_id, address_id, standard_address FROM {test_match_table} WHERE enterprise_id = %s", ('4002',))
        assert cursor is not None, "cursor should not be None"
        row = cursor.fetchone()
        assert row is not None, "should find updated row"
        assert row['address_id'] == '5004', f"expected '5004', got '{row['address_id']}'"
        assert row['standard_address'] == '直接纠正地址'
        print(f"  direct correction with integer ids OK: address_id='{row['address_id']}'")

    finally:
        conn.execute(f"DROP TABLE IF EXISTS {test_match_table}")
        conn.commit()
        conn.close()

    print("\n[PASS] test_correction_methods_with_integer_ids")
    return True


def test_get_recall_results_by_enterprise_ids_with_int():
    print("=" * 60)
    print("test get_recall_results_by_enterprise_ids with integer ids")
    print("=" * 60)

    conn = DBConnection(
        host=Config.DB_HOST,
        port=Config.DB_PORT,
        schema=Config.DB_SCHEMA,
        dbname=Config.DB_NAME,
        user=Config.DB_USER,
        password=Config.DB_PASSWORD
    )

    if not conn.connect():
        print("[SKIP] database connection failed")
        return True

    data_loader = DataLoader(conn)
    test_recall_table = 'test_int_id_recall'

    try:
        conn.execute(f"DROP TABLE IF EXISTS {test_recall_table}")
        conn.commit()

        print("\n[1/2] create recall results table and insert test data...")
        data_loader.create_recall_table(table_name=test_recall_table)

        test_results = [
            {
                'enterprise_id': 4001,
                'enterprise_name': '企业1',
                'enterprise_address': '地址1',
                'candidates': [
                    {'source_id': 5001, 'address': '标准地址1', 'room_no': 'A101', 'similarity': 0.95},
                    {'source_id': 5002, 'address': '标准地址2', 'room_no': 'A102', 'similarity': 0.85},
                ]
            },
            {
                'enterprise_id': 4002,
                'enterprise_name': '企业2',
                'enterprise_address': '地址2',
                'candidates': [
                    {'source_id': 5003, 'address': '标准地址3', 'room_no': 'B201', 'similarity': 0.90},
                ]
            }
        ]
        inserted = data_loader.insert_recall_results(test_results, table_name=test_recall_table)
        assert inserted == 3, f"should insert 3 rows, got {inserted}"
        print(f"  inserted {inserted} recall results with integer ids")

        print("\n[2/2] test get_recall_results_by_enterprise_ids with integer ids...")
        df = data_loader.get_recall_results_by_enterprise_ids(
            [4001, 4002], table_name=test_recall_table
        )
        assert not df.empty, "should get results"
        assert len(df) == 3, f"should get 3 rows, got {len(df)}"
        print(f"  query with integer enterprise_ids OK: got {len(df)} rows")

    finally:
        conn.execute(f"DROP TABLE IF EXISTS {test_recall_table}")
        conn.commit()
        conn.close()

    print("\n[PASS] test_get_recall_results_by_enterprise_ids_with_int")
    return True


if __name__ == '__main__':
    results = {}

    tests = [
        ('insert_vectors_with_integer_source_ids', test_insert_vectors_with_integer_source_ids),
        ('data_loader_id_column_str_conversion', test_data_loader_id_column_str_conversion),
        ('correction_methods_with_integer_ids', test_correction_methods_with_integer_ids),
        ('get_recall_results_by_enterprise_ids_with_int', test_get_recall_results_by_enterprise_ids_with_int),
    ]

    for name, test_fn in tests:
        try:
            passed = test_fn()
            results[name] = 'PASS' if passed else 'FAIL'
        except Exception as e:
            results[name] = f'ERROR: {e}'
            import traceback
            traceback.print_exc()

    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    for name, result in results.items():
        status = '✅' if result == 'PASS' else '❌'
        print(f"  {status} {name}: {result}")

    all_passed = all(r == 'PASS' for r in results.values())
    print(f"\n{'ALL TESTS PASSED' if all_passed else 'SOME TESTS FAILED'}")
