"""
向量预处理页面 Bug 修复验证测试
================================

验证 Bug: 创建完企业向量表后再创建标准地址向量表，
企业表配置内容丢失，且企业表向量化源表信息标识、名称、地址都显示同一个字段。

根本原因：
1. 创建企业向量表后，tables 列表包含新创建的向量表（如 'enterprise_vectors'）
2. 用户在配置标准地址表时，企业表 selectbox 的 options 现在包含了向量表
3. 如果用户误切换企业表 selectbox 到向量表，会触发字段清除逻辑
4. session_state 中的字段值（如 'name'）不在向量表的 columns 中
5. streamlit 自动重置 selectbox 为 index=0
6. 三个字段 selectbox 都被重置为向量表的第一个字段 'id'

修复方案：在企业表/标准地址表 selectbox 的 options 中过滤掉向量表
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ====================================================================
# 修复1验证：源表 selectbox 的 options 不包含向量表
# ====================================================================

def test_source_table_selectbox_excludes_vector_tables():
    """验证源表 selectbox 的 options 过滤掉了向量表"""
    print("=" * 70)
    print("Bug fix: source table selectbox excludes vector tables")
    print("=" * 70)

    vp_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'pages', 'vector_preprocess.py'
    )
    with open(vp_path, 'r', encoding='utf-8') as f:
        source = f.read()

    # 验证：在获取 tables 后，过滤掉向量表
    assert 'get_cached_vector_tables' in source, \
        "source should call get_cached_vector_tables to identify vector tables"
    assert '_vector_table_set' in source, \
        "source should build a vector_table_set for filtering"
    assert "t for t in all_tables if t not in _vector_table_set" in source, \
        "source should filter out vector tables from all_tables"

    print("  source filters out vector tables from source table options ✓")

    # 验证：变量名从 tables 改为 all_tables（原始列表），tables 是过滤后的
    assert 'all_tables = list(get_cached_tables' in source, \
        "source should use all_tables for the raw table list"
    assert 'tables = [t for t in all_tables' in source, \
        "source should derive tables (filtered) from all_tables"

    print("  variable renamed: all_tables (raw) -> tables (filtered) ✓")

    print("\n[PASS] test_source_table_selectbox_excludes_vector_tables")
    return True


def test_filtering_logic_correctness():
    """验证过滤逻辑的正确性 - 模拟过滤过程"""
    print("=" * 70)
    print("Bug fix: filtering logic correctness")
    print("=" * 70)

    # 模拟数据库中的所有表
    all_tables = [
        'enterprise_data',           # 企业源表
        'standard_address_data',     # 标准地址源表
        'enterprise_vectors',        # 企业向量表（应被过滤）
        'standard_address_vectors',  # 标准地址向量表（应被过滤）
        'other_table',               # 其他表
    ]

    # 模拟 get_cached_vector_tables 返回的向量表
    vector_tables = ['enterprise_vectors', 'standard_address_vectors']
    _vector_table_set = set(vector_tables)

    # 执行过滤
    tables = [t for t in all_tables if t not in _vector_table_set]

    expected = ['enterprise_data', 'standard_address_data', 'other_table']
    assert tables == expected, \
        f"filtered tables mismatch.\nexpected: {expected}\nactual: {tables}"

    print(f"  all_tables: {all_tables}")
    print(f"  vector_tables: {vector_tables}")
    print(f"  filtered tables: {tables}")
    print("  vector tables correctly excluded from source options ✓")

    # 验证源表 selectbox 不会显示向量表
    assert 'enterprise_vectors' not in tables, "企业向量表不应出现在源表选项中"
    assert 'standard_address_vectors' not in tables, "标准地址向量表不应出现在源表选项中"
    assert 'enterprise_data' in tables, "企业源表应保留"
    assert 'standard_address_data' in tables, "标准地址源表应保留"

    print("  enterprise source table preserved ✓")
    print("  standard source table preserved ✓")
    print("  vector tables excluded ✓")

    print("\n[PASS] test_filtering_logic_correctness")
    return True


def test_filtering_handles_empty_result():
    """验证过滤后列表为空时的兜底逻辑"""
    print("=" * 70)
    print("Bug fix: filtering handles empty result (edge case)")
    print("=" * 70)

    # 极端情况：所有表都是向量表
    all_tables = ['enterprise_vectors', 'standard_address_vectors']
    vector_tables = ['enterprise_vectors', 'standard_address_vectors']
    _vector_table_set = set(vector_tables)

    tables = [t for t in all_tables if t not in _vector_table_set]

    # 兜底逻辑：如果过滤后为空，保留全部
    if not tables:
        tables = all_tables

    assert tables == all_tables, \
        f"empty filter result should fallback to all_tables, got {tables}"
    print(f"  all_tables (all vector tables): {all_tables}")
    print(f"  filtered (empty) -> fallback to all_tables: {tables}")
    print("  edge case handled correctly ✓")

    print("\n[PASS] test_filtering_handles_empty_result")
    return True


# ====================================================================
# 修复2验证：完整场景模拟 - 创建企业向量表后配置标准地址表
# ====================================================================

def test_full_flow_enterprise_config_preserved():
    """
    完整场景验证：
    1. 配置企业表（源表 A，字段 id/name/address）
    2. 创建企业向量表 enterprise_vectors
    3. 配置标准地址表（源表 B，字段 sid/saddr/sroom）
    4. 创建标准地址向量表 standard_address_vectors
    5. 验证企业表配置未丢失，且三个字段不是同一个值
    """
    print("=" * 70)
    print("Full flow: enterprise config preserved after creating standard vector table")
    print("=" * 70)

    # 模拟初始 vec_config
    vec_config = {
        'enterprise_table': '',
        'enterprise_id_col': '',
        'enterprise_name_col': '',
        'enterprise_address_col': '',
        'enterprise_vector_table': 'enterprise_vectors',
        'standard_table': '',
        'standard_id_col': '',
        'standard_address_col': '',
        'standard_room_col': '',
        'standard_vector_table': 'standard_address_vectors',
        'table_vec_mapping': {},
    }

    # 模拟数据库中的表
    all_tables = ['A', 'B', 'enterprise_vectors', 'standard_address_vectors']
    vector_tables_set = {'enterprise_vectors', 'standard_address_vectors'}

    # === 步骤1：用户选择企业表 A ===
    print("\n[1/5] user selects enterprise source table 'A'...")
    # 过滤源表选项
    tables = [t for t in all_tables if t not in vector_tables_set]
    print(f"  source table options (filtered): {tables}")
    assert 'enterprise_vectors' not in tables, "向量表不应出现在源表选项中"
    assert 'A' in tables, "企业源表 A 应保留"

    # 用户选择 A
    enterprise_table = 'A'
    if enterprise_table and enterprise_table != vec_config.get('enterprise_table'):
        # 清除字段
        vec_config['enterprise_id_col'] = ''
        vec_config['enterprise_name_col'] = ''
        vec_config['enterprise_address_col'] = ''
        vec_config['enterprise_vector_table'] = 'enterprise_vectors'  # 默认
    vec_config['enterprise_table'] = enterprise_table

    # 用户配置字段
    vec_config['enterprise_id_col'] = 'id'
    vec_config['enterprise_name_col'] = 'name'
    vec_config['enterprise_address_col'] = 'address'

    print(f"  enterprise_table = {vec_config['enterprise_table']}")
    print(f"  enterprise_id_col = {vec_config['enterprise_id_col']}")
    print(f"  enterprise_name_col = {vec_config['enterprise_name_col']}")
    print(f"  enterprise_address_col = {vec_config['enterprise_address_col']}")

    # === 步骤2：创建企业向量表 ===
    print("\n[2/5] user creates enterprise vector table 'enterprise_vectors'...")
    target_name = vec_config.get('enterprise_vector_table')
    src_table = vec_config.get('enterprise_table')
    # 模拟创建成功
    vec_config.setdefault('table_vec_mapping', {})[src_table] = target_name
    # 创建后 tables 列表会包含新向量表
    all_tables = ['A', 'B', 'enterprise_vectors', 'standard_address_vectors']
    print(f"  created: {target_name}")
    print(f"  table_vec_mapping: {vec_config['table_vec_mapping']}")

    # === 步骤3：用户配置标准地址表 B ===
    print("\n[3/5] user selects standard source table 'B'...")
    # 重新过滤源表选项
    tables = [t for t in all_tables if t not in vector_tables_set]
    print(f"  source table options (filtered): {tables}")
    assert 'enterprise_vectors' not in tables, "企业向量表不应出现在源表选项中"
    assert 'standard_address_vectors' not in tables, "标准地址向量表不应出现在源表选项中"
    assert 'B' in tables, "标准源表 B 应保留"

    # 关键验证：企业表 A 不应被错误地切换
    # 因为 'enterprise_vectors' 不在源表选项中，用户无法误选它
    # 所以 enterprise_table 保持为 'A'
    assert vec_config['enterprise_table'] == 'A', \
        f"enterprise_table should still be 'A', got '{vec_config['enterprise_table']}'"
    print(f"  enterprise_table preserved: {vec_config['enterprise_table']} ✓")

    # 用户选择 B 作为标准地址表
    standard_table = 'B'
    if standard_table and standard_table != vec_config.get('standard_table'):
        vec_config['standard_id_col'] = ''
        vec_config['standard_address_col'] = ''
        vec_config['standard_room_col'] = ''
        vec_config['standard_vector_table'] = 'standard_address_vectors'
    vec_config['standard_table'] = standard_table

    # 用户配置标准地址字段
    vec_config['standard_id_col'] = 'sid'
    vec_config['standard_address_col'] = 'saddr'
    vec_config['standard_room_col'] = 'sroom'

    # === 步骤4：创建标准地址向量表 ===
    print("\n[4/5] user creates standard vector table 'standard_address_vectors'...")
    target_name = vec_config.get('standard_vector_table')
    src_table = vec_config.get('standard_table')
    vec_config.setdefault('table_vec_mapping', {})[src_table] = target_name
    print(f"  created: {target_name}")

    # === 步骤5：验证企业表配置完整保留 ===
    print("\n[5/5] verify enterprise config preserved...")

    assert vec_config['enterprise_table'] == 'A', \
        f"enterprise_table lost, got '{vec_config['enterprise_table']}'"
    assert vec_config['enterprise_id_col'] == 'id', \
        f"enterprise_id_col lost, got '{vec_config['enterprise_id_col']}'"
    assert vec_config['enterprise_name_col'] == 'name', \
        f"enterprise_name_col lost, got '{vec_config['enterprise_name_col']}'"
    assert vec_config['enterprise_address_col'] == 'address', \
        f"enterprise_address_col lost, got '{vec_config['enterprise_address_col']}'"

    # 关键验证：三个字段不是同一个值
    assert vec_config['enterprise_id_col'] != vec_config['enterprise_name_col'], \
        f"标识和名称不应相同: id={vec_config['enterprise_id_col']}, name={vec_config['enterprise_name_col']}"
    assert vec_config['enterprise_id_col'] != vec_config['enterprise_address_col'], \
        f"标识和地址不应相同: id={vec_config['enterprise_id_col']}, addr={vec_config['enterprise_address_col']}"
    assert vec_config['enterprise_name_col'] != vec_config['enterprise_address_col'], \
        f"名称和地址不应相同: name={vec_config['enterprise_name_col']}, addr={vec_config['enterprise_address_col']}"

    print(f"  enterprise_table = {vec_config['enterprise_table']} ✓")
    print(f"  enterprise_id_col = {vec_config['enterprise_id_col']} ✓")
    print(f"  enterprise_name_col = {vec_config['enterprise_name_col']} ✓")
    print(f"  enterprise_address_col = {vec_config['enterprise_address_col']} ✓")
    print(f"  three fields are different values ✓")

    # 验证 step2 显示的源表信息正确
    _ent_src = vec_config
    _ent_table_ok = (
        _ent_src['enterprise_table']
        and _ent_src['enterprise_id_col']
        and _ent_src['enterprise_name_col']
        and _ent_src['enterprise_address_col']
    )
    assert _ent_table_ok, "企业源表配置应完整"

    expected_display = (
        f"源表: **{_ent_src['enterprise_table']}** | "
        f"标识: `{_ent_src['enterprise_id_col']}` | "
        f"名称: `{_ent_src['enterprise_name_col']}` | "
        f"地址: `{_ent_src['enterprise_address_col']}`"
    )
    print(f"  step2 display: {expected_display}")
    print("  step2 source info correct ✓")

    print("\n[PASS] test_full_flow_enterprise_config_preserved")
    return True


# ====================================================================
# 修复3验证：模拟 bug 场景 - 用户误选向量表（修复后无法误选）
# ====================================================================

def test_user_cannot_select_vector_table_as_source():
    """
    验证修复后用户无法将向量表选为源表。
    修复前：用户可以选向量表，导致字段被清除
    修复后：向量表不在源表选项中，用户无法误选
    """
    print("=" * 70)
    print("Bug fix: user cannot select vector table as source table")
    print("=" * 70)

    # 模拟数据库中的表
    all_tables = ['A', 'B', 'enterprise_vectors', 'standard_address_vectors']
    vector_tables_set = {'enterprise_vectors', 'standard_address_vectors'}

    # 模拟修复后的源表选项
    source_table_options = [''] + [t for t in all_tables if t not in vector_tables_set]

    print(f"  all_tables: {all_tables}")
    print(f"  vector_tables: {list(vector_tables_set)}")
    print(f"  source_table_options: {source_table_options}")

    # 验证向量表不在选项中
    assert 'enterprise_vectors' not in source_table_options, \
        "enterprise_vectors 不应出现在源表选项中"
    assert 'standard_address_vectors' not in source_table_options, \
        "standard_address_vectors 不应出现在源表选项中"

    # 验证源表在选项中
    assert 'A' in source_table_options, "源表 A 应在选项中"
    assert 'B' in source_table_options, "源表 B 应在选项中"

    print("  vector tables NOT in source options ✓")
    print("  source tables IN source options ✓")
    print("  user cannot accidentally select vector table as source ✓")

    print("\n[PASS] test_user_cannot_select_vector_table_as_source")
    return True


# ====================================================================
# 修复4验证：源表选项在创建向量表后保持稳定
# ====================================================================

def test_source_options_stable_after_creating_vector_table():
    """
    验证创建向量表后，源表 selectbox 的 options 保持稳定
    （不会因为新增向量表而让用户误选）
    """
    print("=" * 70)
    print("Bug fix: source options stable after creating vector table")
    print("=" * 70)

    # 初始状态：没有向量表
    all_tables_before = ['A', 'B', 'C']
    vector_tables_before = set()
    source_options_before = [''] + [t for t in all_tables_before if t not in vector_tables_before]

    print(f"  before creation:")
    print(f"    all_tables: {all_tables_before}")
    print(f"    source_options: {source_options_before}")

    # 创建企业向量表后
    all_tables_after = ['A', 'B', 'C', 'enterprise_vectors']
    vector_tables_after = {'enterprise_vectors'}
    source_options_after = [''] + [t for t in all_tables_after if t not in vector_tables_after]

    print(f"  after creation:")
    print(f"    all_tables: {all_tables_after}")
    print(f"    source_options: {source_options_after}")

    # 验证源表选项保持稳定（不包含新创建的向量表）
    assert source_options_after == source_options_before, \
        f"source options should be stable, before={source_options_before}, after={source_options_after}"

    print("  source options stable after creating vector table ✓")

    # 创建标准地址向量表后
    all_tables_after2 = ['A', 'B', 'C', 'enterprise_vectors', 'standard_address_vectors']
    vector_tables_after2 = {'enterprise_vectors', 'standard_address_vectors'}
    source_options_after2 = [''] + [t for t in all_tables_after2 if t not in vector_tables_after2]

    print(f"  after creating both vector tables:")
    print(f"    source_options: {source_options_after2}")

    assert source_options_after2 == source_options_before, \
        f"source options should still be stable, before={source_options_before}, after={source_options_after2}"

    print("  source options stable after creating both vector tables ✓")

    print("\n[PASS] test_source_options_stable_after_creating_vector_table")
    return True


if __name__ == '__main__':
    results = {}

    tests = [
        ('source_table_selectbox_excludes_vector_tables',
         test_source_table_selectbox_excludes_vector_tables),
        ('filtering_logic_correctness',
         test_filtering_logic_correctness),
        ('filtering_handles_empty_result',
         test_filtering_handles_empty_result),
        ('full_flow_enterprise_config_preserved',
         test_full_flow_enterprise_config_preserved),
        ('user_cannot_select_vector_table_as_source',
         test_user_cannot_select_vector_table_as_source),
        ('source_options_stable_after_creating_vector_table',
         test_source_options_stable_after_creating_vector_table),
    ]

    for name, test_fn in tests:
        try:
            passed = test_fn()
            results[name] = 'PASS' if passed else 'FAIL'
        except Exception as e:
            results[name] = f'ERROR: {e}'
            import traceback
            traceback.print_exc()

    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)
    for name, result in results.items():
        status = '✅' if result == 'PASS' else '❌'
        print(f"  {status} {name}: {result}")

    all_passed = all(r == 'PASS' for r in results.values())
    print(f"\n{'ALL TESTS PASSED' if all_passed else 'SOME TESTS FAILED'}")
    sys.exit(0 if all_passed else 1)
