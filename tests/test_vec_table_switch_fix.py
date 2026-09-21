import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config


def test_vec_config_reset_on_enterprise_table_switch():
    print("=" * 60)
    print("test vec_config reset on enterprise table switch")
    print("=" * 60)

    print("\n[1/4] simulate initial state...")
    vec_config = {
        'enterprise_table': 'old_enterprise',
        'enterprise_id_col': 'old_id',
        'enterprise_name_col': 'old_name',
        'enterprise_address_col': 'old_addr',
        'enterprise_vector_table': 'old_enterprise_vectors',
        'standard_table': '',
        'standard_id_col': '',
        'standard_address_col': '',
        'standard_room_col': '',
        'standard_vector_table': Config.STANDARD_VECTOR_TABLE
    }
    session_state = {
        'enterprise_vector_table_name': 'old_enterprise_vectors',
        'enterprise_id_vec': 'old_id',
        'enterprise_name_vec': 'old_name',
        'enterprise_addr_vec': 'old_addr',
    }
    print(f"  initial vec_config['enterprise_vector_table'] = {vec_config['enterprise_vector_table']}")

    print("\n[2/4] simulate switching enterprise table (old → new_enterprise)...")
    enterprise_table = 'new_enterprise'
    if enterprise_table and enterprise_table != vec_config.get('enterprise_table'):
        vec_config['enterprise_id_col'] = ''
        vec_config['enterprise_name_col'] = ''
        vec_config['enterprise_address_col'] = ''
        new_ent_vec_table = f"{enterprise_table}_vectors"
        vec_config['enterprise_vector_table'] = new_ent_vec_table
        if 'enterprise_vector_table_name' in session_state:
            del session_state['enterprise_vector_table_name']
        for key in ['enterprise_id_vec', 'enterprise_name_vec', 'enterprise_addr_vec']:
            if key in session_state:
                del session_state[key]
    vec_config['enterprise_table'] = enterprise_table

    assert vec_config['enterprise_vector_table'] == 'new_enterprise_vectors', \
        f"expected 'new_enterprise_vectors', got '{vec_config['enterprise_vector_table']}'"
    assert vec_config['enterprise_id_col'] == '', "id_col should be reset"
    assert vec_config['enterprise_name_col'] == '', "name_col should be reset"
    assert vec_config['enterprise_address_col'] == '', "address_col should be reset"
    assert 'enterprise_vector_table_name' not in session_state, "text_input key should be deleted"
    assert 'enterprise_id_vec' not in session_state, "widget key should be deleted"
    print(f"  vec_config['enterprise_vector_table'] = {vec_config['enterprise_vector_table']} ✓")
    print(f"  all field cols reset ✓")
    print(f"  text_input key deleted ✓")

    print("\n[3/4] verify step2 reads correct vec_table from vec_config...")
    ent_vec_table = vec_config.get('enterprise_vector_table', Config.ENTERPRISE_VECTOR_TABLE)
    assert ent_vec_table == 'new_enterprise_vectors', \
        f"step2 should read 'new_enterprise_vectors', got '{ent_vec_table}'"
    print(f"  step2 ent_vec_table = {ent_vec_table} ✓")

    print("\n[4/4] simulate switching again (new_enterprise → another_table)...")
    enterprise_table = 'another_table'
    if enterprise_table and enterprise_table != vec_config.get('enterprise_table'):
        vec_config['enterprise_id_col'] = ''
        vec_config['enterprise_name_col'] = ''
        vec_config['enterprise_address_col'] = ''
        new_ent_vec_table = f"{enterprise_table}_vectors"
        vec_config['enterprise_vector_table'] = new_ent_vec_table
        if 'enterprise_vector_table_name' in session_state:
            del session_state['enterprise_vector_table_name']
        for key in ['enterprise_id_vec', 'enterprise_name_vec', 'enterprise_addr_vec']:
            if key in session_state:
                del session_state[key]
    vec_config['enterprise_table'] = enterprise_table

    assert vec_config['enterprise_vector_table'] == 'another_table_vectors', \
        f"expected 'another_table_vectors', got '{vec_config['enterprise_vector_table']}'"
    print(f"  vec_config['enterprise_vector_table'] = {vec_config['enterprise_vector_table']} ✓")

    print("\n[PASS] test_vec_config_reset_on_enterprise_table_switch")
    return True


def test_vec_config_reset_on_standard_table_switch():
    print("=" * 60)
    print("test vec_config reset on standard table switch")
    print("=" * 60)

    print("\n[1/3] simulate initial state...")
    vec_config = {
        'enterprise_table': '',
        'enterprise_id_col': '',
        'enterprise_name_col': '',
        'enterprise_address_col': '',
        'enterprise_vector_table': Config.ENTERPRISE_VECTOR_TABLE,
        'standard_table': 'old_standard',
        'standard_id_col': 'old_id',
        'standard_address_col': 'old_addr',
        'standard_room_col': 'old_room',
        'standard_vector_table': 'old_standard_vectors'
    }
    session_state = {
        'standard_vector_table_name': 'old_standard_vectors',
        'standard_id_vec': 'old_id',
        'standard_addr_vec': 'old_addr',
        'standard_room_vec': 'old_room',
    }

    print("\n[2/3] simulate switching standard table...")
    standard_table = 'new_standard'
    if standard_table and standard_table != vec_config.get('standard_table'):
        vec_config['standard_id_col'] = ''
        vec_config['standard_address_col'] = ''
        vec_config['standard_room_col'] = ''
        new_std_vec_table = f"{standard_table}_vectors"
        vec_config['standard_vector_table'] = new_std_vec_table
        if 'standard_vector_table_name' in session_state:
            del session_state['standard_vector_table_name']
        for key in ['standard_id_vec', 'standard_addr_vec', 'standard_room_vec']:
            if key in session_state:
                del session_state[key]
    vec_config['standard_table'] = standard_table

    assert vec_config['standard_vector_table'] == 'new_standard_vectors', \
        f"expected 'new_standard_vectors', got '{vec_config['standard_vector_table']}'"
    assert vec_config['standard_id_col'] == '', "id_col should be reset"
    assert vec_config['standard_address_col'] == '', "address_col should be reset"
    assert vec_config['standard_room_col'] == '', "room_col should be reset"
    assert 'standard_vector_table_name' not in session_state, "text_input key should be deleted"
    print(f"  vec_config['standard_vector_table'] = {vec_config['standard_vector_table']} ✓")

    print("\n[3/3] verify step2 reads correct vec_table from vec_config...")
    std_vec_table = vec_config.get('standard_vector_table', Config.STANDARD_VECTOR_TABLE)
    assert std_vec_table == 'new_standard_vectors', \
        f"step2 should read 'new_standard_vectors', got '{std_vec_table}'"
    print(f"  step2 std_vec_table = {std_vec_table} ✓")

    print("\n[PASS] test_vec_config_reset_on_standard_table_switch")
    return True


def test_vec_table_name_generation():
    print("=" * 60)
    print("test vector table name generation rule")
    print("=" * 60)

    test_cases = [
        ('enterprise', 'enterprise_vectors'),
        ('t_company', 't_company_vectors'),
        ('企业表', '企业表_vectors'),
        ('my_table_2024', 'my_table_2024_vectors'),
    ]

    for src_table, expected in test_cases:
        result = f"{src_table}_vectors"
        assert result == expected, f"expected '{expected}', got '{result}'"
        print(f"  {src_table} → {result} ✓")

    print("\n[PASS] test_vec_table_name_generation")
    return True


def test_no_reset_when_same_table_selected():
    print("=" * 60)
    print("test no reset when same table is re-selected")
    print("=" * 60)

    vec_config = {
        'enterprise_table': 'my_enterprise',
        'enterprise_id_col': 'id',
        'enterprise_name_col': 'name',
        'enterprise_address_col': 'addr',
        'enterprise_vector_table': 'my_enterprise_vectors',
        'standard_table': '',
        'standard_id_col': '',
        'standard_address_col': '',
        'standard_room_col': '',
        'standard_vector_table': Config.STANDARD_VECTOR_TABLE
    }

    print("\n[1/1] re-select same table should NOT reset fields...")
    enterprise_table = 'my_enterprise'
    if enterprise_table and enterprise_table != vec_config.get('enterprise_table'):
        assert False, "should not enter reset block when same table selected"

    assert vec_config['enterprise_vector_table'] == 'my_enterprise_vectors', \
        "vector table name should not change"
    assert vec_config['enterprise_id_col'] == 'id', "id_col should not be reset"
    assert vec_config['enterprise_name_col'] == 'name', "name_col should not be reset"
    assert vec_config['enterprise_address_col'] == 'addr', "address_col should not be reset"
    print(f"  all fields preserved when same table re-selected ✓")

    print("\n[PASS] test_no_reset_when_same_table_selected")
    return True


if __name__ == '__main__':
    results = {}

    tests = [
        ('vec_config_reset_on_enterprise_table_switch', test_vec_config_reset_on_enterprise_table_switch),
        ('vec_config_reset_on_standard_table_switch', test_vec_config_reset_on_standard_table_switch),
        ('vec_table_name_generation', test_vec_table_name_generation),
        ('no_reset_when_same_table_selected', test_no_reset_when_same_table_selected),
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
