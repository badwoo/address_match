"""
向量验证 SQL 修复测试
=====================

验证 _verify_inserted_vectors 中 SQL 参数数量匹配，
避免向量化过程中出现 "tuple index out of range" 错误。
"""

import sys
import os
import re

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _read_vector_store_source():
    """读取 vector_store.py 源码"""
    vs_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'database', 'vector_store.py'
    )
    with open(vs_path, 'r', encoding='utf-8') as f:
        return f.read()


def test_verify_inserted_vectors_sql_param_count():
    """
    Bug 修复验证：_verify_inserted_vectors 的 SQL 占位符数量
    必须与传入参数数量一致，防止 psycopg2 报 tuple index out of range。
    """
    print("=" * 60)
    print("Bug fix: _verify_inserted_vectors SQL param count match")
    print("=" * 60)

    source = _read_vector_store_source()

    func_start = source.find("def _verify_inserted_vectors(")
    assert func_start != -1, "_verify_inserted_vectors not found"

    next_def = source.find("\n    def ", func_start + 1)
    func_body = source[func_start:next_def] if next_def != -1 else source[func_start:]

    # 提取 SQL 字符串
    sql_match = re.search(
        r'sql\s*=\s*f"""(.*?)"""',
        func_body,
        re.DOTALL
    )
    assert sql_match, "SQL string not found in _verify_inserted_vectors"
    sql = sql_match.group(1)

    # 统计 SQL 中 %s 占位符数量
    placeholder_count = sql.count('%s')
    print(f"  SQL placeholders: {placeholder_count}")

    # 统计 execute 调用传入的参数数量
    execute_match = re.search(
        r'self\.db\.execute\(sql,\s*(\([^)]*\))\)',
        func_body
    )
    assert execute_match, "execute(sql, params) call not found"
    params_str = execute_match.group(1)
    print(f"  execute params: {params_str}")

    # 参数为元组 (source_id,)，计 1 个元素
    assert params_str.startswith('(') and params_str.endswith(')'), \
        "params should be a tuple"
    # 去掉括号后按逗号分割，过滤空字符串
    param_items = [p.strip() for p in params_str[1:-1].split(',') if p.strip()]
    param_count = len(param_items)
    print(f"  param count: {param_count}")

    assert placeholder_count == param_count, \
        f"SQL has {placeholder_count} placeholders but {param_count} params provided"

    print("  placeholder count matches param count ✓")
    print("\n[PASS] test_verify_inserted_vectors_sql_param_count")
    return True


def test_verify_inserted_vectors_uses_self_inner_product():
    """
    验证修复后的 SQL 使用 vector <#> vector 计算自身内积，
    不再依赖外部传入查询向量。
    """
    print("=" * 60)
    print("Verify _verify_inserted_vectors uses vector <#> vector")
    print("=" * 60)

    source = _read_vector_store_source()

    func_start = source.find("def _verify_inserted_vectors(")
    next_def = source.find("\n    def ", func_start + 1)
    func_body = source[func_start:next_def] if next_def != -1 else source[func_start:]

    sql_match = re.search(
        r'sql\s*=\s*f"""(.*?)"""',
        func_body,
        re.DOTALL
    )
    sql = sql_match.group(1)

    assert "vector <#> vector" in sql, \
        "SQL should use vector <#> vector for self inner product"
    assert "vector <-> %s" not in sql, \
        "SQL should not use vector <-> %s with external vector param"

    print("  vector <#> vector found ✓")
    print("  no external vector <-> %s placeholder ✓")
    print("\n[PASS] test_verify_inserted_vectors_uses_self_inner_product")
    return True


def test_verify_inserted_vectors_no_double_placeholder():
    """
    验证 SQL 中不再出现两个 %s 占位符但只传一个参数的情况。
    """
    print("=" * 60)
    print("Verify _verify_inserted_vectors has no double placeholder bug")
    print("=" * 60)

    source = _read_vector_store_source()

    func_start = source.find("def _verify_inserted_vectors(")
    next_def = source.find("\n    def ", func_start + 1)
    func_body = source[func_start:next_def] if next_def != -1 else source[func_start:]

    sql_match = re.search(
        r'sql\s*=\s*f"""(.*?)"""',
        func_body,
        re.DOTALL
    )
    sql = sql_match.group(1)

    assert sql.count('%s') <= 1, \
        f"SQL should have at most 1 placeholder, got {sql.count('%s')}"

    print(f"  SQL placeholder count: {sql.count('%s')} ✓")
    print("\n[PASS] test_verify_inserted_vectors_no_double_placeholder")
    return True


if __name__ == '__main__':
    results = {}
    tests = [
        ('verify_inserted_vectors_sql_param_count', test_verify_inserted_vectors_sql_param_count),
        ('verify_inserted_vectors_uses_self_inner_product', test_verify_inserted_vectors_uses_self_inner_product),
        ('verify_inserted_vectors_no_double_placeholder', test_verify_inserted_vectors_no_double_placeholder),
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
