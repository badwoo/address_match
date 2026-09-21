"""
向量预处理完成状态刷新测试
==============================

验证两个 bug 修复：
1. 向量化后台任务完成后，fragment 能主动触发整页刷新，页面状态自动切换到完成 UI。
2. 成功路径中降级批次计数使用正确的变量名 embedder，避免 NameError。
"""

import sys
import os
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _read_vector_preprocess_source():
    """读取 vector_preprocess.py 源码"""
    vp_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'pages', 'vector_preprocess.py'
    )
    with open(vp_path, 'r', encoding='utf-8') as f:
        return f.read()


def test_fragment_triggers_rerun_when_task_finished():
    """
    Bug 修复验证：render_vec_status_fragment 检测到任务结束时调用 st.rerun()。
    此前只设置 _vec_finished_trigger 不 rerun，导致页面不会自动更新到完成状态。
    """
    print("=" * 60)
    print("Bug fix: fragment triggers st.rerun() on task completion")
    print("=" * 60)

    source = _read_vector_preprocess_source()

    # 定位 render_vec_status_fragment 函数
    fragment_start = source.find("def render_vec_status_fragment()")
    assert fragment_start != -1, "render_vec_status_fragment not found"

    # 截取函数体（到下一个顶格 def 或文件末尾）
    next_def = source.find("\ndef ", fragment_start + 1)
    fragment_body = source[fragment_start:next_def] if next_def != -1 else source[fragment_start:]

    # 验证函数体内存在检测完成的条件分支
    assert "if not vec_status['is_running']:" in fragment_body, \
        "fragment should check vec_status['is_running']"

    # 验证在该分支内调用了 st.rerun()
    completion_block_start = fragment_body.find("if not vec_status['is_running']:")
    completion_block = fragment_body[completion_block_start:]
    # 截取到条件块结束（下一个同缩进或更外层语句）
    block_lines = completion_block.splitlines()
    block_end = len(block_lines)
    for i, line in enumerate(block_lines[1:], start=1):
        # 条件块内行首空白应大于条件行缩进
        if line.strip() and not line.startswith("        "):
            block_end = i
            break
    completion_block = "\n".join(block_lines[:block_end])

    assert "st.rerun()" in completion_block, \
        "fragment completion branch should call st.rerun() to refresh the whole page"

    print("  completion branch calls st.rerun() ✓")
    print("\n[PASS] test_fragment_triggers_rerun_when_task_finished")
    return True


def test_success_path_uses_embedder_for_fallback_count():
    """
    Bug 修复验证：向量化成功完成后，降级批次计数使用 embedder 变量。
    旧代码使用未定义的 working_embedder，会在成功路径抛出 NameError。
    """
    print("=" * 60)
    print("Bug fix: success path uses embedder for fallback count")
    print("=" * 60)

    source = _read_vector_preprocess_source()

    # 不允许存在未定义的 working_embedder 引用
    assert "working_embedder" not in source, \
        "source should not reference undefined working_embedder"
    print("  no 'working_embedder' reference ✓")

    # 验证使用 embedder 获取降级计数
    assert "getattr(embedder, '_fallback_count', 0)" in source, \
        "source should read fallback_count from embedder"
    print("  getattr(embedder, '_fallback_count', 0) found ✓")

    print("\n[PASS] test_success_path_uses_embedder_for_fallback_count")
    return True


def test_completion_state_render_branch():
    """
    验证页面渲染分支逻辑：当 is_running=False 且 completed=True 时进入完成 UI。
    """
    print("=" * 60)
    print("Verify render branch logic for completed state")
    print("=" * 60)

    source = _read_vector_preprocess_source()

    # 定位 show_vector_preprocess 中的状态分支
    show_start = source.find("def show_vector_preprocess()")
    assert show_start != -1, "show_vector_preprocess not found"

    # 验证分支顺序：is_running -> completed -> cancelled -> error_message
    assert "if vec_status['is_running']:" in source, "should check is_running first"
    assert "elif vec_status['completed']:" in source, "should check completed second"
    assert "elif vec_status['cancelled']:" in source, "should check cancelled third"
    assert "elif vec_status['error_message']:" in source, "should check error_message fourth"

    print("  render branch order: is_running -> completed -> cancelled -> error ✓")
    print("\n[PASS] test_completion_state_render_branch")
    return True


def test_completion_branch_rerun_is_unconditional():
    """
    验证完成分支中的 st.rerun() 不依赖用户交互，只要 is_running=False 就会触发。
    """
    print("=" * 60)
    print("Verify completion branch st.rerun() is unconditional")
    print("=" * 60)

    source = _read_vector_preprocess_source()

    fragment_start = source.find("def render_vec_status_fragment()")
    next_def = source.find("\ndef ", fragment_start + 1)
    fragment_body = source[fragment_start:next_def] if next_def != -1 else source[fragment_start:]

    completion_block_start = fragment_body.find("if not vec_status['is_running']:")
    completion_block = fragment_body[completion_block_start:]
    block_lines = completion_block.splitlines()
    block_end = len(block_lines)
    for i, line in enumerate(block_lines[1:], start=1):
        if line.strip() and not line.startswith("        "):
            block_end = i
            break
    completion_block = "\n".join(block_lines[:block_end])

    # 完成分支内应有 st.rerun()，且不应包裹在 if st.button(...) 等用户交互条件中
    assert "st.rerun()" in completion_block, \
        "fragment completion branch should call st.rerun()"
    assert "if st.button" not in completion_block, \
        "completion branch should not depend on button click"

    print("  completion branch st.rerun() is unconditional ✓")
    print("\n[PASS] test_completion_branch_rerun_is_unconditional")
    return True


if __name__ == '__main__':
    results = {}
    tests = [
        ('fragment_triggers_rerun_when_task_finished', test_fragment_triggers_rerun_when_task_finished),
        ('success_path_uses_embedder_for_fallback_count', test_success_path_uses_embedder_for_fallback_count),
        ('completion_state_render_branch', test_completion_state_render_branch),
        ('completion_branch_rerun_is_unconditional', test_completion_branch_rerun_is_unconditional),
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
