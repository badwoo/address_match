# -*- coding: utf-8 -*-
"""
地址结构化解析完成状态原子性测试
================================

验证以下修复点：
1. 完成状态（is_running=False + completed=True）原子性设置，避免 fragment 读到中间状态
2. 文件模式 completion_results 保存结果列表供 UI 显示下载
3. 数据库模式 completion_results 为 None（结果已写入结果表）
4. completion_result_table 正确设置（数据库模式）
5. 失败状态原子性设置
6. 无结果状态原子性设置
7. parse_from_dataframe / parse_from_db_streaming 完成时不设置 is_running=False
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time
import threading
import pytest
import pandas as pd
from unittest.mock import MagicMock, patch

from matching.address_tagging import AddressTaggingParser, run_address_tagging_async


def _make_parser(mode='12'):
    """构造一个已预载 rule_engine 的 parser（跳过真实模型加载）"""
    parser = AddressTaggingParser(device='cpu', mode=mode)
    parser.rule_engine = MagicMock()
    return parser


def _mock_cursor(rows=None, fetchone_result=None):
    """构造一个 mock cursor"""
    cursor = MagicMock()
    if rows is not None:
        cursor.fetchall.return_value = rows
    if fetchone_result is not None:
        cursor.fetchone.return_value = fetchone_result
    return cursor


def _wait_thread(thread, timeout=10):
    """等待线程完成，超时则失败"""
    thread.join(timeout=timeout)
    assert not thread.is_alive(), f"线程在 {timeout}s 内未完成"


class TestCompletionStateAtomicity:
    """验证完成状态原子性设置（修复竞态条件）"""

    def test_file_mode_completion_results_saved(self):
        """文件模式完成时，completion_results 应保存结果列表"""
        parser = _make_parser('12')
        results = [
            {'original_address': '广东省深圳市南山区', 'province': '广东省'},
            {'original_address': '北京市朝阳区', 'province': '北京市'}
        ]
        parser.rule_engine.parse.return_value = results

        df = pd.DataFrame({'address': ['广东省深圳市南山区', '北京市朝阳区']})

        thread = run_address_tagging_async(
            parser=parser, data_source=df, address_col='address',
            db_conn=None, table_name=None, mode='12'
        )
        _wait_thread(thread)

        status = parser.get_status()
        assert status['completed'] is True
        assert status['completion_success'] is True
        assert status['is_running'] is False
        # 文件模式应保存结果列表
        assert status['completion_results'] is results
        # 文件模式无 db_conn，result_table 为空
        assert status['completion_result_table'] == ''
        assert status['completion_end_time'] is not None

    def test_db_mode_completion_results_none(self):
        """数据库模式完成时，completion_results 应为 None（结果已写入结果表）"""
        parser = _make_parser('12')
        parser.rule_engine.parse.return_value = [{'original_address': 'a', 'province': '广东省'}]

        count_cursor = _mock_cursor(fetchone_result={'count': 1})
        select_cursor = _mock_cursor(rows=[{'ctid': '(0,1)', 'address': 'a'}])
        db_conn = MagicMock()
        db_conn.execute.side_effect = [count_cursor, select_cursor]

        data_loader = MagicMock()
        data_loader.insert_address_tagging_results.return_value = 1
        data_loader.create_tagging_copy_table_from_result.return_value = 'copy_t'

        with patch('database.data_loader.DataLoader') as DataLoaderMock:
            DataLoaderMock.return_value = data_loader

            thread = run_address_tagging_async(
                parser=parser, data_source=None, address_col='address',
                db_conn=db_conn, table_name='source_t', result_table_name='result_t',
                mode='12'
            )
            _wait_thread(thread)

        status = parser.get_status()
        assert status['completed'] is True
        assert status['completion_success'] is True
        assert status['is_running'] is False
        # 数据库模式 completion_results 应为 None
        assert status['completion_results'] is None
        # 结果表名应正确设置
        assert status['completion_result_table'] == 'result_t'
        assert status['completion_source_table'] == 'source_t'
        assert status['completion_copy_table'] == 'copy_t'

    def test_no_intermediate_state_during_completion(self):
        """验证完成过程中不会出现 is_running=False, completed=False 的中间状态

        这是修复的核心：原实现中 _update_status(is_running=False) 和 completed=True
        在两个独立锁块中，fragment 可能在中间读到 is_running=False, completed=False，
        触发误 st.rerun() 导致完成页面不跳转。
        """
        parser = _make_parser('12')
        results = [{'original_address': 'a', 'province': '广东省'}]
        parser.rule_engine.parse.return_value = results

        df = pd.DataFrame({'address': ['a']})

        # 启动监控线程，高频采样 parser 状态
        intermediate_states = []
        stop_event = threading.Event()

        def monitor():
            while not stop_event.is_set():
                s = parser.get_status()
                intermediate_states.append((s['is_running'], s['completed']))
                time.sleep(0.0005)  # 0.5ms 采样间隔

        monitor_thread = threading.Thread(target=monitor)
        monitor_thread.start()

        # 确保 monitor 开始采样后再启动任务
        time.sleep(0.01)

        thread = run_address_tagging_async(
            parser=parser, data_source=df, address_col='address',
            db_conn=None, table_name=None, mode='12'
        )
        _wait_thread(thread)

        # 等待 monitor 采样到最终状态
        time.sleep(0.05)
        stop_event.set()
        monitor_thread.join(timeout=2)

        # 完成后检查：最终状态必须是 (False, True)
        assert intermediate_states[-1] == (False, True), \
            f"最终状态应为 (is_running=False, completed=True)，实际: {intermediate_states[-1]}"

        # 检查是否出现 (True, *) -> (False, False) 的跳变（说明存在中间状态）
        # 这就是竞态条件的特征：is_running 已被设置为 False，但 completed 还未被设置为 True
        for i in range(1, len(intermediate_states)):
            prev = intermediate_states[i - 1]
            curr = intermediate_states[i]
            # 如果从 (True, *) 跳到 (False, False)，说明存在中间状态
            if prev[0] is True and curr == (False, False):
                pytest.fail(
                    f"检测到竞态条件中间状态 (is_running=False, completed=False) "
                    f"at index {i}, prev={prev}, curr={curr}"
                )

    def test_failure_state_atomicity(self):
        """验证失败状态原子性：失败时 completed=True, completion_success=False"""
        parser = _make_parser('12')
        # 让 rule_engine.parse 抛异常
        parser.rule_engine.parse.side_effect = RuntimeError('测试异常')

        df = pd.DataFrame({'address': ['a']})

        thread = run_address_tagging_async(
            parser=parser, data_source=df, address_col='address',
            db_conn=None, table_name=None, mode='12'
        )
        _wait_thread(thread)

        status = parser.get_status()
        assert status['completed'] is True
        assert status['completion_success'] is False
        assert status['is_running'] is False
        assert '测试异常' in status['completion_message']
        assert status['completion_end_time'] is not None

    def test_no_results_state_atomicity(self):
        """验证无结果状态原子性：无结果时 completed=True, completion_success=False"""
        parser = _make_parser('12')
        parser.rule_engine.parse.return_value = []  # 空结果

        df = pd.DataFrame({'address': ['a']})

        thread = run_address_tagging_async(
            parser=parser, data_source=df, address_col='address',
            db_conn=None, table_name=None, mode='12'
        )
        _wait_thread(thread)

        status = parser.get_status()
        assert status['completed'] is True
        assert status['completion_success'] is False
        assert status['is_running'] is False
        assert status['completion_message'] == '没有可解析的数据'


class TestParseMethodsNotSetIsRunning:
    """验证 parse_from_dataframe / parse_from_db_streaming 完成时不设置 is_running=False

    这是修复竞态条件的关键：这两个方法返回后，task_func 才会设置 completed=True。
    如果方法内部设置了 is_running=False，fragment 会在中间读到 is_running=False, completed=False。
    """

    def test_parse_from_dataframe_not_set_is_running_false_on_success(self):
        """parse_from_dataframe 成功返回时，is_running 应仍为 True"""
        parser = _make_parser('12')
        results = [{'original_address': 'a', 'province': '广东省'}]
        parser.rule_engine.parse.return_value = results

        df = pd.DataFrame({'address': ['a']})

        # 手动设置 is_running=True（模拟 task_func 的行为）
        parser._update_status(is_running=True)

        parser.parse_from_dataframe(df, 'address')

        # 方法返回后，is_running 应仍为 True（由 task_func 统一设置 False）
        status = parser.get_status()
        assert status['is_running'] is True, \
            "parse_from_dataframe 完成时不应设置 is_running=False，应由 task_func 统一设置"
        assert status['progress'] == 1.0
        assert status['processed_count'] == 1

    def test_parse_from_db_streaming_not_set_is_running_false_on_success(self):
        """parse_from_db_streaming 成功返回时，is_running 应仍为 True"""
        parser = _make_parser('12')
        parser.rule_engine.parse.return_value = [{'original_address': 'a', 'province': '广东省'}]

        count_cursor = _mock_cursor(fetchone_result={'count': 1})
        select_cursor = _mock_cursor(rows=[{'ctid': '(0,1)', 'address': 'a'}])
        db_conn = MagicMock()
        db_conn.execute.side_effect = [count_cursor, select_cursor]

        data_loader = MagicMock()
        data_loader.insert_address_tagging_results.return_value = 1

        # 手动设置 is_running=True（模拟 task_func 的行为）
        parser._update_status(is_running=True)

        parser.parse_from_db_streaming(
            db_conn=db_conn, table_name='t', address_col='address',
            result_table_name='r', data_loader=data_loader, db_batch_size=10
        )

        # 方法返回后，is_running 应仍为 True（由 task_func 统一设置 False）
        status = parser.get_status()
        assert status['is_running'] is True, \
            "parse_from_db_streaming 完成时不应设置 is_running=False，应由 task_func 统一设置"
        assert status['progress'] == 1.0
        assert status['processed_count'] == 1


class TestCompletionResultTable:
    """验证 completion_result_table 正确设置"""

    def test_db_mode_sets_result_table(self):
        """数据库模式完成时，completion_result_table 应正确设置"""
        parser = _make_parser('12')
        parser.rule_engine.parse.return_value = [{'original_address': 'a', 'province': '广东省'}]

        count_cursor = _mock_cursor(fetchone_result={'count': 1})
        select_cursor = _mock_cursor(rows=[{'ctid': '(0,1)', 'address': 'a'}])
        db_conn = MagicMock()
        db_conn.execute.side_effect = [count_cursor, select_cursor]

        data_loader = MagicMock()
        data_loader.insert_address_tagging_results.return_value = 1
        data_loader.create_tagging_copy_table_from_result.return_value = 'copy_t'

        with patch('database.data_loader.DataLoader') as DataLoaderMock:
            DataLoaderMock.return_value = data_loader

            thread = run_address_tagging_async(
                parser=parser, data_source=None, address_col='address',
                db_conn=db_conn, table_name='source_t',
                result_table_name='result_t', mode='12'
            )
            _wait_thread(thread)

        status = parser.get_status()
        assert status['completed'] is True
        assert status['completion_result_table'] == 'result_t'
        assert status['completion_source_table'] == 'source_t'
        assert status['completion_copy_table'] == 'copy_t'


class TestGetStatusReturnsAllFields:
    """验证 get_status 返回所有完成状态字段"""

    def test_get_status_includes_completion_result_table(self):
        """get_status 应返回 completion_result_table 字段"""
        parser = _make_parser('12')
        status = parser.get_status()
        assert 'completion_result_table' in status
        assert status['completion_result_table'] == ''

    def test_get_status_includes_all_completion_fields(self):
        """get_status 应返回所有完成相关字段"""
        parser = _make_parser('12')
        status = parser.get_status()
        required_fields = [
            'is_running', 'completed', 'completion_success',
            'completion_message', 'completion_results', 'completion_end_time',
            'completion_copy_table', 'completion_source_table',
            'completion_result_table'
        ]
        for field in required_fields:
            assert field in status, f"get_status 缺少字段: {field}"
