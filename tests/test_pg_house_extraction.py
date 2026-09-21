# -*- coding: utf-8 -*-
"""
验证 sql/extract_house_number.sql 中 extract_house_number 函数的正确性。

策略：
    1. 从 tests/test_address_tagging_rules.py 提取所有出现的地址字符串
    2. 调用项目原生 Python 规则引擎获取预期 house 值
    3. 调用 PG 函数获取实际 house 值
    4. 对比两者差异，输出准确率和不一致 case
"""
import os
import re
import sys
import psycopg2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from matching.address_tagging_rules import RuleBasedAddressTaggingEngine


SQL_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'sql', 'extract_house_number.sql'
)

TEST_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'tests', 'test_address_tagging_rules.py'
)


def load_sql_file():
    """读取 SQL 文件，移除注释行，返回可执行 SQL。"""
    with open(SQL_FILE, 'r', encoding='utf-8') as f:
        content = f.read()
    lines = []
    for line in content.splitlines():
        if line.lstrip().startswith('--'):
            continue
        lines.append(line)
    return '\n'.join(lines)


def extract_addresses():
    """从测试文件中提取所有出现的地址字符串（去重，保持顺序）。"""
    with open(TEST_FILE, 'r', encoding='utf-8') as f:
        content = f.read()

    # 匹配 addr = 'xxx' 或 cases = [('xxx', ...), ...]
    addrs = []

    # 匹配 addr = 'xxx'
    for m in re.finditer(r"addr\s*=\s*'([^']+)'", content):
        addrs.append(m.group(1))

    # 匹配 cases 列表中的 ('xxx', 'yyy')
    for m in re.finditer(r"\('([^']+)',\s*'([^']+)'\)", content):
        addrs.append(m.group(1))

    # 去重保持顺序
    seen = set()
    unique = []
    for a in addrs:
        if a not in seen:
            seen.add(a)
            unique.append(a)
    return unique


def main():
    # Python 规则引擎
    engine = RuleBasedAddressTaggingEngine()

    # 连接 PG
    conn = psycopg2.connect(
        host='localhost', port=5432,
        dbname='postgres', user='postgres', password='123456'
    )
    conn.autocommit = True
    cur = conn.cursor()

    # 创建 PG 函数
    cur.execute(load_sql_file())

    # 提取地址
    addresses = extract_addresses()
    print(f"提取到 {len(addresses)} 个地址用例\n")

    # 对比
    passed = 0
    failed = 0
    failed_cases = []

    for addr in addresses:
        # Python 规则引擎预期值
        py_result = engine.parse_single(addr)
        expected = py_result['house']

        # PG 函数实际值
        cur.execute("SELECT extract_house_number(%s)", (addr,))
        actual = cur.fetchone()[0] or ''

        if actual == expected:
            passed += 1
        else:
            failed += 1
            failed_cases.append((addr, expected, actual))

    total = passed + failed
    accuracy = passed / total * 100 if total > 0 else 0
    print(f"==== 测试结果 ====")
    print(f"总数: {total}, 通过: {passed}, 失败: {failed}")
    print(f"准确率: {accuracy:.2f}%\n")

    if failed_cases:
        print(f"==== 失败用例 ====")
        for addr, expected, actual in failed_cases:
            print(f"地址: {addr}")
            print(f"  期望(Python): '{expected}'")
            print(f"  实际(PG):     '{actual}'")
            print()

    cur.close()
    conn.close()


if __name__ == '__main__':
    main()
