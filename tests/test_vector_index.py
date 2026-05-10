"""
测试向量索引创建功能

测试内容：
1. ivfflat 索引创建（自动计算 lists）
2. hnsw 索引创建（默认参数）
3. maintenance_work_mem 设置与恢复
4. 索引重复创建跳过
5. 索引删除
6. 索引存在性检查
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from database.connection import DBConnection
from database.vector_store import VectorStore
from config import Config

TEST_TABLE = 'test_vector_index_table'
TEST_INDEX_IVFFLAT = 'test_idx_ivfflat'
TEST_INDEX_HNSW = 'test_idx_hnsw'
VECTOR_DIM = 768


def setup_test_table(vs):
    """创建测试向量表并插入模拟数据"""
    print(f"\n=== 创建测试表 {TEST_TABLE} ===")
    success = vs.create_vector_table_with_dim(TEST_TABLE, VECTOR_DIM, table_type='enterprise')
    print(f"  创建表: {'OK' if success else 'FAIL'}")
    assert success, "表创建失败"

    # 插入1000条模拟向量数据（ivfflat 需要一定数据量才能创建索引）
    print("  插入1000条测试向量...")
    vectors = []
    source_ids = []
    addresses = []
    names = []

    for i in range(1000):
        v = np.random.randn(VECTOR_DIM).astype(np.float32)
        v = v / np.linalg.norm(v)
        vectors.append(v)
        source_ids.append(f"test_{i}")
        addresses.append(f"test_addr_{i}")
        names.append(f"test_ent_{i}")

    vectors_array = np.array(vectors, dtype=np.float32)
    count = vs.insert_vectors(vectors_array, source_ids, addresses, TEST_TABLE, names, table_type='enterprise')
    print(f"  插入数据: {count} 条")
    assert count == 1000, f"期望1000条，实际{count}条"

    row_count = vs.get_vector_count(TEST_TABLE)
    print(f"  表记录数: {row_count}")
    assert row_count == 1000, f"期望1000条，实际{row_count}条"


def test_ivfflat_index(vs):
    """测试 ivfflat 索引创建"""
    print(f"\n=== 测试 ivfflat 索引 ===")
    print(f"  表: {TEST_TABLE}, 索引: {TEST_INDEX_IVFFLAT}")

    # 先确认索引不存在
    exists = vs.check_index_exists(TEST_TABLE, TEST_INDEX_IVFFLAT)
    print(f"  创建前索引存在: {exists}")
    assert not exists

    # 创建索引（自动计算 lists）
    success = vs.create_vector_index(
        table_name=TEST_TABLE,
        index_name=TEST_INDEX_IVFFLAT,
        index_type='ivfflat',
        maintenance_work_mem='256MB'
    )
    print(f"  创建索引: {'OK' if success else 'FAIL'}")
    assert success, "ivfflat 索引创建失败"

    # 验证索引存在
    exists = vs.check_index_exists(TEST_TABLE, TEST_INDEX_IVFFLAT)
    print(f"  创建后索引存在: {exists}")
    assert exists, "索引创建后未找到"

    # 测试重复创建（应跳过）
    success2 = vs.create_vector_index(
        table_name=TEST_TABLE,
        index_name=TEST_INDEX_IVFFLAT,
        index_type='ivfflat'
    )
    print(f"  重复创建: {'跳过' if success2 else 'FAIL'}")
    assert success2, "重复创建应返回True（跳过）"


def test_hnsw_index(vs):
    """测试 hnsw 索引创建"""
    print(f"\n=== 测试 hnsw 索引 ===")
    print(f"  表: {TEST_TABLE}, 索引: {TEST_INDEX_HNSW}")

    # 先确认索引不存在
    exists = vs.check_index_exists(TEST_TABLE, TEST_INDEX_HNSW)
    print(f"  创建前索引存在: {exists}")
    assert not exists

    # 创建索引（使用默认参数 m=16, ef_construction=200）
    success = vs.create_vector_index(
        table_name=TEST_TABLE,
        index_name=TEST_INDEX_HNSW,
        index_type='hnsw',
        m=16,
        ef_construction=200,
        maintenance_work_mem='512MB'
    )
    print(f"  创建索引 (m=16, ef_construction=200): {'OK' if success else 'FAIL'}")
    assert success, "hnsw 索引创建失败"

    # 验证索引存在
    exists = vs.check_index_exists(TEST_TABLE, TEST_INDEX_HNSW)
    print(f"  创建后索引存在: {exists}")
    assert exists, "hnsw 索引创建后未找到"


def test_maintenance_work_mem(vs):
    """测试 maintenance_work_mem 设置与恢复"""
    print(f"\n=== 测试 maintenance_work_mem ===")
    # 通过查询当前值验证（间接测试）
    # 主要验证不会报错
    test_index = 'test_idx_work_mem'
    success = vs.create_vector_index(
        table_name=TEST_TABLE,
        index_name=test_index,
        index_type='ivfflat',
        lists=100,
        maintenance_work_mem='128MB'
    )
    print(f"  设置 maintenance_work_mem=128MB 创建索引: {'OK' if success else 'FAIL'}")
    assert success
    vs.drop_vector_index(test_index)


def test_index_operations(vs):
    """测试索引删除"""
    print(f"\n=== 测试索引删除 ===")

    # 删除 ivfflat 索引
    success = vs.drop_vector_index(TEST_INDEX_IVFFLAT)
    print(f"  删除 {TEST_INDEX_IVFFLAT}: {'OK' if success else 'FAIL'}")
    assert success

    exists = vs.check_index_exists(TEST_TABLE, TEST_INDEX_IVFFLAT)
    print(f"  删除后索引存在: {exists}")
    assert not exists

    # 删除 hnsw 索引
    success = vs.drop_vector_index(TEST_INDEX_HNSW)
    print(f"  删除 {TEST_INDEX_HNSW}: {'OK' if success else 'FAIL'}")
    assert success

    exists = vs.check_index_exists(TEST_TABLE, TEST_INDEX_HNSW)
    print(f"  删除后索引存在: {exists}")
    assert not exists


def cleanup(vs):
    """清理测试数据"""
    print(f"\n=== 清理 ===")
    success = vs.drop_vector_table(TEST_TABLE)
    print(f"  删除表 {TEST_TABLE}: {'OK' if success else 'FAIL'}")


def main():
    print("=" * 60)
    print("向量索引创建功能测试")
    print("=" * 60)

    # 连接数据库
    db = DBConnection(
        host='localhost',
        port=5432,
        schema='public',
        dbname='postgres',
        user='postgres',
        password='123456'
    )

    if not db.connect():
        print("FAIL: 无法连接数据库")
        return 1

    print("数据库连接成功")
    vs = VectorStore(db)

    try:
        setup_test_table(vs)
        test_ivfflat_index(vs)
        test_hnsw_index(vs)
        test_maintenance_work_mem(vs)
        test_index_operations(vs)

        print("\n" + "=" * 60)
        print("ALL TESTS PASSED!")
        print("=" * 60)
        return 0
    except AssertionError as e:
        print(f"\n[FAIL] 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return 1
    except Exception as e:
        print(f"\n[FAIL] 测试异常: {e}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        cleanup(vs)
        db.close()


if __name__ == '__main__':
    sys.exit(main())
