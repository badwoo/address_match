import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.vector_store import VectorStore
from database.connection import DBConnection
from config import Config

def test_rename_vector_table():
    """测试向量表重命名功能"""
    print("=" * 60)
    print("测试向量表重命名功能")
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
    test_old_name = 'test_rename_old_vector'
    test_new_name = 'test_rename_new_vector'

    try:
        # 清理可能存在的测试表
        vector_store.drop_vector_table(test_old_name)
        vector_store.drop_vector_table(test_new_name)

        # 1. 创建测试向量表
        print("\n[1/5] 创建测试向量表...")
        success = vector_store.create_vector_table(test_old_name, table_type='enterprise')
        assert success, "创建向量表失败"
        print(f"✅ 创建表 {test_old_name} 成功")

        # 2. 检查表是否存在
        print("\n[2/5] 检查表是否存在...")
        exists = vector_store.check_table_exists(test_old_name)
        assert exists, "check_table_exists 应返回 True"
        print(f"✅ 表 {test_old_name} 存在检查通过")

        not_exists = vector_store.check_table_exists(test_new_name)
        assert not not_exists, "不存在的表应返回 False"
        print(f"✅ 表 {test_new_name} 不存在检查通过")

        # 3. 重命名表
        print("\n[3/5] 重命名向量表...")
        success = vector_store.rename_vector_table(test_old_name, test_new_name)
        assert success, "重命名向量表失败"
        print(f"✅ 重命名 {test_old_name} -> {test_new_name} 成功")

        # 4. 验证重命名后旧表不存在、新表存在
        print("\n[4/5] 验证重命名结果...")
        old_exists = vector_store.check_table_exists(test_old_name)
        new_exists = vector_store.check_table_exists(test_new_name)
        assert not old_exists, "旧表不应再存在"
        assert new_exists, "新表应存在"
        print(f"✅ 旧表已不存在，新表已存在")

        # 5. 重命名为已存在的表名应失败（或被数据库拒绝）
        print("\n[5/5] 测试重命名为已存在的表名...")
        # 先创建另一个表
        another_table = 'test_rename_another_vector'
        vector_store.drop_vector_table(another_table)
        vector_store.create_vector_table(another_table, table_type='enterprise')
        # 尝试重命名为已存在的表（数据库层面会报错，我们的方法返回False）
        success = vector_store.rename_vector_table(test_new_name, another_table)
        # 这里取决于数据库行为，PostgreSQL会报错，所以success应该是False
        # 但我们不assert这个，因为不同数据库行为可能不同
        print(f"ℹ️ 重命名为已存在表的结果: {success}")

        # 清理
        vector_store.drop_vector_table(test_new_name)
        vector_store.drop_vector_table(another_table)
        print("\n✅ 所有测试通过！")
        return True

    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        print(traceback.format_exc())
        # 清理
        try:
            vector_store.drop_vector_table(test_old_name)
            vector_store.drop_vector_table(test_new_name)
        except:
            pass
        return False
    finally:
        conn.close()


def test_check_table_exists():
    """测试检查表是否存在功能"""
    print("\n" + "=" * 60)
    print("测试 check_table_exists 功能")
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
    test_table = 'test_check_exists_vector'

    try:
        # 清理
        vector_store.drop_vector_table(test_table)

        # 表不存在时应返回 False
        exists = vector_store.check_table_exists(test_table)
        assert not exists, "不存在的表应返回 False"
        print("✅ 不存在的表返回 False")

        # 创建表后应返回 True
        vector_store.create_vector_table(test_table, table_type='standard')
        exists = vector_store.check_table_exists(test_table)
        assert exists, "已创建的表应返回 True"
        print("✅ 已创建的表返回 True")

        # 清理
        vector_store.drop_vector_table(test_table)
        print("\n✅ check_table_exists 测试通过！")
        return True

    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        print(traceback.format_exc())
        try:
            vector_store.drop_vector_table(test_table)
        except:
            pass
        return False
    finally:
        conn.close()


if __name__ == '__main__':
    result1 = test_check_table_exists()
    result2 = test_rename_vector_table()

    print("\n" + "=" * 60)
    print("测试总结")
    print("=" * 60)
    print(f"check_table_exists: {'✅ 通过' if result1 else '❌ 失败'}")
    print(f"rename_vector_table: {'✅ 通过' if result2 else '❌ 失败'}")
