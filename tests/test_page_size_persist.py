"""
page_size 持久化逻辑测试
========================

验证 _restore_page_size 和 _make_page_size_persist_callback 的行为，
确保 page_size 在 widget 状态被 Streamlit 清除后能从持久化变量恢复。

背景：
    精排匹配结果人工纠正/人工选择跳转返回后，每页行数重置为 20。
    根因：Streamlit 的 widget 状态管理机制——当 widget 在某次渲染中未出现，
    session_state[key] 会被清除，下次渲染时 selectbox 使用 index 默认值（20）。

修复：
    使用非 widget key 的持久化变量（{key}_persist）存储用户选择，
    在 selectbox 渲染前通过 _restore_page_size 恢复。
"""

import sys
import os
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _setup_streamlit_state(initial_state=None):
    """
    模拟 Streamlit session_state 环境。

    使用 dict 替代 st.session_state，并 patch streamlit 模块。
    返回 (state_dict, patcher)，调用方需要在 finally 中 stop patcher。
    """
    import types

    state = dict(initial_state) if initial_state else {}

    # 创建一个类似 st.session_state 的对象
    class _FakeSessionState:
        def __init__(self, data):
            self._data = data

        def __contains__(self, key):
            return key in self._data

        def __getitem__(self, key):
            return self._data[key]

        def __setitem__(self, key, value):
            self._data[key] = value

        def get(self, key, default=None):
            return self._data.get(key, default)

        def __delitem__(self, key):
            del self._data[key]

    fake_st = types.SimpleNamespace(session_state=_FakeSessionState(state))

    import streamlit
    patcher = patch('streamlit.session_state', state)
    # 直接 patch app_common 中的 st.session_state
    import app_common
    original_st = app_common.st
    app_common.st = fake_st

    return state, app_common, original_st


def _restore_state(app_common, original_st):
    """恢复 app_common.st"""
    app_common.st = original_st


# ---------------------------------------------------------------------------
# _restore_page_size
# ---------------------------------------------------------------------------

def test_restore_page_size_initializes_persist_with_default():
    """首次调用：persist_key 不存在，使用 default_value 初始化"""
    print("=" * 60)
    print("_restore_page_size: 首次调用初始化持久化变量")
    print("=" * 60)

    state, app_common, original_st = _setup_streamlit_state()
    try:
        # 调用 _restore_page_size，default_value=20
        app_common._restore_page_size('match_page_size', default_value=20)

        # persist_key 应该被初始化为 20
        assert 'match_page_size_persist' in state, "persist_key 未被创建"
        assert state['match_page_size_persist'] == 20, \
            f"persist_key 应为 20，实际 {state['match_page_size_persist']}"

        # widget key 也应该被恢复（因为不存在）
        assert 'match_page_size' in state, "widget key 未被恢复"
        assert state['match_page_size'] == 20, \
            f"widget key 应为 20，实际 {state['match_page_size']}"

        print("  match_page_size_persist = 20 ✓")
        print("  match_page_size = 20 ✓")
        print("\n[PASS] test_restore_page_size_initializes_persist_with_default")
        return True
    finally:
        _restore_state(app_common, original_st)


def test_restore_page_size_recovers_from_persist_when_widget_cleared():
    """widget key 被清除时，从 persist_key 恢复（核心场景）"""
    print("=" * 60)
    print("_restore_page_size: widget 被清除时从 persist 恢复")
    print("=" * 60)

    # 模拟用户之前设置了 100，persist 保留，但 widget key 被 Streamlit 清除
    initial_state = {'match_page_size_persist': 100}
    state, app_common, original_st = _setup_streamlit_state(initial_state)
    try:
        # 注意：match_page_size 不在 state 中（被 Streamlit 清除）
        assert 'match_page_size' not in state, "测试前提错误：widget key 不应存在"

        app_common._restore_page_size('match_page_size', default_value=20)

        # widget key 应该从 persist 恢复为 100
        assert state['match_page_size'] == 100, \
            f"widget key 应从 persist 恢复为 100，实际 {state['match_page_size']}"

        # persist_key 保持不变
        assert state['match_page_size_persist'] == 100

        print("  初始: match_page_size_persist=100, match_page_size 不存在")
        print("  恢复后: match_page_size=100 ✓")
        print("\n[PASS] test_restore_page_size_recovers_from_persist_when_widget_cleared")
        return True
    finally:
        _restore_state(app_common, original_st)


def test_restore_page_size_does_not_override_existing_widget():
    """widget key 存在时，不覆盖（用户当前选择优先）"""
    print("=" * 60)
    print("_restore_page_size: widget 存在时不覆盖")
    print("=" * 60)

    # widget key 存在（值为 50），persist 也存在（值为 100）
    initial_state = {'match_page_size': 50, 'match_page_size_persist': 100}
    state, app_common, original_st = _setup_streamlit_state(initial_state)
    try:
        app_common._restore_page_size('match_page_size', default_value=20)

        # widget key 应该保持 50（不被 persist 覆盖）
        assert state['match_page_size'] == 50, \
            f"widget key 应保持 50，实际 {state['match_page_size']}"

        # persist_key 保持 100
        assert state['match_page_size_persist'] == 100

        print("  初始: match_page_size=50, match_page_size_persist=100")
        print("  恢复后: match_page_size=50（未覆盖）✓")
        print("\n[PASS] test_restore_page_size_does_not_override_existing_widget")
        return True
    finally:
        _restore_state(app_common, original_st)


def test_restore_page_size_uses_custom_default():
    """使用自定义 default_value"""
    print("=" * 60)
    print("_restore_page_size: 自定义 default_value")
    print("=" * 60)

    state, app_common, original_st = _setup_streamlit_state()
    try:
        app_common._restore_page_size('custom_page_size', default_value=50)

        assert state['custom_page_size_persist'] == 50
        assert state['custom_page_size'] == 50

        print("  custom_page_size_persist = 50 ✓")
        print("  custom_page_size = 50 ✓")
        print("\n[PASS] test_restore_page_size_uses_custom_default")
        return True
    finally:
        _restore_state(app_common, original_st)


# ---------------------------------------------------------------------------
# _make_page_size_persist_callback
# ---------------------------------------------------------------------------

def test_persist_callback_updates_persist_key():
    """on_change 回调：用户改变 selectbox 时，同步更新 persist_key"""
    print("=" * 60)
    print("_make_page_size_persist_callback: 更新 persist_key")
    print("=" * 60)

    initial_state = {'match_page_size': 50, 'match_page_size_persist': 20}
    state, app_common, original_st = _setup_streamlit_state(initial_state)
    try:
        callback = app_common._make_page_size_persist_callback('match_page_size')

        # 模拟用户将 selectbox 改为 100
        state['match_page_size'] = 100
        callback()

        # persist_key 应该同步更新为 100
        assert state['match_page_size_persist'] == 100, \
            f"persist_key 应更新为 100，实际 {state['match_page_size_persist']}"

        print("  用户改 selectbox 为 100 → persist_key 更新为 100 ✓")
        print("\n[PASS] test_persist_callback_updates_persist_key")
        return True
    finally:
        _restore_state(app_common, original_st)


def test_persist_callback_isolated_per_key():
    """不同 key 的回调互不影响"""
    print("=" * 60)
    print("_make_page_size_persist_callback: 不同 key 隔离")
    print("=" * 60)

    initial_state = {
        'match_page_size': 50, 'match_page_size_persist': 50,
        'recall_page_size': 20, 'recall_page_size_persist': 20,
    }
    state, app_common, original_st = _setup_streamlit_state(initial_state)
    try:
        match_cb = app_common._make_page_size_persist_callback('match_page_size')
        recall_cb = app_common._make_page_size_persist_callback('recall_page_size')

        # 修改 match_page_size
        state['match_page_size'] = 100
        match_cb()

        # match_persist 应更新，recall_persist 不变
        assert state['match_page_size_persist'] == 100
        assert state['recall_page_size_persist'] == 20

        print("  修改 match_page_size=100 → match_persist=100, recall_persist=20 ✓")
        print("\n[PASS] test_persist_callback_isolated_per_key")
        return True
    finally:
        _restore_state(app_common, original_st)


# ---------------------------------------------------------------------------
# 端到端场景：模拟用户跳转返回后 page_size 恢复
# ---------------------------------------------------------------------------

def test_e2e_scenario_page_size_recovery_after_widget_cleared():
    """端到端：模拟用户设置 page_size=100 → widget 被清除 → 恢复为 100"""
    print("=" * 60)
    print("端到端: page_size 跳转返回后恢复")
    print("=" * 60)

    state, app_common, original_st = _setup_streamlit_state()
    try:
        # Step 1: 首次渲染，selectbox 使用默认值 20
        app_common._restore_page_size('match_page_size', default_value=20)
        assert state['match_page_size'] == 20
        assert state['match_page_size_persist'] == 20
        print(f"  Step 1 首次渲染: page_size=20, persist=20 ✓")

        # Step 2: 用户改为 100，触发 on_change 回调
        callback = app_common._make_page_size_persist_callback('match_page_size')
        state['match_page_size'] = 100
        callback()
        assert state['match_page_size_persist'] == 100
        print(f"  Step 2 用户改 100: page_size=100, persist=100 ✓")

        # Step 3: 模拟 widget 被 Streamlit 清除（跳转到人工纠正页面再返回）
        del state['match_page_size']
        assert 'match_page_size' not in state
        print(f"  Step 3 widget 被清除: match_page_size 不存在 ✓")

        # Step 4: 下次渲染前调用 _restore_page_size 恢复
        app_common._restore_page_size('match_page_size', default_value=20)
        assert state['match_page_size'] == 100, \
            f"应恢复为 100，实际 {state['match_page_size']}"
        assert state['match_page_size_persist'] == 100
        print(f"  Step 4 恢复后: page_size=100, persist=100 ✓")

        print("\n[PASS] test_e2e_scenario_page_size_recovery_after_widget_cleared")
        return True
    finally:
        _restore_state(app_common, original_st)


# ---------------------------------------------------------------------------
# PAGE_SIZE_WIDGET_KEYS 完整性
# ---------------------------------------------------------------------------

def test_page_size_widget_keys_covers_all_result_management_selectboxes():
    """PAGE_SIZE_WIDGET_KEYS 应覆盖 result_management 中所有 page_size selectbox 的 key"""
    print("=" * 60)
    print("PAGE_SIZE_WIDGET_KEYS: 覆盖所有 page_size selectbox")
    print("=" * 60)

    # result_management.py 中实际使用的 page_size widget key（从代码中提取）
    actual_keys = {
        'recall_page_size',
        'match_page_size',
        'sim_page_size',
        'mgeo_copy_page_size',
        'tagging_page_size',
        'tagging_17_page_size',
        'tagging_17_2_page_size',
    }

    declared_keys = set(app_common_module().PAGE_SIZE_WIDGET_KEYS)

    missing = actual_keys - declared_keys
    assert not missing, f"PAGE_SIZE_WIDGET_KEYS 缺少: {missing}"

    print(f"  实际使用: {sorted(actual_keys)}")
    print(f"  已声明: {sorted(declared_keys)}")
    print(f"  缺失: {missing or '无'} ✓")
    print("\n[PASS] test_page_size_widget_keys_covers_all_result_management_selectboxes")
    return True


def app_common_module():
    """导入 app_common 模块（不触发 streamlit 初始化）"""
    import app_common
    return app_common


def run_all_tests():
    """运行全部测试"""
    tests = [
        test_restore_page_size_initializes_persist_with_default,
        test_restore_page_size_recovers_from_persist_when_widget_cleared,
        test_restore_page_size_does_not_override_existing_widget,
        test_restore_page_size_uses_custom_default,
        test_persist_callback_updates_persist_key,
        test_persist_callback_isolated_per_key,
        test_e2e_scenario_page_size_recovery_after_widget_cleared,
        test_page_size_widget_keys_covers_all_result_management_selectboxes,
    ]

    passed = 0
    failed = 0
    for test in tests:
        try:
            result = test()
            if result is None or result is True:
                passed += 1
            else:
                failed += 1
                print(f"\n[FAIL] {test.__name__}")
        except Exception as e:
            failed += 1
            import traceback
            print(f"\n[FAIL] {test.__name__}: {e}")
            traceback.print_exc()

    print("\n" + "=" * 60)
    print(f"测试结果: {passed} passed, {failed} failed")
    print("=" * 60)
    return failed == 0


if __name__ == '__main__':
    success = run_all_tests()
    sys.exit(0 if success else 1)
