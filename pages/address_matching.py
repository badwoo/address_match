"""
地址匹配页面
===========
两阶段匹配（粗召回 + MGeo精排），含标签管理。
"""

import streamlit as st
import time
import threading
import pandas as pd
from database.connection import DBConnection
from database.data_loader import DataLoader
from database.vector_store import VectorStore
from config import Config
from utils.logger import logger
from utils.pinyin_utils import tag_to_prefix, get_tag_tables
from database.tag_manager import TagManager
from ui_theme import Colors, card_style, status_container_style
from app_common import format_time, _render_device_selector
from pages.mgeo_similarity import show_mgeo_similarity_matching


def reset_matching_status():
    """重置匹配状态"""
    st.session_state.matching_status = {
        'is_running': False,
        'processed_count': 0,
        'total_count': 0,
        'current_stage': '',
        'progress': 0.0,
        'speed': 0.0,
        'remaining_time': 0.0,
        'status_message': '',
        'error_message': '',
        'start_time': None,
        'recall_completed': False,
        'ranking_completed': False,
        'ranking_ui_shown': False,
        'recall_count': 0,
        'match_count': 0
    }
    st.session_state.recall_status = {
        'completed': False,
        'start_time': None,
        'end_time': None,
        'recall_count': 0,
        'candidate_count': 0
    }


def _render_elapsed_time(start_time: float):
    """
    渲染已运行时间。

    Streamlit 的 st.html 不支持 JS 执行（DOMPurify 会剥离 script 标签），
    st.components.v1.html 在 fragment 内有 key 注入冲突。
    因此直接使用 Python 计算已运行时间，fragment 每 3 秒刷新时自动更新。
    """
    elapsed = max(0, time.time() - start_time)
    st.write(f"**已运行时间**: {format_time(elapsed)}")


POLL_INTERVAL = 3  # 秒

@st.fragment(run_every=POLL_INTERVAL)
def render_matching_status_fragment():
    """
    匹配状态实时展示 fragment。
    每 3 秒自刷新一次，只刷新状态卡片区域，不影响页面其他部分。
    """
    matching_status = st.session_state.matching_status

    # 1. 同步后台线程状态（保持现有逻辑）
    if matching_status.get('current_stage') == 'MGeo精确匹配' \
       and 'running_ranking_status' in st.session_state \
       and st.session_state.running_ranking_status:
        try:
            ranking_stat = st.session_state.running_ranking_status.get_status()
            matching_status.update({
                'is_running': ranking_stat['is_running'],
                'processed_count': ranking_stat['processed_count'],
                'total_count': ranking_stat['total_count'],
                'current_stage': ranking_stat['current_stage'],
                'progress': ranking_stat['progress'],
                'speed': ranking_stat['speed'],
                'remaining_time': ranking_stat['remaining_time'],
                'status_message': ranking_stat['status_message'],
                'error_message': ranking_stat['error_message'],
                'ranking_completed': ranking_stat['ranking_completed'],
                'match_count': ranking_stat['match_count'],
            })
            matching_status = st.session_state.matching_status
        except Exception as e:
            logger.error(f"获取精排状态失败: {e}")
    elif 'matcher' in st.session_state and st.session_state.matcher:
        try:
            matcher_status = st.session_state.matcher.get_status()
            matching_status.update({
                'is_running': matcher_status['is_running'],
                'processed_count': matcher_status['processed_count'],
                'total_count': matcher_status['total_count'],
                'current_stage': matcher_status['current_stage'],
                'progress': matcher_status['progress'],
                'speed': matcher_status['speed'],
                'remaining_time': matcher_status['remaining_time'],
                'status_message': matcher_status['status_message'],
                'error_message': matcher_status['error_message'],
            })
            matching_status = st.session_state.matching_status
        except Exception as e:
            logger.error(f"获取匹配器状态失败: {e}")

    # 2. 渲染状态卡片
    _render_status_card(matching_status)

    # 3. 检测完成：切到完整页面刷新以显示完成 UI
    if not matching_status['is_running']:
        st.rerun()


def _render_status_card(matching_status):
    """
    渲染匹配执行状态卡片。
    与原来视觉一致，但已运行时间由前端 JS 秒表渲染。
    """
    st.markdown("<div class='status-card status-card-warning'>", unsafe_allow_html=True)
    st.subheader("匹配执行状态")

    if matching_status['start_time']:
        start_time_str = time.strftime(
            '%Y-%m-%d %H:%M:%S',
            time.localtime(matching_status['start_time'])
        )
        st.write(f"**开始时间**: {start_time_str}")
        _render_elapsed_time(matching_status['start_time'])

    st.write(f"**当前阶段**: {matching_status['current_stage']}")

    is_recall_stage = matching_status['current_stage'] == '数据粗召回'

    if is_recall_stage:
        st.progress(0)
        st.info("🔄 正在执行批量召回，请稍候...")
    else:
        st.progress(matching_status['progress'])
        st.write(
            f"**处理进度**: {matching_status['processed_count']:,}/"
            f"{matching_status['total_count']:,} "
            f"({matching_status['progress'] * 100:.1f}%)"
        )
        st.write(f"**处理速度**: {matching_status['speed']:.2f} 条/秒")
        st.write(f"**预计剩余时间**: {format_time(matching_status['remaining_time'])}")

    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button("⏹️ 取消匹配"):
            if 'matcher' in st.session_state and st.session_state.matcher:
                try:
                    st.session_state.matcher.stop()
                except Exception:
                    pass

            if 'running_ranking_status' in st.session_state and st.session_state.running_ranking_status:
                try:
                    st.session_state.running_ranking_status.is_running = False
                except Exception:
                    pass

            st.session_state.matching_status.update({
                'is_running': False,
                'processed_count': 0,
                'total_count': 0,
                'current_stage': '',
                'progress': 0.0,
                'speed': 0.0,
                'remaining_time': 0.0,
                'status_message': '',
                'error_message': '',
                'start_time': None,
                'recall_completed': False,
                'ranking_completed': False,
                'ranking_ui_shown': False,
                'recall_count': 0,
                'match_count': 0,
            })
            st.session_state.recall_status.update({
                'completed': False,
                'start_time': None,
                'end_time': None,
                'recall_count': 0,
                'candidate_count': 0,
            })
            if 'running_ranking_status' in st.session_state:
                del st.session_state.running_ranking_status
            st.success("匹配已取消")
            st.rerun()

    with col2:
        st.info("🔄 匹配进行中...")

    st.markdown("</div>", unsafe_allow_html=True)


def start_recall_matching(db_config, device, enterprise_vector_table, standard_vector_table):
    """启动粗召回匹配"""
    # 防止重复启动
    if st.session_state.matching_status.get('is_running'):
        st.warning("匹配任务已在运行中，请等待完成")
        return
    if st.session_state.get('ranking_thread') and st.session_state.ranking_thread.is_alive():
        st.warning("精排任务正在运行中，请等待完成")
        return

    try:
        from matching.matcher import AddressMatcher

        db_conn = DBConnection(
            host=db_config['host'],
            port=db_config['port'],
            schema=db_config['schema'],
            dbname=db_config['dbname'],
            user=db_config['user'],
            password=db_config['password']
        )

        if not db_conn.connect():
            st.error("无法连接数据库")
            return

        matcher = AddressMatcher(db_conn, device=device, mode='recall_only')
        matcher.set_threshold(st.session_state.matching_config['similarity_threshold'])
        st.session_state.matcher = matcher

        # 设置开始时间
        start_time = time.time()

        # 更新状态（在主线程中）
        st.session_state.matching_status.update({
            'is_running': True,
            'processed_count': 0,
            'total_count': 0,
            'current_stage': '数据粗召回',
            'progress': 0.0,
            'speed': 0.0,
            'remaining_time': 0.0,
            'status_message': '',
            'error_message': '',
            'start_time': start_time,
            'recall_completed': False,
            'ranking_completed': False,
            'ranking_ui_shown': False
        })

        st.session_state.recall_status.update({
            'completed': False,
            'start_time': start_time,
            'end_time': None,
            'recall_count': 0,
            'candidate_count': 0
        })

        # 注：不在后台线程中通过 callback 访问 st.session_state，
        # 因为后台线程没有 ScriptRunContext，无法读写 st.session_state。
        # 改为依赖 matcher 对象的 is_running 标志（finally 块中自动置 False）
        # + fragment 每 3 秒轮询 matcher.get_status()
        # + show_address_matching 中的 DB 兜底检测
        pass

        # 启动后台任务，使用回调函数通知完成状态
        matcher.start_recall_async(
            enterprise_table=enterprise_vector_table,
            standard_table=standard_vector_table,
            top_n=st.session_state.matching_config['recall_top_n'],
            progress_callback=None,
            completed_callback=None,
            recall_table=st.session_state.current_recall_table
        )

        st.success("粗召回匹配任务已启动！")
        st.rerun()

    except Exception as e:
        st.error(f"启动失败: {str(e)}")
        import traceback
        st.write(f"详细错误: {traceback.format_exc()}")
        logger.error(f"Recall matching failed: {str(e)}")


def start_mgeo_ranking(db_config, device):
    """启动MGeo精确匹配"""
    # 防止重复启动
    if st.session_state.matching_status.get('is_running'):
        st.warning("匹配任务已在运行中，请等待完成")
        return
    if st.session_state.get('ranking_thread') and st.session_state.ranking_thread.is_alive():
        st.warning("精排任务已在运行中，请等待完成")
        return

    try:
        start_time = time.time()
        threshold = st.session_state.matching_config['similarity_threshold']
        # 获取标签对应的表名
        recall_table = st.session_state.current_recall_table
        match_table = st.session_state.current_match_table

        logger.info("[start_mgeo_ranking] 开始启动MGeo精排...")
        logger.info(f"[start_mgeo_ranking] 相似度阈值: {threshold}")

        # 创建线程安全的状态共享对象（类似matcher.py的方式）
        class RankingStatus:
            def __init__(self):
                self.lock = threading.Lock()
                self.is_running = True
                self.processed_count = 0
                self.total_count = 0
                self.current_stage = 'MGeo精确匹配'
                self.progress = 0.0
                self.speed = 0.0
                self.remaining_time = 0.0
                self.status_message = '正在加载MGeo模型...'
                self.error_message = ''
                self.ranking_completed = False
                self.match_count = 0

            def update(self, **kwargs):
                with self.lock:
                    for key, value in kwargs.items():
                        if hasattr(self, key):
                            setattr(self, key, value)

            def get_status(self):
                with self.lock:
                    return {
                        'is_running': self.is_running,
                        'processed_count': self.processed_count,
                        'total_count': self.total_count,
                        'current_stage': self.current_stage,
                        'progress': self.progress,
                        'speed': self.speed,
                        'remaining_time': self.remaining_time,
                        'status_message': self.status_message,
                        'error_message': self.error_message,
                        'ranking_completed': self.ranking_completed,
                        'match_count': self.match_count
                    }

        # 清除可能影响状态判断的残留标志
        if 'post_recall_refresh_count' in st.session_state:
            del st.session_state['post_recall_refresh_count']

        # 清除粗召回阶段的matcher对象，避免状态读取冲突
        if 'matcher' in st.session_state:
            del st.session_state['matcher']

        # 创建状态对象并保存到session_state
        ranking_status = RankingStatus()
        ranking_status.total_count = st.session_state.recall_status['recall_count']
        st.session_state.running_ranking_status = ranking_status

        logger.info(f"[start_mgeo_ranking] 召回企业数: {st.session_state.recall_status['recall_count']}")

        # 更新状态（在主线程中），先标记为运行中
        st.session_state.matching_status = {
            'is_running': True,
            'processed_count': 0,
            'total_count': st.session_state.recall_status['recall_count'],
            'current_stage': 'MGeo精确匹配',
            'progress': 0.0,
            'speed': 0.0,
            'remaining_time': 0.0,
            'status_message': '正在加载MGeo模型...',
            'error_message': '',
            'start_time': start_time,
            'recall_completed': True,
            'ranking_completed': False,
            'ranking_ui_shown': False,
            'recall_count': st.session_state.recall_status['recall_count'],
            'match_count': 0
        }

        # 启动后台线程执行MGeo精排（模型加载和数据库操作都在后台线程中完成）
        def ranking_thread_func(inner_db_config, inner_device, inner_threshold, inner_ranking_status, inner_start_time,
                                inner_recall_table, inner_match_table):
            """MGeo精排后台线程"""
            db_conn = None
            try:
                logger.info("[ranking_thread_func] 后台线程开始执行")

                # 在后台线程中创建独立的数据库连接
                db_conn = DBConnection(
                    host=inner_db_config['host'],
                    port=inner_db_config['port'],
                    schema=inner_db_config['schema'],
                    dbname=inner_db_config['dbname'],
                    user=inner_db_config['user'],
                    password=inner_db_config['password']
                )
                if not db_conn.connect():
                    logger.error("[ranking_thread_func] 无法连接数据库")
                    inner_ranking_status.update(
                        is_running=False,
                        error_message='无法连接数据库'
                    )
                    return

                data_loader = DataLoader(db_conn)

                # 确保结果表存在
                data_loader.create_result_table(inner_match_table)
                data_loader.truncate_result_table(inner_match_table)
                logger.info(f"[ranking_thread_func] 已清空 {inner_match_table}")

                # 从recall_results表加载召回结果
                logger.info(f"[MGeo精排] 加载召回结果 {inner_recall_table}...")
                recall_results = data_loader.load_recall_results(inner_recall_table)
                total = len(recall_results)
                inner_ranking_status.total_count = total

                if total == 0:
                    logger.warning("[MGeo精排] 没有召回结果")
                    inner_ranking_status.update(
                        is_running=False,
                        current_stage='MGeo精确匹配完成',
                        status_message='没有召回结果可匹配'
                    )
                    return

                logger.info(f"[MGeo精排] 共 {total} 家企业需要精排")

                logger.info("[MGeo精排] 加载MGeo模型...")
                from model.mgeo_model import MGeoModel
                mgeo_model = MGeoModel(device=inner_device)
                logger.info(f"[MGeo精排] 模型加载完成")

                inner_ranking_status.update(
                    status_message='正在执行MGeo精排...'
                )

                final_results = []
                processed_count = 0

                # 遍历每个企业的召回结果
                for recall_idx, recall_item in enumerate(recall_results):
                    # 检查是否被停止
                    if not inner_ranking_status.is_running:
                        logger.info("[MGeo精排] 用户停止了匹配")
                        break

                    enterprise_id = recall_item['enterprise_id']
                    enterprise_name = recall_item.get('enterprise_name', '')
                    enterprise_addr = recall_item['enterprise_address']
                    candidates = recall_item['candidates']

                    if not candidates:
                        final_results.append({
                            'enterprise_id': enterprise_id,
                            'enterprise_name': enterprise_name,
                            'enterprise_address': enterprise_addr,
                            'address_id': None,
                            'standard_address': None,
                            'room_no': '',
                            'exact_match': 0.0,
                            'partial_match': 0.0,
                            'not_match': 1.0,
                            'match_status': '不匹配'
                        })
                        processed_count += 1
                        continue

                    pairs = [(enterprise_addr, candidate['address']) for candidate in candidates]

                    try:
                        predictions = mgeo_model.predict(pairs)
                    except Exception as e:
                        logger.error(f"[MGeo精排] 预测失败 enterprise={enterprise_id}: {str(e)}")
                        final_results.append({
                            'enterprise_id': enterprise_id,
                            'enterprise_name': enterprise_name,
                            'enterprise_address': enterprise_addr,
                            'address_id': None,
                            'standard_address': None,
                            'room_no': '',
                            'exact_match': 0.0,
                            'partial_match': 0.0,
                            'not_match': 1.0,
                            'match_status': '不匹配'
                        })
                        processed_count += 1
                        continue

                    # 按相似度阈值过滤低分候选
                    filtered_pairs = []
                    for i, candidate in enumerate(candidates):
                        sim = candidate.get('similarity', 1.0)
                        if inner_threshold is not None and inner_threshold > 0 and sim < inner_threshold:
                            continue
                        filtered_pairs.append((i, candidate, predictions[i]))

                    if not filtered_pairs:
                        final_results.append({
                            'enterprise_id': enterprise_id,
                            'enterprise_name': enterprise_name,
                            'enterprise_address': enterprise_addr,
                            'address_id': None,
                            'standard_address': None,
                            'room_no': '',
                            'exact_match': 0.0,
                            'partial_match': 0.0,
                            'not_match': 1.0,
                            'match_status': '不匹配'
                        })
                        processed_count += 1
                        continue

                    best_score = -1.0
                    best_not_match = float('inf')
                    best_candidate = None
                    best_pred = None

                    for i, candidate, pred in filtered_pairs:
                        score = pred['exact_match']
                        not_match = pred['not_match']
                        if score > best_score or (score == best_score and not_match < best_not_match):
                            best_score = score
                            best_not_match = not_match
                            best_candidate = candidates[i]
                            best_pred = pred

                    if best_candidate and best_pred:
                        scores = {
                            '精确匹配': best_pred['exact_match'],
                            '部分匹配': best_pred['partial_match'],
                            '不匹配': best_pred['not_match']
                        }
                        match_status = max(scores, key=scores.get)
                        result_item = {
                            'enterprise_id': enterprise_id,
                            'enterprise_name': enterprise_name,
                            'enterprise_address': enterprise_addr,
                            'address_id': best_candidate['source_id'],
                            'standard_address': best_candidate['address'],
                            'room_no': best_candidate.get('room_no', ''),
                            'exact_match': best_pred['exact_match'],
                            'partial_match': best_pred['partial_match'],
                            'not_match': best_pred['not_match'],
                            'match_status': match_status
                        }
                        final_results.append(result_item)
                    else:
                        result_item = {
                            'enterprise_id': enterprise_id,
                            'enterprise_name': enterprise_name,
                            'enterprise_address': enterprise_addr,
                            'address_id': None,
                            'standard_address': None,
                            'room_no': '',
                            'exact_match': 0.0,
                            'partial_match': 0.0,
                            'not_match': 1.0,
                            'match_status': '不匹配'
                        }
                        final_results.append(result_item)

                    processed_count += 1

                    elapsed_time = time.time() - inner_start_time
                    speed = processed_count / elapsed_time if elapsed_time > 0 else 0
                    progress = processed_count / total
                    remaining_time = (total - processed_count) / speed if speed > 0 else 0

                    inner_ranking_status.update(
                        processed_count=processed_count,
                        progress=progress,
                        speed=speed,
                        remaining_time=remaining_time
                    )

                    if len(final_results) >= 100:
                        inserted = data_loader.insert_match_results(final_results, inner_match_table)
                        final_results = []

                if final_results:
                    inserted = data_loader.insert_match_results(final_results, inner_match_table)

                total_time = time.time() - inner_start_time
                logger.info(f"[MGeo精排] 完成！总耗时: {total_time:.2f}s, 处理企业数: {processed_count}")

                # 标记完成
                inner_ranking_status.update(
                    is_running=False,
                    ranking_completed=True,
                    current_stage='MGeo精确匹配完成',
                    status_message='MGeo精确匹配完成',
                    progress=1.0,
                    processed_count=processed_count,
                    match_count=processed_count
                )

            except Exception as e:
                logger.error(f"[MGeo精排] 失败: {str(e)}")
                import traceback
                logger.error(f"[MGeo精排] 详细堆栈: {traceback.format_exc()}")
                inner_ranking_status.update(
                    is_running=False,
                    error_message=str(e),
                    current_stage='MGeo精确匹配失败'
                )
            finally:
                if db_conn:
                    try:
                        db_conn.close()
                    except:
                        pass

        # 启动后台线程
        ranking_thread = threading.Thread(target=ranking_thread_func, args=(db_config, device, threshold, ranking_status, start_time, recall_table, match_table), daemon=True)
        ranking_thread.start()
        st.session_state.ranking_thread = ranking_thread

        st.success("MGeo精确匹配任务已启动！")
        st.rerun()

    except Exception as e:
        st.error(f"启动失败: {str(e)}")
        import traceback
        st.write(f"详细错误: {traceback.format_exc()}")
        logger.error(f"Ranking failed: {str(e)}")


def show_address_matching():
    db_config = st.session_state.db_config

    device = _render_device_selector(key='match_device_selector')

    # ========== 标签管理 ==========
    st.markdown(f"<div style='{card_style(bg_color=Colors.INFO_BG, border_color=Colors.INFO_BORDER)}'>", unsafe_allow_html=True)
    st.subheader("🏷 标签管理")

    if not st.session_state.connected:
        st.warning("请先在【数据库配置】页面连接数据库")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    tag_db_conn = DBConnection(
        host=db_config['host'], port=db_config['port'],
        schema=db_config['schema'], dbname=db_config['dbname'],
        user=db_config['user'], password=db_config['password']
    )
    if not tag_db_conn.connect():
        st.error("无法连接数据库")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    tag_mgr = TagManager(tag_db_conn)
    all_tags = tag_mgr.get_all_tags()

    # 当前选中标签信息
    if st.session_state.current_tag:
        st.markdown(f"""<div style='{card_style(bg_color=Colors.SURFACE_SECONDARY)}'>
            <b>当前标签</b>: {st.session_state.current_tag} |
            <b>召回表</b>: {st.session_state.current_recall_table} |
            <b>匹配表</b>: {st.session_state.current_match_table}
        </div>""", unsafe_allow_html=True)

    # 标签选择 + 新建按钮（对齐排列）
    tag_col1, tag_col2 = st.columns([4, 1])
    with tag_col1:
        if all_tags:
            current_prefix = st.session_state.get('current_tag_prefix', '')
            default_idx = 0
            for i, t in enumerate(all_tags):
                if t['prefix'] == current_prefix:
                    default_idx = i
                    break
            tag_names = [t['tag_name'] for t in all_tags]
            selected_tag_name = st.selectbox(
                "选择已有标签",
                tag_names,
                index=min(default_idx, len(tag_names) - 1),
                key='tag_selector'
            )
            if selected_tag_name and selected_tag_name != st.session_state.get('current_tag', ''):
                for t in all_tags:
                    if t['tag_name'] == selected_tag_name:
                        st.session_state.current_tag = t['tag_name']
                        st.session_state.current_tag_prefix = t['prefix']
                        st.session_state.current_recall_table = t['recall_table']
                        st.session_state.current_match_table = t['match_table']
                        st.rerun()
                        break
        else:
            st.info("暂无标签，请新建")

    with tag_col2:
        st.markdown("<div style='margin-top: 24px;'></div>", unsafe_allow_html=True)
        if st.button("新建标签", use_container_width=True, key='new_tag_btn',
                     help="创建一个新的匹配标签"):
            st.session_state.show_new_tag_input = True

    # 新建标签区域（输入框与按钮对齐）
    if st.session_state.get('show_new_tag_input', False):
        st.markdown(f"<div style='{card_style(bg_color=Colors.SURFACE_SECONDARY)} margin-top: 10px;'>", unsafe_allow_html=True)
        st.caption("创建新标签")
        new_col1, new_col2, new_col3 = st.columns([3, 1, 1])
        with new_col1:
            new_tag_name = st.text_input("标签名称", key='new_tag_input',
                                         placeholder="例如：福田 / 龙华 / batch1",
                                         label_visibility="collapsed")
        with new_col2:
            if st.button("确认创建", use_container_width=True, key='confirm_new_tag', type="primary"):
                if new_tag_name and new_tag_name.strip():
                    result = tag_mgr.create_tag(new_tag_name.strip())
                    if result:
                        st.session_state.current_tag = result['tag_name']
                        st.session_state.current_tag_prefix = result['prefix']
                        st.session_state.current_recall_table = result['recall_table']
                        st.session_state.current_match_table = result['match_table']
                        st.session_state.show_new_tag_input = False
                        st.success(f"标签已创建: {result['tag_name']}")
                    else:
                        st.error("创建失败，可能已存在同名标签")
                    st.rerun()
                else:
                    st.warning("请输入标签名称")
        with new_col3:
            if st.button("取消", use_container_width=True, key='cancel_new_tag'):
                st.session_state.show_new_tag_input = False
                st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)

    # 删除标签
    if all_tags:
        with st.expander("🗑 删除标签（含关联数据表）"):
            st.caption("删除标签将同时删除对应的召回结果表和匹配结果表")
            del_options = [t['tag_name'] for t in all_tags]
            del_col1, del_col2 = st.columns([2, 1])
            with del_col1:
                del_tag_name = st.selectbox("选择标签", del_options, key='del_tag_selector',
                                           label_visibility="collapsed")
            with del_col2:
                if st.button("删除标签", use_container_width=True, key='delete_tag_btn', type="secondary"):
                    del_prefix = None
                    for t in all_tags:
                        if t['tag_name'] == del_tag_name:
                            del_prefix = t['prefix']
                            break
                    if del_prefix:
                        try:
                            tag_mgr.delete_tag(del_prefix)
                            if st.session_state.current_tag_prefix == del_prefix:
                                st.session_state.current_tag = ''
                                st.session_state.current_tag_prefix = ''
                                st.session_state.current_recall_table = Config.RECALL_RESULTS_TABLE
                                st.session_state.current_match_table = Config.MATCH_RESULTS_TABLE
                            st.success(f"标签 '{del_tag_name}' 已删除")
                            st.rerun()
                        except Exception as e:
                            st.error(f"删除失败: {e}")

    tag_db_conn.close()
    st.markdown("</div>", unsafe_allow_html=True)

    # 未设置标签时不允许匹配
    if not st.session_state.current_tag:
        st.warning("请先选择或创建一个标签，再进行地址匹配")
        return

    # 使用标签对应的表名
    _recall_table = st.session_state.current_recall_table
    _match_table = st.session_state.current_match_table

    # 确保 matching_status 已初始化
    if 'matching_status' not in st.session_state:
        st.session_state.matching_status = {
            'is_running': False,
            'processed_count': 0,
            'total_count': 0,
            'current_stage': '',
            'progress': 0.0,
            'speed': 0.0,
            'remaining_time': 0.0,
            'status_message': '',
            'error_message': '',
            'start_time': None,
            'recall_completed': False,
            'ranking_completed': False,
            'ranking_ui_shown': False,
            'recall_count': 0,
            'match_count': 0
        }

    # 确保 recall_status 已初始化
    if 'recall_status' not in st.session_state:
        st.session_state.recall_status = {
            'completed': False,
            'start_time': None,
            'end_time': None,
            'recall_count': 0,
            'candidate_count': 0
        }

    matching_status = st.session_state.matching_status
    recall_status = st.session_state.recall_status

    # ========== 回调触发刷新机制 ==========
    trigger = st.session_state.get('recall_finished_trigger')
    if trigger:
        logger.info("[刷新] 检测到粗召回完成触发器，应用后台线程状态并刷新页面")
        if isinstance(trigger, dict):
            st.session_state.matching_status.update(trigger.get('matching_status', {}))
            st.session_state.recall_status.update(trigger.get('recall_status', {}))
        del st.session_state['recall_finished_trigger']
        st.rerun()

    # ========== 优先检测任务完成状态 ==========
    if not matching_status['is_running'] and not matching_status.get('recall_completed'):
        need_rerun = False

        is_mgeo_stage = matching_status.get('current_stage') == 'MGeo精确匹配' or matching_status.get('ranking_completed')

        if (not is_mgeo_stage
            and matching_status.get('current_stage') in ['数据粗召回', '数据粗召回完成']
            and not matching_status.get('recall_completed')):
            logger.info("[完成检测] 检测粗召回完成状态，查询数据库验证")

            try:
                db_config = st.session_state.db_config
                check_conn = DBConnection(
                    host=db_config['host'],
                    port=db_config['port'],
                    schema=db_config['schema'],
                    dbname=db_config['dbname'],
                    user=db_config['user'],
                    password=db_config['password']
                )
                if check_conn.connect():
                    recall_table = _recall_table
                    enterprise_cursor = check_conn.execute(f"SELECT COUNT(DISTINCT enterprise_id) FROM {recall_table}")
                    enterprise_count = enterprise_cursor.fetchone()['count'] if enterprise_cursor else 0

                    cursor = check_conn.execute(f"SELECT COUNT(*) FROM {recall_table}")
                    recall_count = cursor.fetchone()['count'] if cursor else 0

                    candidate_cursor = check_conn.execute(f"SELECT COUNT(*) FROM {recall_table} WHERE standard_id IS NOT NULL")
                    candidate_count = candidate_cursor.fetchone()['count'] if candidate_cursor else 0

                    check_conn.close()

                    logger.info(f"[完成检测] recall_results表记录数: {recall_count}, 企业数: {enterprise_count}, 候选地址数: {candidate_count}")

                    if recall_count > 0:
                        st.session_state.matching_status = {
                            'is_running': False,
                            'processed_count': enterprise_count,
                            'current_stage': '数据粗召回完成',
                            'progress': 1.0,
                            'speed': 0.0,
                            'remaining_time': 0.0,
                            'status_message': '粗召回完成',
                            'error_message': '',
                            'start_time': st.session_state.matching_status.get('start_time'),
                            'recall_completed': True,
                            'ranking_completed': False,
                            'ranking_ui_shown': False,
                            'recall_count': enterprise_count,
                            'match_count': 0
                        }
                        st.session_state.recall_status = {
                            'completed': True,
                            'end_time': time.time(),
                            'recall_count': enterprise_count,
                            'candidate_count': candidate_count,
                            'start_time': st.session_state.matching_status.get('start_time')
                        }
                        need_rerun = True
                        logger.info("[完成检测] 粗召回完成状态已更新")
                    else:
                        logger.warning("[完成检测] recall_results表为空，等待后台线程写入...")
            except Exception as e:
                logger.error(f"[完成检测] 查询recall_results统计失败: {str(e)}")
                st.session_state.matching_status.update({
                    'recall_completed': True,
                    'is_running': False
                })
                st.session_state.recall_status.update({
                    'completed': True,
                    'end_time': time.time()
                })
                need_rerun = True

        if need_rerun:
            logger.info("[完成检测] 状态已更新，刷新页面...")
            st.rerun()

    # MGeo精排完成检测
    if not matching_status['is_running'] and matching_status.get('ranking_completed') and not matching_status.get('ranking_ui_shown'):
        logger.info("[完成检测] MGeo精确匹配已完成，更新UI状态")
        st.session_state.matching_status['ranking_ui_shown'] = True
        st.rerun()

    # 显示匹配执行状态（使用 fragment 局部刷新，不再每 1 秒整页刷新）
    if matching_status['is_running']:
        render_matching_status_fragment()

        # 匹配进行中时，配置区仍显示但不可编辑
        st.subheader("地址匹配配置")
        with st.expander("参数配置（匹配进行中不可修改）", expanded=False):
            st.info("匹配正在进行中，参数配置暂时不可修改")

        return

    # 粗召回完成后
    if recall_status['completed'] and not matching_status['ranking_completed'] and not matching_status['is_running'] and matching_status.get('current_stage') != 'MGeo精确匹配':
        st.markdown(f"<div class='status-card status-card-success'>", unsafe_allow_html=True)
        st.subheader("数据粗召回匹配完成")

        if recall_status['start_time'] and recall_status['end_time']:
            duration = recall_status['end_time'] - recall_status['start_time']
            st.write(f"**开始时间**: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(recall_status['start_time']))}")
            st.write(f"**结束时间**: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(recall_status['end_time']))}")
            st.write(f"**耗时**: {format_time(duration)}")

        st.write(f"**召回企业数**: {recall_status['recall_count']:,}")
        st.write(f"**候选地址总数**: {recall_status['candidate_count']:,}")

        st.markdown("---")
        st.markdown("**下一步操作**")

        col1, col2, col3 = st.columns(3)
        with col1:
            if st.button("📊 数据查看", help="查看召回结果数据"):
                st.session_state.selected_menu = "结果管理"
                st.session_state.result_management_active_tab = "粗召回数据"
                st.rerun()

        with col2:
            if st.button("▶️ 继续MGeo精确匹配", key='continue_mgeo', help="执行MGeo精确匹配，按企业分组比较企业地址和标准地址，找出最相似的数据"):
                start_mgeo_ranking(db_config, device)

        with col3:
            if st.button("↩️ 返回地址匹配", help="返回地址匹配页面"):
                reset_matching_status()
                st.rerun()

        st.markdown("</div>", unsafe_allow_html=True)

        if st.button("🔄 重新进行粗召回匹配"):
            try:
                db_conn = DBConnection(
                    host=db_config['host'],
                    port=db_config['port'],
                    schema=db_config['schema'],
                    dbname=db_config['dbname'],
                    user=db_config['user'],
                    password=db_config['password']
                )
                if db_conn.connect():
                    data_loader = DataLoader(db_conn)
                    data_loader.truncate_recall_table(_recall_table)
                    db_conn.close()
                    st.info("已清空召回结果表")
            except Exception as e:
                logger.error(f"清空召回表失败: {e}")

            st.session_state.recall_status = {
                'completed': False,
                'start_time': None,
                'end_time': None,
                'recall_count': 0,
                'candidate_count': 0
            }
            st.session_state.matching_status['recall_completed'] = False
            st.rerun()

        return

    # 精排完成后
    if matching_status['ranking_completed']:
        st.markdown(f"<div class='status-card status-card-info'>", unsafe_allow_html=True)
        st.subheader("MGeo精确匹配完成")
        st.write(f"**匹配结果数**: {matching_status['match_count']:,}")

        col1, col2, col3 = st.columns(3)
        with col1:
            if st.button("📊 查看匹配结果"):
                st.session_state.selected_menu = "结果管理"
                st.session_state.result_management_active_tab = "精排匹配结果"
                st.rerun()

        with col2:
            if st.button("🔄 重新开始完整匹配"):
                reset_matching_status()
                st.rerun()

        with col3:
            if st.button("↩️ 返回地址匹配"):
                reset_matching_status()
                st.rerun()

        st.markdown("</div>", unsafe_allow_html=True)
        return

    # 地址匹配功能页签
    match_tab1, match_tab2 = st.tabs(["📊 数据粗召回 & MGeo精确匹配", "🔄 MGeo地址相似度匹配"])

    with match_tab1:
        # 上部分：数据粗召回匹配
        st.markdown(f"<div class='status-card status-card-success'>", unsafe_allow_html=True)
        st.subheader("数据粗召回匹配")

        if not st.session_state.connected:
            st.warning("⚠️ 数据粗召回匹配需要数据库连接，请先在【数据库配置】页面配置并连接数据库")
            st.markdown("</div>", unsafe_allow_html=True)
        else:
            db_conn = DBConnection(
                host=db_config['host'],
                port=db_config['port'],
                schema=db_config['schema'],
                dbname=db_config['dbname'],
                user=db_config['user'],
                password=db_config['password']
            )

            if not db_conn.connect():
                st.error("无法连接数据库，请检查配置")
                st.markdown("</div>", unsafe_allow_html=True)
            else:
                vector_store = VectorStore(db_conn)
                vector_tables = vector_store.get_vector_tables()

                with st.expander("向量表选择", expanded=True):
                    col1, col2 = st.columns(2)
                    with col1:
                        enterprise_vector_table = st.selectbox(
                            "选择企业向量表",
                            [''] + vector_tables,
                            key='enterprise_vector_match'
                        )
                        st.session_state.matching_config['enterprise_vector_table'] = enterprise_vector_table

                    with col2:
                        standard_vector_table = st.selectbox(
                            "选择标准地址向量表",
                            [''] + vector_tables,
                            key='standard_vector_match'
                        )
                        st.session_state.matching_config['standard_vector_table'] = standard_vector_table

                with st.expander("匹配参数配置", expanded=True):
                    col1, col2 = st.columns(2)
                    with col1:
                        st.session_state.matching_config['recall_top_n'] = st.number_input(
                            "粗召回数量",
                            value=st.session_state.matching_config['recall_top_n'],
                            min_value=1,
                            max_value=500,
                            help="设置每个企业召回的候选地址数上限（实际返回可能因相似度阈值过滤而减少）"
                        )

                    with col2:
                        st.session_state.matching_config['similarity_threshold'] = st.slider(
                            "相似度阈值",
                            min_value=0.0,
                            max_value=1.0,
                            value=st.session_state.matching_config['similarity_threshold'],
                            step=0.01
                        )

                    if device == 'cuda':
                        st.success("✅ 将使用GPU进行推理")
                    else:
                        st.info("⚠️ 将使用CPU进行推理")

                if st.button("🚀 启动数据粗召回匹配", key='start_recall'):
                    if not enterprise_vector_table or not standard_vector_table:
                        st.error("请先选择向量表")
                    else:
                        start_recall_matching(db_config, device, enterprise_vector_table, standard_vector_table)

                db_conn.close()

        st.markdown("</div>", unsafe_allow_html=True)

        # 下部分：MGeo精确匹配
        st.markdown(f"<div class='status-card status-card-warning'>", unsafe_allow_html=True)
        st.subheader("MGeo精确匹配")

        if not st.session_state.connected:
            st.warning("⚠️ MGeo精确匹配需要数据库连接，请先在【数据库配置】页面配置并连接数据库")
        else:
            try:
                check_conn = DBConnection(
                    host=db_config['host'],
                    port=db_config['port'],
                    schema=db_config['schema'],
                    dbname=db_config['dbname'],
                    user=db_config['user'],
                    password=db_config['password']
                )
                if check_conn.connect():
                    recall_cursor = check_conn.execute(f"SELECT COUNT(*) FROM {_recall_table}")
                    recall_count = recall_cursor.fetchone()['count'] if recall_cursor else 0
                    check_conn.close()

                    if recall_count > 0:
                        st.success(f"✅ 检测到召回结果数据：{recall_count:,} 条记录")

                        if st.button("▶️ 启动MGeo精确匹配", key='start_mgeo'):
                            start_mgeo_ranking(db_config, device)
                    else:
                        st.warning("⚠️ 未检测到召回结果数据，请先执行数据粗召回匹配")
            except Exception as e:
                st.error(f"检查召回结果失败: {str(e)}")

        st.markdown("</div>", unsafe_allow_html=True)



    with match_tab2:
        show_mgeo_similarity_matching(db_config, device)
