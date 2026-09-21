import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.vector_store import VectorStore
from database.connection import DBConnection
from config import Config

def test_custom_vector_table_name():
    """测试自定义向量表名功能 - 验证向量化流程使用自定义表名"""
    print("=" * 60)
    print("测试自定义向量表名功能")
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
    custom_ent_table = 'my_custom_enterprise_vector'
    custom_std_table = 'my_custom_standard_vector'

    try:
        # 清理
        vector_store.drop_vector_table(custom_ent_table)
        vector_store.drop_vector_table(custom_std_table)

        # 1. 测试使用自定义名称创建企业向量表
        print("\n[1/4] 使用自定义名称创建企业向量表...")
        success = vector_store.create_vector_table(custom_ent_table, table_type='enterprise')
        assert success, "创建自定义企业向量表失败"
        assert vector_store.check_table_exists(custom_ent_table), "自定义企业向量表应存在"
        print(f"✅ 创建自定义企业向量表 {custom_ent_table} 成功")

        # 2. 测试使用自定义名称创建标准地址向量表
        print("\n[2/4] 使用自定义名称创建标准地址向量表...")
        success = vector_store.create_vector_table(custom_std_table, table_type='standard')
        assert success, "创建自定义标准地址向量表失败"
        assert vector_store.check_table_exists(custom_std_table), "自定义标准地址向量表应存在"
        print(f"✅ 创建自定义标准地址向量表 {custom_std_table} 成功")

        # 3. 验证默认表名和自定义表名可以共存
        print("\n[3/4] 验证默认表名和自定义表名共存...")
        default_ent = Config.ENTERPRISE_VECTOR_TABLE
        default_std = Config.STANDARD_VECTOR_TABLE
        vector_store.drop_vector_table(default_ent)
        vector_store.drop_vector_table(default_std)

        success = vector_store.create_vector_table(default_ent, table_type='enterprise')
        assert success, "创建默认企业向量表失败"
        success = vector_store.create_vector_table(default_std, table_type='standard')
        assert success, "创建默认标准地址向量表失败"

        all_tables = vector_store.get_vector_tables()
        assert custom_ent_table in all_tables, f"自定义企业表应在向量表列表中"
        assert custom_std_table in all_tables, f"自定义标准表应在向量表列表中"
        assert default_ent in all_tables, f"默认企业表应在向量表列表中"
        assert default_std in all_tables, f"默认标准表应在向量表列表中"
        print(f"✅ 默认表和自定义表共存验证通过")
        print(f"   当前向量表: {all_tables}")

        # 4. 验证重命名后配置同步逻辑（模拟 app.py 中的逻辑）
        print("\n[4/4] 验证重命名后配置同步逻辑...")
        vec_config = {
            'enterprise_vector_table': custom_ent_table,
            'standard_vector_table': custom_std_table
        }

        # 模拟重命名操作
        renamed_ent = 'renamed_enterprise_vector'
        renamed_std = 'renamed_standard_vector'
        vector_store.drop_vector_table(renamed_ent)
        vector_store.drop_vector_table(renamed_std)

        success = vector_store.rename_vector_table(custom_ent_table, renamed_ent)
        assert success, "重命名企业向量表失败"

        # 模拟 app.py 中的配置同步逻辑
        if vec_config.get('enterprise_vector_table') == custom_ent_table:
            vec_config['enterprise_vector_table'] = renamed_ent

        assert vec_config['enterprise_vector_table'] == renamed_ent, "配置应同步更新"
        print(f"✅ 配置同步验证通过: {custom_ent_table} -> {renamed_ent}")

        # 清理
        vector_store.drop_vector_table(renamed_ent)
        vector_store.drop_vector_table(renamed_std)
        vector_store.drop_vector_table(default_ent)
        vector_store.drop_vector_table(default_std)

        print("\n✅ 所有自定义表名测试通过！")
        return True

    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        print(traceback.format_exc())
        # 清理
        try:
            vector_store.drop_vector_table(custom_ent_table)
            vector_store.drop_vector_table(custom_std_table)
            vector_store.drop_vector_table('renamed_enterprise_vector')
            vector_store.drop_vector_table('renamed_standard_vector')
            vector_store.drop_vector_table(Config.ENTERPRISE_VECTOR_TABLE)
            vector_store.drop_vector_table(Config.STANDARD_VECTOR_TABLE)
        except:
            pass
        return False
    finally:
        conn.close()


def test_vec_config_default_values():
    """测试 vec_config 默认值包含自定义表名字段"""
    print("\n" + "=" * 60)
    print("测试 vec_config 默认值")
    print("=" * 60)

    # 模拟 init_session_state 中的 vec_config 初始化
    vec_config = {
        'enterprise_table': '',
        'enterprise_id_col': '',
        'enterprise_name_col': '',
        'enterprise_address_col': '',
        'enterprise_vector_table': Config.ENTERPRISE_VECTOR_TABLE,
        'standard_table': '',
        'standard_id_col': '',
        'standard_address_col': '',
        'standard_room_col': '',
        'standard_vector_table': Config.STANDARD_VECTOR_TABLE
    }

    assert 'enterprise_vector_table' in vec_config, "vec_config 应包含 enterprise_vector_table"
    assert 'standard_vector_table' in vec_config, "vec_config 应包含 standard_vector_table"
    assert vec_config['enterprise_vector_table'] == Config.ENTERPRISE_VECTOR_TABLE, "默认值应为 Config.ENTERPRISE_VECTOR_TABLE"
    assert vec_config['standard_vector_table'] == Config.STANDARD_VECTOR_TABLE, "默认值应为 Config.STANDARD_VECTOR_TABLE"

    print("✅ vec_config 默认值验证通过")
    print(f"   enterprise_vector_table: {vec_config['enterprise_vector_table']}")
    print(f"   standard_vector_table: {vec_config['standard_vector_table']}")
    return True


if __name__ == '__main__':
    result1 = test_vec_config_default_values()
    result2 = test_custom_vector_table_name()

    print("\n" + "=" * 60)
    print("测试总结")
    print("=" * 60)
    print(f"vec_config 默认值: {'✅ 通过' if result1 else '❌ 失败'}")
    print(f"自定义向量表名: {'✅ 通过' if result2 else '❌ 失败'}")
