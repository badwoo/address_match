import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.vector_store import VectorStore
from database.connection import DBConnection
from config import Config

def test_reproduce_bug():
    """复现 '获取数据表列表失败: no results to fetch' 的 bug"""
    print("=" * 60)
    print("复现创建向量表后的 get_tables 报错问题")
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
        print("❌ 数据库连接失败")
        return False

    vector_store = VectorStore(conn)
    test_table = 'test_bug_reproduce_vector'

    try:
        # 清理
        vector_store.drop_vector_table(test_table)

        # 步骤1: 先调用 get_tables (模拟页面加载)
        print("\n[步骤1] 首次调用 get_tables()...")
        tables = conn.get_tables()
        print(f"✅ get_tables() 成功，返回 {len(tables)} 个表")

        # 步骤2: 调用 check_table_exists (模拟我们新增的功能)
        print("\n[步骤2] 调用 check_table_exists()...")
        exists = vector_store.check_table_exists(test_table)
        print(f"✅ check_table_exists() 成功，结果: {exists}")

        # 步骤3: 调用 get_vector_count (模拟我们新增的功能)
        print("\n[步骤3] 调用 get_vector_count()...")
        count = vector_store.get_vector_count(test_table)
        print(f"✅ get_vector_count() 成功，结果: {count}")

        # 步骤4: 创建向量表 (模拟点击创建按钮)
        print("\n[步骤4] 创建向量表...")
        success = vector_store.create_vector_table(test_table, table_type='enterprise')
        print(f"✅ create_vector_table() 成功: {success}")

        # 步骤5: 再次调用 get_tables (模拟 rerun 后的页面加载)
        print("\n[步骤5] 创建表后再次调用 get_tables()...")
        try:
            tables = conn.get_tables()
            print(f"✅ 再次 get_tables() 成功，返回 {len(tables)} 个表")
        except Exception as e:
            print(f"❌ 再次 get_tables() 失败: {e}")
            return False

        # 步骤6: 模拟多次 check + create 组合
        print("\n[步骤6] 模拟多次 check + count + create 组合...")
        for i in range(3):
            exists = vector_store.check_table_exists(test_table)
            count = vector_store.get_vector_count(test_table)
            print(f"  第{i+1}轮: exists={exists}, count={count}")
            tables = conn.get_tables()
            print(f"  第{i+1}轮 get_tables: {len(tables)} 个表")

        print("\n✅ 所有步骤通过，未复现 bug")
        return True

    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        print(traceback.format_exc())
        return False
    finally:
        try:
            vector_store.drop_vector_table(test_table)
        except:
            pass
        conn.close()


def test_check_connection_side_effect():
    """测试 _check_connection 是否会影响后续查询"""
    print("\n" + "=" * 60)
    print("测试 _check_connection 副作用")
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
        print("❌ 数据库连接失败")
        return False

    try:
        # 步骤1: 正常查询
        print("\n[步骤1] 正常执行查询...")
        cursor = conn.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = %s LIMIT 5", (Config.DB_SCHEMA,))
        results1 = cursor.fetchall()
        print(f"✅ 首次查询成功，返回 {len(results1)} 条")

        # 步骤2: 调用 _check_connection
        print("\n[步骤2] 调用 _check_connection...")
        ok = conn._check_connection()
        print(f"✅ _check_connection 返回: {ok}")

        # 步骤3: 再次执行同样的查询
        print("\n[步骤3] 再次执行查询...")
        cursor = conn.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = %s LIMIT 5", (Config.DB_SCHEMA,))
        results2 = cursor.fetchall()
        print(f"✅ 再次查询成功，返回 {len(results2)} 条")

        # 步骤4: 多次调用 _check_connection 后查询
        print("\n[步骤4] 多次调用 _check_connection 后查询...")
        for i in range(5):
            conn._check_connection()
        cursor = conn.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = %s LIMIT 5", (Config.DB_SCHEMA,))
        results3 = cursor.fetchall()
        print(f"✅ 多次 check 后查询成功，返回 {len(results3)} 条")

        print("\n✅ _check_connection 无副作用")
        return True

    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        print(traceback.format_exc())
        return False
    finally:
        conn.close()


def test_cursor_state_after_fetchone():
    """测试 fetchone 后 cursor 状态"""
    print("\n" + "=" * 60)
    print("测试 fetchone 后 cursor 状态")
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
        print("❌ 数据库连接失败")
        return False

    try:
        # 步骤1: 执行查询并 fetchone
        print("\n[步骤1] 执行查询并 fetchone...")
        cursor = conn.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = %s LIMIT 5", (Config.DB_SCHEMA,))
        row = cursor.fetchone()
        print(f"✅ fetchone 成功: {row}")

        # 步骤2: 在同一个 cursor 上再次 fetchall
        print("\n[步骤2] 同一 cursor 再次 fetchall...")
        try:
            rows = cursor.fetchall()
            print(f"✅ 再次 fetchall 成功，返回 {len(rows)} 条")
        except Exception as e:
            print(f"❌ 再次 fetchall 失败: {e}")

        # 步骤3: 执行新查询
        print("\n[步骤3] 执行新查询...")
        cursor = conn.execute("SELECT COUNT(*) as cnt FROM information_schema.tables WHERE table_schema = %s", (Config.DB_SCHEMA,))
        row = cursor.fetchone()
        print(f"✅ 新查询成功: {row}")

        print("\n✅ cursor 状态测试完成")
        return True

    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        print(traceback.format_exc())
        return False
    finally:
        conn.close()


if __name__ == '__main__':
    r1 = test_reproduce_bug()
    r2 = test_check_connection_side_effect()
    r3 = test_cursor_state_after_fetchone()

    print("\n" + "=" * 60)
    print("测试总结")
    print("=" * 60)
    print(f"复现测试: {'✅ 通过' if r1 else '❌ 失败'}")
    print(f"_check_connection 副作用: {'✅ 通过' if r2 else '❌ 失败'}")
    print(f"cursor 状态: {'✅ 通过' if r3 else '❌ 失败'}")
