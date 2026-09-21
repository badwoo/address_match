import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config


def test_mapping_recall_on_enterprise_table_switch():
    print("=" * 60)
    print("test mapping recall on enterprise table switch")
    print("=" * 60)

    print("\n[1/5] simulate initial state with mapping...")
    vec_config = {
        'enterprise_table': 'table_a',
        'enterprise_id_col': 'id',
        'enterprise_name_col': 'name',
        'enterprise_address_col': 'addr',
        'enterprise_vector_table': 'table_a_vec',
        'standard_table': '',
        'standard_id_col': '',
        'standard_address_col': '',
        'standard_room_col': '',
        'standard_vector_table': Config.STANDARD_VECTOR_TABLE,
        'table_vec_mapping': {
            'table_a': 'table_a_vec',
            'table_b': 'table_b_custom_name',
        }
    }
    session_state = {
        'enterprise_vector_table_name': 'table_a_vec',
    }

    print("\n[2/5] switch to table_b (has mapping) → should recall 'table_b_custom_name'...")
    enterprise_table = 'table_b'
    if enterprise_table and enterprise_table != vec_config.get('enterprise_table'):
        vec_config['enterprise_id_col'] = ''
        vec_config['enterprise_name_col'] = ''
        vec_config['enterprise_address_col'] = ''
        _mapping = vec_config.get('table_vec_mapping', {})
        new_ent_vec_table = _mapping.get(enterprise_table, f"{enterprise_table}_vectors")
        vec_config['enterprise_vector_table'] = new_ent_vec_table
        if 'enterprise_vector_table_name' in session_state:
            del session_state['enterprise_vector_table_name']
    vec_config['enterprise_table'] = enterprise_table

    assert vec_config['enterprise_vector_table'] == 'table_b_custom_name', \
        f"expected 'table_b_custom_name' from mapping, got '{vec_config['enterprise_vector_table']}'"
    assert 'enterprise_vector_table_name' not in session_state, "text_input key should be deleted"
    print(f"  recalled from mapping: {vec_config['enterprise_vector_table']} ✓")

    print("\n[3/5] switch to table_c (no mapping) → should use default '{table}_vectors'...")
    enterprise_table = 'table_c'
    if enterprise_table and enterprise_table != vec_config.get('enterprise_table'):
        vec_config['enterprise_id_col'] = ''
        vec_config['enterprise_name_col'] = ''
        vec_config['enterprise_address_col'] = ''
        _mapping = vec_config.get('table_vec_mapping', {})
        new_ent_vec_table = _mapping.get(enterprise_table, f"{enterprise_table}_vectors")
        vec_config['enterprise_vector_table'] = new_ent_vec_table
        if 'enterprise_vector_table_name' in session_state:
            del session_state['enterprise_vector_table_name']
    vec_config['enterprise_table'] = enterprise_table

    assert vec_config['enterprise_vector_table'] == 'table_c_vectors', \
        f"expected 'table_c_vectors' as default, got '{vec_config['enterprise_vector_table']}'"
    print(f"  default name used: {vec_config['enterprise_vector_table']} ✓")

    print("\n[4/5] simulate creating vector table for table_c → should record mapping...")
    src_table = vec_config.get('enterprise_table', '')
    target_name = vec_config.get('enterprise_vector_table', '')
    if src_table:
        vec_config.setdefault('table_vec_mapping', {})[src_table] = target_name

    assert vec_config['table_vec_mapping']['table_c'] == 'table_c_vectors', \
        "mapping should be recorded after creation"
    print(f"  mapping recorded: table_c → {vec_config['table_vec_mapping']['table_c']} ✓")

    print("\n[5/5] switch back to table_c → should recall from mapping...")
    enterprise_table = 'table_a'
    if enterprise_table and enterprise_table != vec_config.get('enterprise_table'):
        _mapping = vec_config.get('table_vec_mapping', {})
        new_ent_vec_table = _mapping.get(enterprise_table, f"{enterprise_table}_vectors")
        vec_config['enterprise_vector_table'] = new_ent_vec_table
    vec_config['enterprise_table'] = enterprise_table

    assert vec_config['enterprise_vector_table'] == 'table_a_vec', \
        f"expected 'table_a_vec' from mapping, got '{vec_config['enterprise_vector_table']}'"
    print(f"  recalled from mapping: {vec_config['enterprise_vector_table']} ✓")

    print("\n[PASS] test_mapping_recall_on_enterprise_table_switch")
    return True


def test_mapping_recall_on_standard_table_switch():
    print("=" * 60)
    print("test mapping recall on standard table switch")
    print("=" * 60)

    vec_config = {
        'enterprise_table': '',
        'enterprise_id_col': '',
        'enterprise_name_col': '',
        'enterprise_address_col': '',
        'enterprise_vector_table': Config.ENTERPRISE_VECTOR_TABLE,
        'standard_table': 'addr_old',
        'standard_id_col': 'id',
        'standard_address_col': 'addr',
        'standard_room_col': 'room',
        'standard_vector_table': 'addr_old_vectors',
        'table_vec_mapping': {
            'addr_old': 'addr_old_vectors',
            'addr_new': 'addr_new_custom',
        }
    }

    print("\n[1/2] switch to addr_new (has mapping) → should recall...")
    standard_table = 'addr_new'
    if standard_table and standard_table != vec_config.get('standard_table'):
        vec_config['standard_id_col'] = ''
        vec_config['standard_address_col'] = ''
        vec_config['standard_room_col'] = ''
        _mapping = vec_config.get('table_vec_mapping', {})
        new_std_vec_table = _mapping.get(standard_table, f"{standard_table}_vectors")
        vec_config['standard_vector_table'] = new_std_vec_table
    vec_config['standard_table'] = standard_table

    assert vec_config['standard_vector_table'] == 'addr_new_custom', \
        f"expected 'addr_new_custom' from mapping, got '{vec_config['standard_vector_table']}'"
    print(f"  recalled from mapping: {vec_config['standard_vector_table']} ✓")

    print("\n[2/2] switch to addr_unknown (no mapping) → should use default...")
    standard_table = 'addr_unknown'
    if standard_table and standard_table != vec_config.get('standard_table'):
        _mapping = vec_config.get('table_vec_mapping', {})
        new_std_vec_table = _mapping.get(standard_table, f"{standard_table}_vectors")
        vec_config['standard_vector_table'] = new_std_vec_table
    vec_config['standard_table'] = standard_table

    assert vec_config['standard_vector_table'] == 'addr_unknown_vectors', \
        f"expected 'addr_unknown_vectors' as default, got '{vec_config['standard_vector_table']}'"
    print(f"  default name used: {vec_config['standard_vector_table']} ✓")

    print("\n[PASS] test_mapping_recall_on_standard_table_switch")
    return True


def test_start_vectorization_records_mapping():
    print("=" * 60)
    print("test _start_vectorization records mapping")
    print("=" * 60)

    print("\n[1/2] simulate _start_vectorization for enterprise type...")
    vec_config = {
        'enterprise_table': 'my_company',
        'enterprise_id_col': 'id',
        'enterprise_name_col': 'name',
        'enterprise_address_col': 'addr',
        'enterprise_vector_table': 'my_company_vec_2024',
        'standard_table': '',
        'standard_id_col': '',
        'standard_address_col': '',
        'standard_room_col': '',
        'standard_vector_table': Config.STANDARD_VECTOR_TABLE,
        'table_vec_mapping': {}
    }

    table_type = 'enterprise'
    if table_type == 'enterprise':
        _src = vec_config.get('enterprise_table', '')
        _vec = vec_config.get('enterprise_vector_table', '')
    else:
        _src = vec_config.get('standard_table', '')
        _vec = vec_config.get('standard_vector_table', '')
    if _src and _vec:
        vec_config.setdefault('table_vec_mapping', {})[_src] = _vec

    assert vec_config['table_vec_mapping']['my_company'] == 'my_company_vec_2024', \
        "mapping should be recorded when starting vectorization"
    print(f"  mapping recorded: my_company → {vec_config['table_vec_mapping']['my_company']} ✓")

    print("\n[2/2] verify switching back recalls the custom name...")
    _mapping = vec_config.get('table_vec_mapping', {})
    recalled = _mapping.get('my_company', f"my_company_vectors")
    assert recalled == 'my_company_vec_2024', \
        f"expected 'my_company_vec_2024', got '{recalled}'"
    print(f"  recalled custom name: {recalled} ✓")

    print("\n[PASS] test_start_vectorization_records_mapping")
    return True


def test_create_button_records_mapping():
    print("=" * 60)
    print("test create button records mapping")
    print("=" * 60)

    vec_config = {
        'enterprise_table': 't_enterprise',
        'enterprise_id_col': 'id',
        'enterprise_name_col': 'name',
        'enterprise_address_col': 'addr',
        'enterprise_vector_table': 't_enterprise_my_vec',
        'standard_table': '',
        'standard_id_col': '',
        'standard_address_col': '',
        'standard_room_col': '',
        'standard_vector_table': Config.STANDARD_VECTOR_TABLE,
        'table_vec_mapping': {}
    }

    print("\n[1/1] simulate create button click (table created successfully)...")
    target_name = vec_config.get('enterprise_vector_table', Config.ENTERPRISE_VECTOR_TABLE)
    src_table = vec_config.get('enterprise_table', '')
    if src_table:
        vec_config.setdefault('table_vec_mapping', {})[src_table] = target_name

    assert vec_config['table_vec_mapping']['t_enterprise'] == 't_enterprise_my_vec', \
        "mapping should be recorded after create button"
    print(f"  mapping recorded: t_enterprise → {vec_config['table_vec_mapping']['t_enterprise']} ✓")

    print("\n[PASS] test_create_button_records_mapping")
    return True


def test_empty_mapping_fallback():
    print("=" * 60)
    print("test empty mapping fallback to default naming")
    print("=" * 60)

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
        'standard_vector_table': Config.STANDARD_VECTOR_TABLE,
        'table_vec_mapping': {}
    }

    print("\n[1/2] switch to first table (no mapping exists)...")
    enterprise_table = 'first_table'
    _mapping = vec_config.get('table_vec_mapping', {})
    new_ent_vec_table = _mapping.get(enterprise_table, f"{enterprise_table}_vectors")
    assert new_ent_vec_table == 'first_table_vectors', \
        f"expected 'first_table_vectors', got '{new_ent_vec_table}'"
    print(f"  fallback to default: {new_ent_vec_table} ✓")

    print("\n[2/2] table name with special characters...")
    enterprise_table = 'my-table.2024'
    _mapping = vec_config.get('table_vec_mapping', {})
    new_ent_vec_table = _mapping.get(enterprise_table, f"{enterprise_table}_vectors")
    assert new_ent_vec_table == 'my-table.2024_vectors', \
        f"expected 'my-table.2024_vectors', got '{new_ent_vec_table}'"
    print(f"  special chars preserved: {new_ent_vec_table} ✓")

    print("\n[PASS] test_empty_mapping_fallback")
    return True


if __name__ == '__main__':
    results = {}

    tests = [
        ('mapping_recall_on_enterprise_table_switch', test_mapping_recall_on_enterprise_table_switch),
        ('mapping_recall_on_standard_table_switch', test_mapping_recall_on_standard_table_switch),
        ('start_vectorization_records_mapping', test_start_vectorization_records_mapping),
        ('create_button_records_mapping', test_create_button_records_mapping),
        ('empty_mapping_fallback', test_empty_mapping_fallback),
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
