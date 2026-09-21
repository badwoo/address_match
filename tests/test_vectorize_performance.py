import sys
import os
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.vector_store import VectorStore
from database.connection import DBConnection
from config import Config


def test_encode_batch_size_auto_select():
    print("=" * 60)
    print("test encode batch_size auto select by device")
    print("=" * 60)

    from model.embedding import AddressEmbedder

    print("\n[1/2] test default batch_size for CPU mode...")
    embedder = AddressEmbedder(device='cpu')
    assert embedder.device == 'cpu', f"device should be cpu, got {embedder.device}"

    vectors = embedder.encode(["北京市朝阳区建国路1号"])
    assert vectors.shape[0] == 1, f"should produce 1 vector, got {vectors.shape[0]}"
    assert vectors.shape[1] == embedder.vector_dim, f"dim mismatch: {vectors.shape[1]} vs {embedder.vector_dim}"
    norm = np.linalg.norm(vectors[0])
    assert abs(norm - 1.0) < 0.01, f"vector should be L2-normalized, norm={norm}"
    print(f"  CPU encode OK: shape={vectors.shape}, norm={norm:.6f}")

    print("\n[2/2] test explicit batch_size override...")
    vectors_large = embedder.encode(["北京市朝阳区建国路1号"] * 10, batch_size=4)
    assert vectors_large.shape[0] == 10, f"should produce 10 vectors, got {vectors_large.shape[0]}"
    for i in range(10):
        norm_i = np.linalg.norm(vectors_large[i])
        assert abs(norm_i - 1.0) < 0.01, f"vector {i} not normalized, norm={norm_i}"
    print(f"  batch_size=4 encode OK: shape={vectors_large.shape}")

    print("\n[PASS] test_encode_batch_size_auto_select")
    return True


def test_fp16_inference():
    print("=" * 60)
    print("test FP16 half precision inference (GPU only)")
    print("=" * 60)

    import torch
    if not torch.cuda.is_available():
        print("[SKIP] CUDA not available, skip FP16 test")
        return True

    from model.embedding import AddressEmbedder

    print("\n[1/3] test FP16 model loading on GPU...")
    embedder = AddressEmbedder(device='cuda')
    assert embedder.device == 'cuda', f"device should be cuda, got {embedder.device}"
    assert embedder.use_fp16 is True, f"use_fp16 should be True on GPU"
    print(f"  GPU embedder loaded: use_fp16={embedder.use_fp16}")

    print("\n[2/3] test FP16 encode produces correct results...")
    test_addresses = ["北京市朝阳区建国路1号", "上海市浦东新区陆家嘴环路1000号", "广州市天河区天河路385号"]
    vectors = embedder.encode(test_addresses)
    assert vectors.shape[0] == 3, f"should produce 3 vectors, got {vectors.shape[0]}"
    assert vectors.dtype == np.float32 or vectors.dtype == np.float64, f"output should be float32/64, got {vectors.dtype}"
    for i in range(3):
        norm_i = np.linalg.norm(vectors[i])
        assert abs(norm_i - 1.0) < 0.01, f"vector {i} not normalized, norm={norm_i}"
    print(f"  FP16 encode OK: shape={vectors.shape}, all normalized")

    print("\n[3/3] compare FP16 vs FP32 result consistency...")
    embedder_fp32 = AddressEmbedder.__new__(AddressEmbedder)
    embedder_fp32.model_name = Config.EMBEDDING_MODEL_NAME
    embedder_fp32.device = 'cuda'
    embedder_fp32.vector_dim = 768
    embedder_fp32.use_fp16 = False
    embedder_fp32._load_model()
    vectors_fp32 = embedder_fp32.encode(test_addresses, batch_size=3)

    cos_sims = []
    for i in range(3):
        dot = np.dot(vectors[i], vectors_fp32[i])
        cos_sims.append(dot)
    min_sim = min(cos_sims)
    avg_sim = sum(cos_sims) / len(cos_sims)
    print(f"  FP16 vs FP32 cosine similarity: min={min_sim:.6f}, avg={avg_sim:.6f}")
    assert min_sim > 0.99, f"FP16 vs FP32 similarity too low: {min_sim}"

    print("\n[PASS] test_fp16_inference")
    return True


def test_vectors_to_pg_strings_batch():
    print("=" * 60)
    print("test _vectors_to_pg_strings batch conversion")
    print("=" * 60)

    print("\n[1/4] test single vector conversion...")
    vec = np.array([0.1, 0.2, 0.3, 0.4], dtype=np.float32)
    single_result = VectorStore._vector_to_pg_string(vec)
    batch_result = VectorStore._vectors_to_pg_strings(vec.reshape(1, -1))
    assert len(batch_result) == 1, f"should return 1 string, got {len(batch_result)}"
    assert single_result == batch_result[0], "single and batch results should match"
    print(f"  single vector OK: {batch_result[0][:30]}...")

    print("\n[2/4] test multiple vectors conversion...")
    vectors = np.array([
        [0.1, 0.2, 0.3, 0.4],
        [0.5, 0.6, 0.7, 0.8],
        [-0.1, -0.2, -0.3, -0.4],
    ], dtype=np.float32)
    results = VectorStore._vectors_to_pg_strings(vectors)
    assert len(results) == 3, f"should return 3 strings, got {len(results)}"
    for i in range(3):
        expected = VectorStore._vector_to_pg_string(vectors[i])
        assert results[i] == expected, f"vector {i}: batch result doesn't match individual conversion"
    print(f"  3 vectors batch conversion OK")

    print("\n[3/4] test 768-dim vectors (real model output)...")
    dim = 768
    np.random.seed(42)
    vectors_768 = np.random.randn(10, dim).astype(np.float32)
    norms = np.linalg.norm(vectors_768, axis=1, keepdims=True)
    vectors_768 = vectors_768 / norms

    results_768 = VectorStore._vectors_to_pg_strings(vectors_768)
    assert len(results_768) == 10, f"should return 10 strings, got {len(results_768)}"

    for i in range(10):
        expected = VectorStore._vector_to_pg_string(vectors_768[i])
        assert results_768[i] == expected, f"768-dim vector {i}: mismatch"

        parsed = np.array([float(x) for x in results_768[i].strip('[]').split(',')])
        assert len(parsed) == dim, f"parsed dim should be {dim}, got {len(parsed)}"
        max_diff = np.max(np.abs(parsed - vectors_768[i]))
        assert max_diff < 1e-6, f"round-trip error too large: {max_diff}"
    print(f"  768-dim vectors batch conversion OK, round-trip verified")

    print("\n[4/4] test batch vs individual performance (quick check)...")
    import time
    large_vectors = np.random.randn(1000, dim).astype(np.float32)
    norms = np.linalg.norm(large_vectors, axis=1, keepdims=True)
    large_vectors = large_vectors / norms

    t0 = time.time()
    individual_results = [VectorStore._vector_to_pg_string(large_vectors[i]) for i in range(1000)]
    t_individual = time.time() - t0

    t0 = time.time()
    batch_results = VectorStore._vectors_to_pg_strings(large_vectors)
    t_batch = time.time() - t0

    assert len(batch_results) == 1000
    for i in range(0, 1000, 100):
        assert batch_results[i] == individual_results[i], f"mismatch at index {i}"

    speedup = t_individual / t_batch if t_batch > 0 else float('inf')
    print(f"  individual: {t_individual:.3f}s, batch: {t_batch:.3f}s, speedup: {speedup:.2f}x")

    print("\n[PASS] test_vectors_to_pg_strings_batch")
    return True


def test_prefetch_mechanism():
    print("=" * 60)
    print("test prefetch mechanism logic")
    print("=" * 60)

    from concurrent.futures import ThreadPoolExecutor

    print("\n[1/3] test basic prefetch with simple iterator...")
    data = list(range(10))

    def data_loader():
        for item in data:
            yield item

    executor = ThreadPoolExecutor(max_workers=1)
    loader_iter = iter(data_loader())

    results = []
    prefetch_future = executor.submit(lambda: next(loader_iter, None))

    while True:
        try:
            if prefetch_future is not None:
                item = prefetch_future.result()
                prefetch_future = None
            else:
                item = next(loader_iter, None)
        except StopIteration:
            item = None

        if item is None:
            break

        prefetch_future = executor.submit(lambda: next(loader_iter, None))
        results.append(item)

    executor.shutdown(wait=True)
    assert results == data, f"prefetch results mismatch: {results} vs {data}"
    print(f"  basic prefetch OK: got {len(results)} items")

    print("\n[2/3] test prefetch with DataFrame-like data...")
    import pandas as pd

    df_data = [{'id': i, 'address': f'地址{i}'} for i in range(20)]

    def df_loader():
        for i in range(0, len(df_data), 5):
            yield pd.DataFrame(df_data[i:i+5])

    executor = ThreadPoolExecutor(max_workers=1)
    loader_iter = iter(df_loader())

    all_rows = []
    prefetch_future = executor.submit(lambda: next(loader_iter, None))

    while True:
        try:
            if prefetch_future is not None:
                df = prefetch_future.result()
                prefetch_future = None
            else:
                df = next(loader_iter, None)
        except StopIteration:
            df = None

        if df is None:
            break

        prefetch_future = executor.submit(lambda: next(loader_iter, None))
        all_rows.extend(df.to_dict('records'))

    executor.shutdown(wait=True)
    assert len(all_rows) == 20, f"should get 20 rows, got {len(all_rows)}"
    for i, row in enumerate(all_rows):
        assert row['id'] == i, f"row {i} id mismatch: {row['id']} vs {i}"
    print(f"  DataFrame prefetch OK: got {len(all_rows)} rows")

    print("\n[3/3] test prefetch with empty iterator...")
    executor = ThreadPoolExecutor(max_workers=1)

    def empty_loader():
        return
        yield

    loader_iter = iter(empty_loader())
    prefetch_future = executor.submit(lambda: next(loader_iter, None))
    item = prefetch_future.result()
    assert item is None, f"empty iterator should return None, got {item}"
    executor.shutdown(wait=True)
    print(f"  empty iterator prefetch OK")

    print("\n[PASS] test_prefetch_mechanism")
    return True


def test_insert_vectors_with_batch_conversion():
    print("=" * 60)
    print("test insert_vectors with batch string conversion")
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
    test_table = 'test_batch_vec_insert'

    try:
        vector_store.drop_vector_table(test_table)

        print("\n[1/3] create test table and insert vectors...")
        vector_store.create_vector_table_with_dim(test_table, 768, table_type='enterprise')

        np.random.seed(42)
        vectors = np.random.randn(50, 768).astype(np.float32)
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        vectors = vectors / norms

        source_ids = [f'ID_{i:04d}' for i in range(50)]
        addresses = [f'测试地址{i}' for i in range(50)]
        extra_data = [f'企业{i}' for i in range(50)]

        inserted = vector_store.insert_vectors(
            vectors, source_ids, addresses, test_table,
            extra_data=extra_data, table_type='enterprise',
            insert_chunk_size=20
        )
        assert inserted == 50, f"should insert 50 rows, got {inserted}"
        print(f"  inserted {inserted} rows")

        print("\n[2/3] verify inserted data...")
        count = vector_store.get_vector_count(test_table)
        assert count == 50, f"should have 50 rows, got {count}"

        cursor = conn.execute(f"SELECT source_id, enterprise_name, address FROM {test_table} ORDER BY id LIMIT 3")
        rows = cursor.fetchall()
        assert len(rows) == 3
        assert rows[0]['source_id'] == 'ID_0000'
        assert rows[0]['enterprise_name'] == '企业0'
        assert rows[0]['address'] == '测试地址0'
        print(f"  data verification OK")

        print("\n[3/3] verify vector normalization in DB...")
        cursor = conn.execute(f"SELECT source_id, 1 - ((vector <-> vector)^2 / 2.0) as self_ip FROM {test_table} LIMIT 5")
        rows = cursor.fetchall()
        for row in rows:
            self_ip = row['self_ip']
            assert abs(self_ip - 1.0) < 0.1, f"vector {row['source_id']} not normalized, self_ip={self_ip}"
        print(f"  vector normalization OK")

    finally:
        vector_store.drop_vector_table(test_table)
        conn.close()

    print("\n[PASS] test_insert_vectors_with_batch_conversion")
    return True


if __name__ == '__main__':
    results = {}

    tests = [
        ('encode_batch_size_auto_select', test_encode_batch_size_auto_select),
        ('fp16_inference', test_fp16_inference),
        ('vectors_to_pg_strings_batch', test_vectors_to_pg_strings_batch),
        ('prefetch_mechanism', test_prefetch_mechanism),
        ('insert_vectors_with_batch_conversion', test_insert_vectors_with_batch_conversion),
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
