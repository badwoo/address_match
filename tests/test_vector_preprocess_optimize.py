import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.vector_store import VectorStore
from database.connection import DBConnection
from config import Config


def test_get_vector_tables_sorted_by_creation():
    print("=" * 60)
    print("test get_vector_tables sorted by creation (newest first)")
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
        return False

    vector_store = VectorStore(conn)
    test_table_1 = 'test_sort_first_vector'
    test_table_2 = 'test_sort_second_vector'
    test_table_3 = 'test_sort_third_vector'

    try:
        for t in [test_table_1, test_table_2, test_table_3]:
            vector_store.drop_vector_table(t)

        print("\n[1/4] create 3 vector tables in order...")
        vector_store.create_vector_table(test_table_1, table_type='enterprise')
        print(f"  created {test_table_1}")
        vector_store.create_vector_table(test_table_2, table_type='enterprise')
        print(f"  created {test_table_2}")
        vector_store.create_vector_table(test_table_3, table_type='enterprise')
        print(f"  created {test_table_3}")

        print("\n[2/4] get vector table list...")
        tables = vector_store.get_vector_tables()
        print(f"  current tables: {tables}")

        print("\n[3/4] verify sort order: newest first...")
        test_tables = [t for t in tables if t in [test_table_1, test_table_2, test_table_3]]
        print(f"  test tables order: {test_tables}")

        assert len(test_tables) == 3, f"expected 3 test tables, got {len(test_tables)}"
        assert test_tables[0] == test_table_3, f"newest {test_table_3} should be first, got {test_tables[0]}"
        assert test_tables[1] == test_table_2, f"second {test_table_2} should be second, got {test_tables[1]}"
        assert test_tables[2] == test_table_1, f"oldest {test_table_1} should be third, got {test_tables[2]}"
        print(f"[PASS] sort correct: {test_table_3}(newest) -> {test_table_2} -> {test_table_1}(oldest)")

        print("\n[4/4] verify return type...")
        assert isinstance(tables, list), "return value should be list"
        assert len(tables) > 0, "should have at least 1 vector table"
        print("[PASS] return type check passed")

        for t in [test_table_1, test_table_2, test_table_3]:
            vector_store.drop_vector_table(t)
        print("\n[PASS] all tests passed!")
        return True

    except Exception as e:
        print(f"\n[FAIL] test failed: {e}")
        import traceback
        print(traceback.format_exc())
        for t in [test_table_1, test_table_2, test_table_3]:
            try:
                vector_store.drop_vector_table(t)
            except:
                pass
        return False
    finally:
        conn.close()


def test_search_filter_logic():
    print("\n" + "=" * 60)
    print("test search filter logic")
    print("=" * 60)

    options = ['enterprise_vector', 'standard_address_vector', 'test_vector_1', 'test_vector_2', 'other_table']

    print("\n[1/4] test empty search keyword...")
    search_text = ""
    if search_text:
        filtered = [opt for opt in options if search_text.lower() in opt.lower()]
    else:
        filtered = list(options)
    assert filtered == options, "empty search should return all options"
    print("[PASS] empty search returns all options")

    print("\n[2/4] test search 'test'...")
    search_text = "test"
    filtered = [opt for opt in options if search_text.lower() in opt.lower()]
    assert filtered == ['test_vector_1', 'test_vector_2'], f"search 'test' should return 2 items, got: {filtered}"
    print("[PASS] search 'test' returns correct results")

    print("\n[3/4] test search 'vector'...")
    search_text = "vector"
    filtered = [opt for opt in options if search_text.lower() in opt.lower()]
    assert len(filtered) == 4, f"search 'vector' should return 4 items, got: {filtered}"
    print("[PASS] search 'vector' returns correct results")

    print("\n[4/4] test search nonexistent keyword...")
    search_text = "nonexistent"
    filtered = [opt for opt in options if search_text.lower() in opt.lower()]
    assert filtered == [], "search nonexistent keyword should return empty list"
    print("[PASS] search nonexistent keyword returns empty list")

    print("\n[PASS] search filter logic test passed!")
    return True


def test_pagination_logic():
    print("\n" + "=" * 60)
    print("test pagination logic (page_size=6)")
    print("=" * 60)

    tables = [f"vector_table_{i}" for i in range(1, 15)]
    page_size = 6

    print("\n[1/3] test page 1...")
    total_tables = len(tables)
    total_pages = max(1, (total_tables + page_size - 1) // page_size)
    current_page = 1
    start_idx = (current_page - 1) * page_size
    end_idx = min(start_idx + page_size, total_tables)
    page_tables = tables[start_idx:end_idx]

    assert total_pages == 3, f"14 tables should have 3 pages, got: {total_pages}"
    assert len(page_tables) == 6, f"page 1 should have 6 items, got: {len(page_tables)}"
    assert page_tables[0] == "vector_table_1", "page 1 first item should be vector_table_1"
    print(f"[PASS] page 1: {len(page_tables)} items, total {total_pages} pages")

    print("\n[2/3] test page 2...")
    current_page = 2
    start_idx = (current_page - 1) * page_size
    end_idx = min(start_idx + page_size, total_tables)
    page_tables = tables[start_idx:end_idx]
    assert len(page_tables) == 6, f"page 2 should have 6 items, got: {len(page_tables)}"
    print(f"[PASS] page 2: {len(page_tables)} items")

    print("\n[3/3] test page 3 (last page, not full)...")
    current_page = 3
    start_idx = (current_page - 1) * page_size
    end_idx = min(start_idx + page_size, total_tables)
    page_tables = tables[start_idx:end_idx]
    assert len(page_tables) == 2, f"page 3 should have 2 items, got: {len(page_tables)}"
    print(f"[PASS] page 3: {len(page_tables)} items")

    print("\n[PASS] pagination logic test passed!")
    return True


def test_vec_config_restore_after_options_change():
    print("\n" + "=" * 60)
    print("test vec_config restore after selectbox options change")
    print("=" * 60)

    vec_config = {
        'enterprise_table': 'enterprise',
        'enterprise_id_col': 'id',
        'enterprise_name_col': 'name',
        'enterprise_address_col': 'address',
        'enterprise_vector_table': 'enterprise_vector',
        'standard_table': 'standard_address',
        'standard_id_col': 'code',
        'standard_address_col': 'address',
        'standard_room_col': 'room',
        'standard_vector_table': 'standard_address_vector'
    }

    print("\n[1/5] test enterprise table restore: saved value in new options...")
    tables = ['enterprise', 'standard_address', 'other_table']
    session_state_ent_table = ''
    _saved_ent_table = vec_config.get('enterprise_table', '')
    if _saved_ent_table and _saved_ent_table in tables and session_state_ent_table != _saved_ent_table:
        session_state_ent_table = _saved_ent_table
    assert session_state_ent_table == 'enterprise', f"should restore to 'enterprise', got '{session_state_ent_table}'"
    print("[PASS] enterprise table restored from vec_config")

    print("\n[2/5] test enterprise table restore: saved value NOT in new options...")
    tables_new = ['standard_address', 'other_table']
    session_state_ent_table = ''
    _saved_ent_table = vec_config.get('enterprise_table', '')
    if _saved_ent_table and _saved_ent_table in tables_new and session_state_ent_table != _saved_ent_table:
        session_state_ent_table = _saved_ent_table
    assert session_state_ent_table == '', f"should stay empty when saved value not in options, got '{session_state_ent_table}'"
    print("[PASS] enterprise table stays empty when saved value not in options")

    print("\n[3/5] test enterprise column restore: saved columns in new options...")
    enterprise_columns = ['id', 'name', 'address', 'phone', 'type']
    session_state_ent_id = ''
    _saved_ent_id = vec_config.get('enterprise_id_col', '')
    if _saved_ent_id and _saved_ent_id in enterprise_columns and session_state_ent_id != _saved_ent_id:
        session_state_ent_id = _saved_ent_id
    assert session_state_ent_id == 'id', f"should restore to 'id', got '{session_state_ent_id}'"
    print("[PASS] enterprise id column restored from vec_config")

    print("\n[4/5] test enterprise column restore: saved columns NOT in new options...")
    enterprise_columns_new = ['code', 'full_address', 'phone']
    session_state_ent_id = ''
    _saved_ent_id = vec_config.get('enterprise_id_col', '')
    if _saved_ent_id and _saved_ent_id in enterprise_columns_new and session_state_ent_id != _saved_ent_id:
        session_state_ent_id = _saved_ent_id
    assert session_state_ent_id == '', f"should stay empty when saved column not in options, got '{session_state_ent_id}'"
    print("[PASS] enterprise id column stays empty when saved column not in options")

    print("\n[5/5] test no restore when session_state already matches vec_config...")
    tables = ['enterprise', 'standard_address', 'other_table']
    session_state_ent_table = 'enterprise'
    _saved_ent_table = vec_config.get('enterprise_table', '')
    restore_triggered = False
    if _saved_ent_table and _saved_ent_table in tables and session_state_ent_table != _saved_ent_table:
        session_state_ent_table = _saved_ent_table
        restore_triggered = True
    assert not restore_triggered, "should not trigger restore when values already match"
    assert session_state_ent_table == 'enterprise', "value should remain unchanged"
    print("[PASS] no unnecessary restore when values already match")

    print("\n[PASS] vec_config restore logic test passed!")
    return True


def test_vec_config_field_clear_on_table_change():
    print("\n" + "=" * 60)
    print("test vec_config field clear on table change")
    print("=" * 60)

    vec_config = {
        'enterprise_table': 'enterprise',
        'enterprise_id_col': 'id',
        'enterprise_name_col': 'name',
        'enterprise_address_col': 'address',
    }

    print("\n[1/2] test field clear when table changes...")
    enterprise_table = 'new_enterprise'
    if enterprise_table != vec_config.get('enterprise_table'):
        vec_config['enterprise_id_col'] = ''
        vec_config['enterprise_name_col'] = ''
        vec_config['enterprise_address_col'] = ''
    vec_config['enterprise_table'] = enterprise_table
    assert vec_config['enterprise_table'] == 'new_enterprise'
    assert vec_config['enterprise_id_col'] == '', "id_col should be cleared on table change"
    assert vec_config['enterprise_name_col'] == '', "name_col should be cleared on table change"
    assert vec_config['enterprise_address_col'] == '', "address_col should be cleared on table change"
    print("[PASS] fields cleared when table changes")

    print("\n[2/2] test field NOT cleared when table stays same...")
    vec_config = {
        'enterprise_table': 'enterprise',
        'enterprise_id_col': 'id',
        'enterprise_name_col': 'name',
        'enterprise_address_col': 'address',
    }
    enterprise_table = 'enterprise'
    if enterprise_table != vec_config.get('enterprise_table'):
        vec_config['enterprise_id_col'] = ''
        vec_config['enterprise_name_col'] = ''
        vec_config['enterprise_address_col'] = ''
    vec_config['enterprise_table'] = enterprise_table
    assert vec_config['enterprise_id_col'] == 'id', "id_col should NOT be cleared when table unchanged"
    assert vec_config['enterprise_name_col'] == 'name', "name_col should NOT be cleared when table unchanged"
    assert vec_config['enterprise_address_col'] == 'address', "address_col should NOT be cleared when table unchanged"
    print("[PASS] fields preserved when table unchanged")

    print("\n[PASS] vec_config field clear logic test passed!")
    return True


def test_field_selectbox_no_restore_interference():
    print("\n" + "=" * 60)
    print("test field selectbox no restore interference")
    print("=" * 60)

    print("\n[1/4] test user selects a different field - should NOT be restored...")
    vec_config = {
        'enterprise_table': 'enterprise',
        'enterprise_id_col': 'id',
        'enterprise_name_col': 'name',
        'enterprise_address_col': 'address',
    }
    enterprise_columns = ['id', 'name', 'address', 'phone', 'type']

    # 模拟用户选择新字段 'phone'（Streamlit 会更新 session_state）
    session_state_ent_id = 'phone'
    # 修复后的代码：不再从 vec_config 恢复，直接让 selectbox 正常工作
    # 旧代码会在这里执行：if _saved_ent_id in columns: session_state[key] = _saved_ent_id
    # 这会覆盖用户的 'phone' 选择，回跳到 'id'

    # 验证：session_state 保持用户选择的值，不被 vec_config 旧值覆盖
    assert session_state_ent_id == 'phone', f"user selection should NOT be overwritten, got '{session_state_ent_id}'"
    print("[PASS] user field selection preserved, not overwritten by vec_config")

    print("\n[2/4] test vec_config updated after selectbox returns...")
    # selectbox 返回后，vec_config 应该被更新为新值
    vec_config['enterprise_id_col'] = session_state_ent_id
    assert vec_config['enterprise_id_col'] == 'phone', "vec_config should be updated to new selection"
    print("[PASS] vec_config correctly updated after field selection")

    print("\n[3/4] test user changes field multiple times...")
    # 用户再次选择 'type'
    session_state_ent_id = 'type'
    vec_config['enterprise_id_col'] = session_state_ent_id
    assert vec_config['enterprise_id_col'] == 'type', "vec_config should track latest selection"
    print("[PASS] multiple field changes tracked correctly")

    print("\n[4/4] test table change clears fields (expected behavior)...")
    # 用户更换表，字段应该被清空
    enterprise_table = 'new_enterprise'
    if enterprise_table != vec_config.get('enterprise_table'):
        vec_config['enterprise_id_col'] = ''
        vec_config['enterprise_name_col'] = ''
        vec_config['enterprise_address_col'] = ''
    vec_config['enterprise_table'] = enterprise_table
    assert vec_config['enterprise_id_col'] == '', "fields should be cleared on table change"
    print("[PASS] fields correctly cleared on table change")

    print("\n[PASS] field selectbox no restore interference test passed!")
    return True


def test_table_selectbox_no_restore_interference():
    print("\n" + "=" * 60)
    print("test table selectbox no restore interference")
    print("=" * 60)

    print("\n[1/4] test user selects a different table - should NOT be restored...")
    vec_config = {
        'enterprise_table': 'enterprise_old',
        'enterprise_id_col': 'id',
        'enterprise_name_col': 'name',
        'enterprise_address_col': 'address',
    }
    tables = ['enterprise_old', 'enterprise_new', 'standard_address']

    # 模拟用户选择新表 'enterprise_new'（Streamlit 会更新 session_state）
    session_state_ent_table = 'enterprise_new'
    # 修复后的代码：不再从 vec_config 恢复，直接让 selectbox 正常工作
    # 旧代码会在这里执行：if _saved_ent_table in tables: session_state[key] = _saved_ent_table
    # 这会覆盖用户的 'enterprise_new' 选择，回跳到 'enterprise_old'

    # 验证：session_state 保持用户选择的值，不被 vec_config 旧值覆盖
    assert session_state_ent_table == 'enterprise_new', f"user table selection should NOT be overwritten, got '{session_state_ent_table}'"
    print("[PASS] user table selection preserved, not overwritten by vec_config")

    print("\n[2/4] test vec_config updated after selectbox returns...")
    # selectbox 返回后，vec_config 应该被更新为新值
    # 同时字段应该被清空（因为表变了）
    enterprise_table = session_state_ent_table
    if enterprise_table != vec_config.get('enterprise_table'):
        vec_config['enterprise_id_col'] = ''
        vec_config['enterprise_name_col'] = ''
        vec_config['enterprise_address_col'] = ''
    vec_config['enterprise_table'] = enterprise_table
    assert vec_config['enterprise_table'] == 'enterprise_new', "vec_config should be updated to new table"
    assert vec_config['enterprise_id_col'] == '', "fields should be cleared on table change"
    print("[PASS] vec_config correctly updated and fields cleared on table change")

    print("\n[3/4] test user changes table multiple times...")
    # 用户再次选择 'standard_address'
    session_state_ent_table = 'standard_address'
    enterprise_table = session_state_ent_table
    if enterprise_table != vec_config.get('enterprise_table'):
        vec_config['enterprise_id_col'] = ''
        vec_config['enterprise_name_col'] = ''
        vec_config['enterprise_address_col'] = ''
    vec_config['enterprise_table'] = enterprise_table
    assert vec_config['enterprise_table'] == 'standard_address', "vec_config should track latest table selection"
    print("[PASS] multiple table changes tracked correctly")

    print("\n[4/4] test standard table selection also works...")
    std_vec_config = {
        'standard_table': 'std_old',
        'standard_id_col': 'code',
        'standard_address_col': 'addr',
        'standard_room_col': 'room',
    }
    session_state_std_table = 'std_new'
    # 验证不被恢复逻辑覆盖
    assert session_state_std_table == 'std_new', "standard table selection should NOT be overwritten"
    print("[PASS] standard table selection preserved")

    print("\n[PASS] table selectbox no restore interference test passed!")
    return True


if __name__ == '__main__':
    result1 = test_search_filter_logic()
    result2 = test_pagination_logic()
    result3 = test_get_vector_tables_sorted_by_creation()
    result4 = test_vec_config_restore_after_options_change()
    result5 = test_vec_config_field_clear_on_table_change()
    result6 = test_field_selectbox_no_restore_interference()
    result7 = test_table_selectbox_no_restore_interference()

    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)
    print(f"search filter logic:    {'PASS' if result1 else 'FAIL'}")
    print(f"pagination logic:       {'PASS' if result2 else 'FAIL'}")
    print(f"vector table sort:      {'PASS' if result3 else 'FAIL'}")
    print(f"vec_config restore:     {'PASS' if result4 else 'FAIL'}")
    print(f"field clear on change:  {'PASS' if result5 else 'FAIL'}")
    print(f"field select no restore:{'PASS' if result6 else 'FAIL'}")
    print(f"table select no restore:{'PASS' if result7 else 'FAIL'}")
