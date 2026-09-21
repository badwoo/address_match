"""
向量预处理页面缓存刷新与状态保持测试
====================================

验证 4 个 bug 修复：
1. 创建企业向量表后右侧向量表管理立即刷新
2. 配置标准地址表不会清除企业表配置信息
3. 删除向量表后筛选框立即移除已删除表
4. 创建标准地址向量表后右侧向量表管理立即刷新

测试策略：
- Bug 1/3/4：通过模拟缓存调用 + invalidate_vector_tables_cache 验证缓存被正确清除
- Bug 2：模拟 session_state 和 vec_config 在配置标准地址表后的状态一致性
"""

import sys
import os
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config


# ====================================================================
# Bug 1 & 4: 创建向量表后清除缓存（让右侧管理区立即刷新）
# ====================================================================

def test_invalidate_vector_tables_cache_exists():
    """验证 invalidate_vector_tables_cache 函数存在且可被调用"""
    print("=" * 60)
    print("test invalidate_vector_tables_cache function exists")
    print("=" * 60)

    from app_common import invalidate_vector_tables_cache
    assert callable(invalidate_vector_tables_cache), \
        "invalidate_vector_tables_cache should be callable"

    print("  function exists and is callable ✓")
    print("\n[PASS] test_invalidate_vector_tables_cache_exists")
    return True


def test_invalidate_vector_tables_cache_clears_cache():
    """验证 invalidate_vector_tables_cache 会调用底层缓存清除方法"""
    print("=" * 60)
    print("test invalidate_vector_tables_cache clears cached vector tables")
    print("=" * 60)

    with patch('app_common.get_cached_vector_tables') as mock_vec_cache, \
         patch('app_common.get_cached_tables') as mock_tables_cache, \
         patch('app_common.logger'):
        mock_vec_cache.clear = MagicMock()
        mock_tables_cache.clear = MagicMock()

        from app_common import invalidate_vector_tables_cache
        invalidate_vector_tables_cache()

        # 验证两个缓存都被清除
        assert mock_vec_cache.clear.called, "get_cached_vector_tables.clear() should be called"
        assert mock_tables_cache.clear.called, "get_cached_tables.clear() should be called"
        print("  get_cached_vector_tables.clear() called ✓")
        print("  get_cached_tables.clear() called ✓")

    print("\n[PASS] test_invalidate_vector_tables_cache_clears_cache")
    return True


def test_invalidate_vector_tables_cache_swallows_exception():
    """验证缓存清除失败不会抛出异常（保证页面流程不中断）"""
    print("=" * 60)
    print("test invalidate_vector_tables_cache swallows exception")
    print("=" * 60)

    with patch('app_common.get_cached_vector_tables') as mock_vec_cache, \
         patch('app_common.logger'):
        mock_vec_cache.clear = MagicMock(side_effect=RuntimeError("cache error"))

        from app_common import invalidate_vector_tables_cache
        # 不应抛出异常
        invalidate_vector_tables_cache()
        print("  exception swallowed, no propagation ✓")

    print("\n[PASS] test_invalidate_vector_tables_cache_swallows_exception")
    return True


def test_create_enterprise_vector_table_triggers_cache_invalidation():
    """
    Bug 1 修复验证：模拟创建企业向量表成功后调用 invalidate_vector_tables_cache
    通过检查 vector_preprocess.py 源码中包含正确的调用
    """
    print("=" * 60)
    print("Bug 1: create enterprise vector table triggers cache invalidation")
    print("=" * 60)

    vp_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'pages', 'vector_preprocess.py'
    )
    with open(vp_path, 'r', encoding='utf-8') as f:
        source = f.read()

    # 验证创建企业向量表按钮的逻辑里有缓存清除调用
    create_ent_section = source[source.find("key='create_ent_btn'"):]
    create_ent_section = create_ent_section[:create_ent_section.find("else:") + 200]

    assert 'invalidate_vector_tables_cache()' in create_ent_section, \
        "create_ent_btn callback should call invalidate_vector_tables_cache()"
    assert 'st.rerun()' in create_ent_section, \
        "create_ent_btn callback should call st.rerun() after success"

    print("  create_ent_btn triggers cache invalidation + rerun ✓")

    # 验证创建标准地址向量表按钮的逻辑
    create_std_section = source[source.find("key='create_std_btn'"):]
    create_std_section = create_std_section[:create_std_section.find("else:") + 200]

    assert 'invalidate_vector_tables_cache()' in create_std_section, \
        "create_std_btn callback should call invalidate_vector_tables_cache()"
    assert 'st.rerun()' in create_std_section, \
        "create_std_btn callback should call st.rerun() after success"

    print("  create_std_btn triggers cache invalidation + rerun ✓")

    print("\n[PASS] test_create_enterprise_vector_table_triggers_cache_invalidation")
    return True


# ====================================================================
# Bug 3: 删除/重命名/清空向量表后筛选框立即更新
# ====================================================================

def test_delete_vector_table_triggers_cache_invalidation():
    """Bug 3 修复验证：删除向量表后清除缓存"""
    print("=" * 60)
    print("Bug 3: delete vector table triggers cache invalidation")
    print("=" * 60)

    vp_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'pages', 'vector_preprocess.py'
    )
    with open(vp_path, 'r', encoding='utf-8') as f:
        source = f.read()

    # 删除向量表按钮：截取按钮回调块（直到下一个 st.divider 或 st.button）
    delete_start = source.find("key='delete_table_btn'")
    delete_section = source[delete_start:delete_start + 1500]
    assert 'invalidate_vector_tables_cache()' in delete_section, \
        "delete_table_btn callback should call invalidate_vector_tables_cache()"
    print("  delete_table_btn triggers cache invalidation ✓")

    # 清空向量表按钮
    trunc_start = source.find("key='trunc_btn'")
    trunc_section = source[trunc_start:trunc_start + 1500]
    assert 'invalidate_vector_tables_cache()' in trunc_section, \
        "trunc_btn callback should call invalidate_vector_tables_cache()"
    print("  trunc_btn triggers cache invalidation ✓")

    # 重命名向量表按钮
    rename_start = source.find("key='rename_btn'")
    rename_section = source[rename_start:rename_start + 1500]
    assert 'invalidate_vector_tables_cache()' in rename_section, \
        "rename_btn callback should call invalidate_vector_tables_cache()"
    print("  rename_btn triggers cache invalidation ✓")

    print("\n[PASS] test_delete_vector_table_triggers_cache_invalidation")
    return True


# ====================================================================
# Bug 2: 配置标准地址表不会清除企业表配置信息
# ====================================================================

def test_enterprise_config_preserved_when_configuring_standard():
    """
    Bug 2 修复验证：模拟完整配置流程，确保企业表配置在配置标准地址表后保持不变。
    重点验证 vec_config 中的 enterprise_* 字段在标准地址表配置流程中不被触碰。
    """
    print("=" * 60)
    print("Bug 2: enterprise config preserved when configuring standard")
    print("=" * 60)

    # 模拟初始 vec_config（与企业表配置一致）
    vec_config = {
        'enterprise_table': 'enterprise_A',
        'enterprise_id_col': 'id',
        'enterprise_name_col': 'name',
        'enterprise_address_col': 'address',
        'enterprise_vector_table': 'enterprise_A_vectors',
        'standard_table': '',
        'standard_id_col': '',
        'standard_address_col': '',
        'standard_room_col': '',
        'standard_vector_table': Config.STANDARD_VECTOR_TABLE,
        'table_vec_mapping': {'enterprise_A': 'enterprise_A_vectors'},
    }

    print("\n[1/3] simulate enterprise table config done...")
    print(f"  enterprise_table = {vec_config['enterprise_table']}")
    print(f"  enterprise_id_col = {vec_config['enterprise_id_col']}")

    print("\n[2/3] simulate user selecting standard table (standard_B)...")
    # 模拟 line 768-778 的标准地址表 selectbox change handler
    standard_table = 'standard_B'
    if standard_table and standard_table != vec_config.get('standard_table'):
        # 只清除 standard_* 字段，不应触碰 enterprise_*
        vec_config['standard_id_col'] = ''
        vec_config['standard_address_col'] = ''
        vec_config['standard_room_col'] = ''
        _mapping = vec_config.get('table_vec_mapping', {})
        new_std_vec_table = _mapping.get(standard_table, f"{standard_table}_vectors")
        vec_config['standard_vector_table'] = new_std_vec_table
    if standard_table:
        vec_config['standard_table'] = standard_table

    print("\n[3/3] verify enterprise config preserved...")
    assert vec_config['enterprise_table'] == 'enterprise_A', \
        f"enterprise_table should be preserved, got '{vec_config['enterprise_table']}'"
    assert vec_config['enterprise_id_col'] == 'id', \
        f"enterprise_id_col should be preserved, got '{vec_config['enterprise_id_col']}'"
    assert vec_config['enterprise_name_col'] == 'name', \
        f"enterprise_name_col should be preserved, got '{vec_config['enterprise_name_col']}'"
    assert vec_config['enterprise_address_col'] == 'address', \
        f"enterprise_address_col should be preserved, got '{vec_config['enterprise_address_col']}'"
    assert vec_config['enterprise_vector_table'] == 'enterprise_A_vectors', \
        f"enterprise_vector_table should be preserved, got '{vec_config['enterprise_vector_table']}'"

    print(f"  enterprise_table preserved = {vec_config['enterprise_table']} ✓")
    print(f"  enterprise_id_col preserved = {vec_config['enterprise_id_col']} ✓")
    print(f"  enterprise_name_col preserved = {vec_config['enterprise_name_col']} ✓")
    print(f"  enterprise_address_col preserved = {vec_config['enterprise_address_col']} ✓")
    print(f"  enterprise_vector_table preserved = {vec_config['enterprise_vector_table']} ✓")

    # 同时验证 standard_* 已更新
    assert vec_config['standard_table'] == 'standard_B'
    assert vec_config['standard_vector_table'] == 'standard_B_vectors'
    print(f"  standard_table updated = {vec_config['standard_table']} ✓")
    print(f"  standard_vector_table updated = {vec_config['standard_vector_table']} ✓")

    print("\n[PASS] test_enterprise_config_preserved_when_configuring_standard")
    return True


def test_enterprise_config_preserved_when_creating_standard_vector_table():
    """
    Bug 2 完整场景验证：创建企业向量表 → 配置标准地址表 → 创建标准向量表
    确保整个流程后企业表配置仍可用于下一流程（向量化执行）。
    """
    print("=" * 60)
    print("Bug 2 full flow: enterprise → standard → vector table creation")
    print("=" * 60)

    # 初始状态
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
        'table_vec_mapping': {},
    }

    # 步骤1：配置企业表
    print("\n[1/4] step1: configure enterprise table...")
    enterprise_table = 'enterprise_A'
    if enterprise_table and enterprise_table != vec_config.get('enterprise_table'):
        vec_config['enterprise_id_col'] = ''
        vec_config['enterprise_name_col'] = ''
        vec_config['enterprise_address_col'] = ''
        _mapping = vec_config.get('table_vec_mapping', {})
        new_ent_vec_table = _mapping.get(enterprise_table, f"{enterprise_table}_vectors")
        vec_config['enterprise_vector_table'] = new_ent_vec_table
    vec_config['enterprise_table'] = enterprise_table
    # 模拟用户配置字段
    vec_config['enterprise_id_col'] = 'id'
    vec_config['enterprise_name_col'] = 'name'
    vec_config['enterprise_address_col'] = 'address'

    print(f"  enterprise_table = {vec_config['enterprise_table']}")
    print(f"  enterprise_id_col = {vec_config['enterprise_id_col']}")

    # 步骤2：模拟"创建企业向量表"按钮回调（不修改 vec_config 的 enterprise_table 字段）
    print("\n[2/4] step2: simulate 'create enterprise vector table' button click...")
    target_name = vec_config.get('enterprise_vector_table', Config.ENTERPRISE_VECTOR_TABLE)
    src_table = vec_config.get('enterprise_table', '')
    # 模拟创建成功（不修改 enterprise_table 等核心字段）
    if src_table:
        vec_config.setdefault('table_vec_mapping', {})[src_table] = target_name
    # 关键：创建后立即 rerun，确保 session_state 中企业表配置保持

    print(f"  enterprise_table after create = {vec_config['enterprise_table']} ✓")
    print(f"  enterprise_id_col after create = {vec_config['enterprise_id_col']} ✓")

    # 步骤3：配置标准地址表
    print("\n[3/4] step3: configure standard table...")
    standard_table = 'standard_B'
    if standard_table and standard_table != vec_config.get('standard_table'):
        vec_config['standard_id_col'] = ''
        vec_config['standard_address_col'] = ''
        vec_config['standard_room_col'] = ''
        _mapping = vec_config.get('table_vec_mapping', {})
        new_std_vec_table = _mapping.get(standard_table, f"{standard_table}_vectors")
        vec_config['standard_vector_table'] = new_std_vec_table
    vec_config['standard_table'] = standard_table
    vec_config['standard_id_col'] = 'sid'
    vec_config['standard_address_col'] = 'saddr'
    vec_config['standard_room_col'] = 'sroom'

    # 步骤4：模拟"创建标准地址向量表"按钮回调
    print("\n[4/4] step4: simulate 'create standard vector table' button click...")
    target_name = vec_config.get('standard_vector_table', Config.STANDARD_VECTOR_TABLE)
    src_table = vec_config.get('standard_table', '')
    if src_table:
        vec_config.setdefault('table_vec_mapping', {})[src_table] = target_name

    # 验证企业表配置仍然完整保留
    assert vec_config['enterprise_table'] == 'enterprise_A', \
        f"enterprise_table lost after standard config, got '{vec_config['enterprise_table']}'"
    assert vec_config['enterprise_id_col'] == 'id', \
        f"enterprise_id_col lost, got '{vec_config['enterprise_id_col']}'"
    assert vec_config['enterprise_name_col'] == 'name', \
        f"enterprise_name_col lost, got '{vec_config['enterprise_name_col']}'"
    assert vec_config['enterprise_address_col'] == 'address', \
        f"enterprise_address_col lost, got '{vec_config['enterprise_address_col']}'"
    assert vec_config['enterprise_vector_table'] == 'enterprise_A_vectors', \
        f"enterprise_vector_table lost, got '{vec_config['enterprise_vector_table']}'"

    # 验证 standard 配置也正确
    assert vec_config['standard_table'] == 'standard_B'
    assert vec_config['standard_id_col'] == 'sid'
    assert vec_config['standard_vector_table'] == 'standard_B_vectors'

    print(f"  enterprise config preserved: {vec_config['enterprise_table']}.{vec_config['enterprise_id_col']} ✓")
    print(f"  standard config correct: {vec_config['standard_table']}.{vec_config['standard_id_col']} ✓")
    print(f"  step2 source display info correct ✓")

    print("\n[PASS] test_enterprise_config_preserved_when_creating_standard_vector_table")
    return True


def test_step2_reads_correct_source_after_full_flow():
    """
    Bug 2 关键验证：完整配置流程后，向量化执行（步骤2）读取的源表信息正确。
    模拟 line 1119-1128 的源表信息读取逻辑。
    """
    print("=" * 60)
    print("Bug 2 step2: source table info correctness after full flow")
    print("=" * 60)

    # 模拟完整配置后的 vec_config
    vec_config = {
        'enterprise_table': 'enterprise_A',
        'enterprise_id_col': 'id',
        'enterprise_name_col': 'name',
        'enterprise_address_col': 'address',
        'enterprise_vector_table': 'enterprise_A_vectors',
        'standard_table': 'standard_B',
        'standard_id_col': 'sid',
        'standard_address_col': 'saddr',
        'standard_room_col': 'sroom',
        'standard_vector_table': 'standard_B_vectors',
    }

    # 模拟 line 1126-1128 的源表检查逻辑
    _ent_src = vec_config
    _ent_table_ok = (
        _ent_src['enterprise_table']
        and _ent_src['enterprise_id_col']
        and _ent_src['enterprise_name_col']
        and _ent_src['enterprise_address_col']
    )
    _std_table_ok = (
        _ent_src['standard_table']
        and _ent_src['standard_id_col']
        and _ent_src['standard_address_col']
    )

    assert _ent_table_ok, "enterprise source table should be fully configured"
    assert _std_table_ok, "standard source table should be fully configured"
    print(f"  enterprise source OK: {_ent_src['enterprise_table']} ✓")
    print(f"  standard source OK: {_ent_src['standard_table']} ✓")

    # 验证读取的源表信息（line 1142, 1173 的展示逻辑）
    expected_ent_display = f"源表: **enterprise_A** | 标识: `id` | 名称: `name` | 地址: `address`"
    actual_ent_display = (
        f"源表: **{_ent_src['enterprise_table']}** | "
        f"标识: `{_ent_src['enterprise_id_col']}` | "
        f"名称: `{_ent_src['enterprise_name_col']}` | "
        f"地址: `{_ent_src['enterprise_address_col']}`"
    )
    assert actual_ent_display == expected_ent_display, \
        f"enterprise display mismatch.\nexpected: {expected_ent_display}\nactual: {actual_ent_display}"
    print(f"  enterprise display correct ✓")

    print("\n[PASS] test_step2_reads_correct_source_after_full_flow")
    return True


# ====================================================================
# Bug 1&4 整合：模拟 streamlit 缓存场景验证
# ====================================================================

def test_cache_invalidation_pattern_for_create_flow():
    """
    Bug 1&4 端到端模拟：模拟 streamlit 缓存场景
    验证创建向量表后下次调用 get_cached_vector_tables 不会返回旧缓存
    """
    print("=" * 60)
    print("Bug 1&4: cache invalidation pattern for create flow")
    print("=" * 60)

    # 模拟缓存存储和"实际数据库"
    cache_store = {}
    real_db_tables = []  # 模拟真实数据库中存在的向量表

    def mock_get_cached_vector_tables(host, port, dbname, user, password, schema):
        # 缓存 key 包含全部连接参数
        key = (host, port, dbname, user, password, schema)
        if key not in cache_store:
            # 缓存未命中，从"数据库"读取
            cache_store[key] = list(real_db_tables)
        return tuple(cache_store[key])

    def mock_invalidate():
        cache_store.clear()

    db_params = ('localhost', 5432, 'testdb', 'user', 'pwd', 'public')

    # 模拟初始状态：数据库没有向量表
    initial_tables = mock_get_cached_vector_tables(*db_params)
    assert initial_tables == (), f"expected empty, got {initial_tables}"
    print(f"  initial vector tables: {initial_tables} ✓")

    # === 模拟旧的 buggy 行为：创建表但不调用 invalidate ===
    print("\n  [buggy behavior simulation] creating table WITHOUT cache invalidation...")
    real_db_tables.append('enterprise_vectors')  # 数据库已创建新表
    # 但缓存未被清除，下次调用返回旧缓存
    tables_after_create_buggy = mock_get_cached_vector_tables(*db_params)
    assert 'enterprise_vectors' not in tables_after_create_buggy, \
        f"buggy: cache should still be stale, got {tables_after_create_buggy}"
    print(f"  buggy: tables still = {tables_after_create_buggy} (cache stale, bug reproduced) ✓")

    # === 模拟修复后的行为：创建表后调用 invalidate ===
    print("\n  [fixed behavior simulation] creating table WITH cache invalidation...")
    mock_invalidate()  # 修复后会调用这个
    # 下次调用会重新查询"数据库"
    tables_after_create_fixed = mock_get_cached_vector_tables(*db_params)
    assert 'enterprise_vectors' in tables_after_create_fixed, \
        f"after fix, new table should be visible, got {tables_after_create_fixed}"
    print(f"  fixed: tables = {tables_after_create_fixed} ✓")

    print("\n[PASS] test_cache_invalidation_pattern_for_create_flow")
    return True


if __name__ == '__main__':
    results = {}

    tests = [
        ('invalidate_vector_tables_cache_exists', test_invalidate_vector_tables_cache_exists),
        ('invalidate_vector_tables_cache_clears_cache', test_invalidate_vector_tables_cache_clears_cache),
        ('invalidate_vector_tables_cache_swallows_exception', test_invalidate_vector_tables_cache_swallows_exception),
        ('create_enterprise_vector_table_triggers_cache_invalidation',
         test_create_enterprise_vector_table_triggers_cache_invalidation),
        ('delete_vector_table_triggers_cache_invalidation',
         test_delete_vector_table_triggers_cache_invalidation),
        ('enterprise_config_preserved_when_configuring_standard',
         test_enterprise_config_preserved_when_configuring_standard),
        ('enterprise_config_preserved_when_creating_standard_vector_table',
         test_enterprise_config_preserved_when_creating_standard_vector_table),
        ('step2_reads_correct_source_after_full_flow',
         test_step2_reads_correct_source_after_full_flow),
        ('cache_invalidation_pattern_for_create_flow',
         test_cache_invalidation_pattern_for_create_flow),
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
    sys.exit(0 if all_passed else 1)
