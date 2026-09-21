import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.vector_store import VectorStore
from database.connection import DBConnection
from config import Config

def test_get_vector_table_detail():
    """测试获取向量表详情功能"""
    print("=" * 60)
    print("测试获取向量表详情功能")
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
        print("❌ 数据库连接失败，跳过测试")
        return False

    vector_store = VectorStore(conn)
    test_table = 'test_detail_vector_table'

    try:
        # 清理
        vector_store.drop_vector_table(test_table)

        # 1. 创建测试向量表
        print("\n[1/4] 创建测试向量表...")
        success = vector_store.create_vector_table(test_table, table_type='enterprise')
        assert success, "创建向量表失败"
        print(f"✅ 创建表 {test_table} 成功")

        # 2. 获取空表的详情
        print("\n[2/4] 获取空表详情...")
        detail = vector_store.get_vector_table_detail(test_table)
        assert detail is not None, "获取详情不应返回 None"
        assert detail['table_name'] == test_table, "表名应匹配"
        assert detail['row_count'] == 0, "空表数据量应为 0"
        assert detail['vector_dim'] == Config.VECTOR_DIM, f"向量维度应为 {Config.VECTOR_DIM}"
        assert len(detail['columns']) > 0, "应有字段信息"
        assert detail['table_size'] is not None, "表大小不应为 None"
        print(f"✅ 空表详情获取成功")
        print(f"   表名: {detail['table_name']}")
        print(f"   数据量: {detail['row_count']}")
        print(f"   向量维度: {detail['vector_dim']}")
        print(f"   字段数: {len(detail['columns'])}")
        print(f"   表大小: {detail['table_size']}")

        # 3. 验证字段结构
        print("\n[3/4] 验证字段结构...")
        col_names = [c[0] for c in detail['columns']]
        assert 'id' in col_names, "应有 id 字段"
        assert 'source_id' in col_names, "应有 source_id 字段"
        assert 'address' in col_names, "应有 address 字段"
        assert 'vector' in col_names, "应有 vector 字段"
        assert 'created_at' in col_names, "应有 created_at 字段"
        assert 'enterprise_name' in col_names, "企业表应有 enterprise_name 字段"
        print(f"✅ 字段结构验证通过: {col_names}")

        # 4. 创建标准地址类型表验证字段差异
        print("\n[4/4] 验证标准地址表字段结构...")
        std_table = 'test_detail_standard_vector'
        vector_store.drop_vector_table(std_table)
        vector_store.create_vector_table(std_table, table_type='standard')
        std_detail = vector_store.get_vector_table_detail(std_table)
        assert std_detail is not None, "获取标准地址表详情不应返回 None"
        std_col_names = [c[0] for c in std_detail['columns']]
        assert 'room_no' in std_col_names, "标准地址表应有 room_no 字段"
        assert 'enterprise_name' not in std_col_names, "标准地址表不应有 enterprise_name 字段"
        print(f"✅ 标准地址表字段验证通过: {std_col_names}")

        # 清理
        vector_store.drop_vector_table(test_table)
        vector_store.drop_vector_table(std_table)

        print("\n✅ 所有向量表详情测试通过！")
        return True

    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        print(traceback.format_exc())
        try:
            vector_store.drop_vector_table(test_table)
            vector_store.drop_vector_table('test_detail_standard_vector')
        except:
            pass
        return False
    finally:
        conn.close()


if __name__ == '__main__':
    result = test_get_vector_table_detail()

    print("\n" + "=" * 60)
    print("测试总结")
    print("=" * 60)
    print(f"get_vector_table_detail: {'✅ 通过' if result else '❌ 失败'}")
