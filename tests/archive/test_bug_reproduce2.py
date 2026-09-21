import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.vector_store import VectorStore
from database.connection import DBConnection
from config import Config

def test_streamlit_rerun_simulation():
    """
    模拟 Streamlit rerun 场景：
    1. 第一次页面加载：get_tables -> check_exists -> get_count
    2. 用户点击创建按钮 -> create_table -> rerun
    3. 第二次页面加载：get_tables (此时可能报错)
    """
    print("=" * 60)
    print("模拟 Streamlit rerun 场景")
    print("=" * 60)

    # 模拟第一次页面加载 - 创建连接
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
    test_table = 'test_rerun_simulation_vector'

    try:
        # 清理
        vector_store.drop_vector_table(test_table)

        # ===== 第一次页面加载 =====
        print("\n[第一次页面加载]")

        # 1. get_tables
        tables = conn.get_tables()
        print(f"  get_tables: {len(tables)} 个表")

        # 2. 获取当前配置的向量表名及存在状态（这是我们新增的功能）
        ent_vec_table = test_table
        ent_table_exists = vector_store.check_table_exists(ent_vec_table)
        ent_count_in_table = vector_store.get_vector_count(ent_vec_table) if ent_table_exists else 0
        print(f"  check_table_exists({ent_vec_table}): {ent_table_exists}")
        print(f"  get_vector_count({ent_vec_table}): {ent_count_in_table}")

        # 3. 用户点击创建按钮 -> create_vector_table
        print("\n[用户点击创建按钮]")
        success = vector_store.create_vector_table(test_table, table_type='enterprise')
        print(f"  create_vector_table: {success}")

        # 4. st.rerun() 被调用 - 模拟 rerun：重新获取连接
        print("\n[模拟 st.rerun() - 重新获取连接]")
        # 关闭旧连接，创建新连接（模拟 Streamlit 缓存 TTL 过期或新连接）
        conn.close()

        conn2 = DBConnection(
            host=Config.DB_HOST,
            port=Config.DB_PORT,
            schema=Config.DB_SCHEMA,
            dbname=Config.DB_NAME,
            user=Config.DB_USER,
            password=Config.DB_PASSWORD
        )
        conn2.connect()
        vector_store2 = VectorStore(conn2)

        # 5. 第二次页面加载 - 再次调用 get_tables
        print("\n[第二次页面加载]")
        try:
            tables = conn2.get_tables()
            print(f"  get_tables: {len(tables)} 个表 ✅")
        except Exception as e:
            print(f"  get_tables 失败: {e} ❌")
            return False

        # 6. 再次检查表存在状态
        ent_table_exists = vector_store2.check_table_exists(test_table)
        ent_count_in_table = vector_store2.get_vector_count(test_table) if ent_table_exists else 0
        print(f"  check_table_exists({test_table}): {ent_table_exists}")
        print(f"  get_vector_count({test_table}): {ent_count_in_table}")

        conn2.close()

        # ===== 测试缓存连接场景 =====
        print("\n[测试缓存连接场景 - 同一个连接对象多次使用]")
        conn3 = DBConnection(
            host=Config.DB_HOST,
            port=Config.DB_PORT,
            schema=Config.DB_SCHEMA,
            dbname=Config.DB_NAME,
            user=Config.DB_USER,
            password=Config.DB_PASSWORD
        )
        conn3.connect()
        vs3 = VectorStore(conn3)

        # 模拟多次调用
        for i in range(5):
            tables = conn3.get_tables()
            exists = vs3.check_table_exists(test_table)
            count = vs3.get_vector_count(test_table)
            print(f"  第{i+1}次: tables={len(tables)}, exists={exists}, count={count}")

        conn3.close()

        print("\n✅ Streamlit rerun 模拟测试通过")
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
        try:
            conn.close()
        except:
            pass


def test_get_tables_with_empty_schema():
    """测试 schema 为空时 get_tables 的行为"""
    print("\n" + "=" * 60)
    print("测试 schema 为空时 get_tables 的行为")
    print("=" * 60)

    conn = DBConnection(
        host=Config.DB_HOST,
        port=Config.DB_PORT,
        schema='',  # 空 schema
        dbname=Config.DB_NAME,
        user=Config.DB_USER,
        password=Config.DB_PASSWORD
    )

    if not conn.connect():
        print("❌ 数据库连接失败")
        return False

    try:
        print("\n[测试空 schema 的 get_tables]")
        tables = conn.get_tables()
        print(f"✅ 空 schema get_tables 返回: {len(tables)} 个表")
        conn.close()
        return True
    except Exception as e:
        print(f"❌ 空 schema get_tables 失败: {e}")
        conn.close()
        return False


def test_execute_with_ddl_then_select():
    """测试执行 DDL 后再执行 SELECT"""
    print("\n" + "=" * 60)
    print("测试 DDL 后执行 SELECT")
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

    test_table = 'test_ddl_then_select'

    try:
        # 1. 执行 CREATE TABLE (DDL)
        print("\n[步骤1] 执行 CREATE TABLE...")
        cursor = conn.execute(f"CREATE TABLE IF NOT EXISTS {test_table} (id INT)")
        print(f"✅ CREATE TABLE 成功")

        # 2. 立即执行 SELECT
        print("\n[步骤2] 立即执行 SELECT...")
        cursor = conn.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = %s LIMIT 5", (Config.DB_SCHEMA,))
        results = cursor.fetchall()
        print(f"✅ SELECT 成功，返回 {len(results)} 条")

        # 3. 执行 DROP TABLE (DDL)
        print("\n[步骤3] 执行 DROP TABLE...")
        cursor = conn.execute(f"DROP TABLE IF EXISTS {test_table}")
        print(f"✅ DROP TABLE 成功")

        # 4. 再次执行 SELECT
        print("\n[步骤4] 再次执行 SELECT...")
        cursor = conn.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = %s LIMIT 5", (Config.DB_SCHEMA,))
        results = cursor.fetchall()
        print(f"✅ SELECT 成功，返回 {len(results)} 条")

        conn.close()
        print("\n✅ DDL + SELECT 测试通过")
        return True

    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        print(traceback.format_exc())
        try:
            conn.execute(f"DROP TABLE IF EXISTS {test_table}")
        except:
            pass
        conn.close()
        return False


if __name__ == '__main__':
    r1 = test_streamlit_rerun_simulation()
    r2 = test_get_tables_with_empty_schema()
    r3 = test_execute_with_ddl_then_select()

    print("\n" + "=" * 60)
    print("测试总结")
    print("=" * 60)
    print(f"Streamlit rerun 模拟: {'✅ 通过' if r1 else '❌ 失败'}")
    print(f"空 schema 测试: {'✅ 通过' if r2 else '❌ 失败'}")
    print(f"DDL + SELECT 测试: {'✅ 通过' if r3 else '❌ 失败'}")
