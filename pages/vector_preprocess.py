"""
向量预处理页面
=============
配置企业表和标准地址表的字段映射，执行向量化，管理向量索引。
"""

import streamlit as st
import time
import threading
from database.connection import DBConnection
from database.data_loader import DataLoader
from database.vector_store import VectorStore
from config import Config
from utils.logger import logger
from ui_theme import Colors, Spacing, Typography, Radius, Shadow
from app_common import (
    format_time, _render_device_selector, _get_cached_db_connection,
    get_cached_tables, get_cached_vector_tables, invalidate_vector_tables_cache
)


def _init_vec_status():
    """初始化向量化状态"""
    return {
        'is_running': False,
        'table_type': '',
        'cancel_requested': False,
        'processed_count': 0,
        'total_count': 0,
        'progress': 0.0,
        'speed': 0.0,
        'elapsed': 0.0,
        'remaining': 0.0,
        'status_message': '',
        'error_message': '',
        'completed': False,
        'cancelled': False,
        'start_datetime': '',
        'end_datetime': '',
        'execution_time': 0.0
    }


def _init_index_status():
    """初始化索引创建状态"""
    return {
        'is_running': False,
        'completed': False,
        'error_message': '',
        'start_datetime': '',
        'end_datetime': '',
        'execution_time': 0.0,
        'start_time': 0.0
    }


def _start_vectorization(table_type, batch_size, device, mode='全表向量化'):
    """启动向量化后台线程"""
    vec_status = _init_vec_status()
    vec_status['is_running'] = True
    vec_status['table_type'] = table_type
    st.session_state.vec_status = vec_status

    if table_type == 'enterprise':
        _src = st.session_state.vec_config.get('enterprise_table', '')
        _vec = st.session_state.vec_config.get('enterprise_vector_table', '')
    else:
        _src = st.session_state.vec_config.get('standard_table', '')
        _vec = st.session_state.vec_config.get('standard_vector_table', '')
    if _src and _vec:
        st.session_state.vec_config.setdefault('table_vec_mapping', {})[_src] = _vec

    # 将 vec_status 引用直接传给后台线程（线程中无法访问 st.session_state）
    thread = threading.Thread(
        target=run_vectorization_background,
        args=(vec_status, st.session_state.db_config.copy(), st.session_state.vec_config.copy(),
              table_type, batch_size, device, mode),
        daemon=True
    )
    thread.start()


def run_vectorization_background(vec_status, db_config, vec_config, table_type, batch_size, device, mode='全表向量化'):
    """后台运行向量化（vec_status 由主线程传入，线程内直接操作）"""
    working_conn = None
    start_time = time.time()

    try:
        vec_status['start_datetime'] = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
        vec_status['status_message'] = '正在连接数据库...'
        logger.info(f"[向量化] 启动: table_type={table_type}, batch_size={batch_size}, device={device}")

        working_conn = DBConnection(
            host=db_config['host'],
            port=db_config['port'],
            schema=db_config['schema'],
            dbname=db_config['dbname'],
            user=db_config['user'],
            password=db_config['password']
        )

        if not working_conn.connect():
            vec_status['error_message'] = '无法连接数据库'
            vec_status['is_running'] = False
            logger.error("[向量化] 数据库连接失败")
            return

        logger.info("[向量化] 数据库连接成功")
        working_data_loader = DataLoader(working_conn)

        if table_type == 'enterprise':
            source_table = vec_config['enterprise_table']
            id_col = vec_config['enterprise_id_col']
            name_col = vec_config['enterprise_name_col']
            addr_col = vec_config['enterprise_address_col']
            vec_table = vec_config.get('enterprise_vector_table', Config.ENTERPRISE_VECTOR_TABLE)
        else:
            source_table = vec_config['standard_table']
            id_col = vec_config['standard_id_col']
            addr_col = vec_config['standard_address_col']
            room_col = vec_config['standard_room_col']
            vec_table = vec_config.get('standard_vector_table', Config.STANDARD_VECTOR_TABLE)

        logger.info(f"[向量化] 源表={source_table}, 目标向量表={vec_table}")

        is_incremental = (mode == '增量向量化')

        vec_status['status_message'] = '正在加载向量化模型...'
        from model.embedding import AddressEmbedder
        from app_common import get_cached_embedder
        import torch
        actual_device = device
        if device == 'cuda' and not torch.cuda.is_available():
            logger.warning("[向量化] GPU不可用，切换到CPU")
            actual_device = 'cpu'
        # 使用缓存的模型实例，避免每次向量化都重新加载（5-15秒/次）
        embedder = get_cached_embedder(actual_device)
        vector_dim = embedder.get_vector_dim()
        logger.info(f"[向量化] 模型加载完成, dim={vector_dim}, device={actual_device}")

        working_vector_store = VectorStore(working_conn)
        existing_dim = working_vector_store.check_vector_table_dimension(vec_table)
        if existing_dim is not None and existing_dim != vector_dim:
            logger.warning(f"[向量化] 维度不匹配: 现有={existing_dim}, 模型={vector_dim}, 重建表")
            working_vector_store.drop_vector_table(vec_table)

        working_vector_store.create_vector_table_with_dim(vec_table, vector_dim, table_type=table_type)
        logger.info(f"[向量化] 向量表 {vec_table} 就绪")

        # 增量模式：统计已向量化数量和待处理数量
        if is_incremental:
            already_vectorized = working_vector_store.get_vector_count(vec_table)
            total_count = working_data_loader.get_unvectorized_count(
                source_table, id_col, addr_col, vec_table
            )
            logger.info(f"[向量化] 增量模式, 已向量化: {already_vectorized}, 待处理: {total_count}")
        else:
            already_vectorized = 0
            total_count = working_data_loader.get_valid_address_count(source_table, addr_col)

        vec_status['total_count'] = total_count
        vec_status['status_message'] = f'共 {total_count:,} 条地址待处理'
        if is_incremental and already_vectorized > 0:
            vec_status['status_message'] += f'（跳过 {already_vectorized:,} 条已向量化）'
        logger.info(f"[向量化] 有效地址数: {total_count}")

        if total_count == 0:
            if is_incremental and already_vectorized > 0:
                vec_status['completed'] = True
                vec_status['is_running'] = False
                vec_status['end_datetime'] = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
                vec_status['execution_time'] = time.time() - start_time
                vec_status['status_message'] = f'增量向量化完成，所有 {already_vectorized:,} 条记录均已向量化'
                logger.info("[向量化] 增量模式：所有记录已向量化，无需处理")
                return
            vec_status['error_message'] = '没有有效的地址数据'
            vec_status['is_running'] = False
            logger.warning("[向量化] 无有效地址数据")
            return

        # ---- 批量导入优化：禁用 autovacuum 防止与 INSERT 争抢 I/O ----
        vec_status['status_message'] = '正在优化批量导入环境...'
        working_vector_store.disable_autovacuum(vec_table)

        # 删除已存在的向量索引（导入完成后重建），避免插入时维护索引开销
        # 索引名与 UI 创建索引时保持一致
        if table_type == 'enterprise':
            idx_name = 'idx_enterprise_vector'
        else:
            idx_name = 'idx_standard_vector'
        if working_vector_store.check_index_exists(vec_table, idx_name):
            logger.info(f"[向量化] 删除已有向量索引 {idx_name}，导入完成后重建")
            working_vector_store.drop_vector_index(idx_name)
        logger.info(f"[向量化] 批量导入环境就绪 (autovacuum=off, 无向量索引)")

        processed_count = 0
        batch_num = 0

        # 增量模式使用增量加载器
        if is_incremental:
            if table_type == 'enterprise':
                loader = working_data_loader.load_unvectorized_enterprise_data(
                    source_table, id_col, name_col, addr_col, vec_table, batch_size
                )
            else:
                loader = working_data_loader.load_unvectorized_standard_addresses(
                    source_table, id_col, addr_col, room_col, vec_table, batch_size
                )
        else:
            if table_type == 'enterprise':
                loader = working_data_loader.load_enterprise_data(
                    source_table, id_col, name_col, addr_col, batch_size
                )
            else:
                loader = working_data_loader.load_standard_addresses(
                    source_table, id_col, addr_col, room_col, batch_size
                )

        from concurrent.futures import ThreadPoolExecutor, Future
        _prefetch_executor = ThreadPoolExecutor(max_workers=1)
        _prefetch_future = None

        def _submit_prefetch(loader_iter):
            return _prefetch_executor.submit(lambda: next(loader_iter, None))

        loader_iter = iter(loader)
        _prefetch_future = _submit_prefetch(loader_iter)

        while True:
            try:
                if _prefetch_future is not None:
                    df = _prefetch_future.result()
                    _prefetch_future = None
                else:
                    df = next(loader_iter, None)
            except StopIteration:
                df = None

            if df is None:
                break

            _prefetch_future = _submit_prefetch(loader_iter)

            batch_num += 1
            if vec_status.get('cancel_requested'):
                logger.info(f"[向量化] 收到取消请求, 批次={batch_num}, 已处理={processed_count}")
                vec_status['status_message'] = '正在清空已写入数据...'
                working_vector_store.truncate_vector_table(vec_table)
                vec_status['cancelled'] = True
                vec_status['is_running'] = False
                vec_status['end_datetime'] = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
                vec_status['execution_time'] = time.time() - start_time
                vec_status['status_message'] = f'已取消，已清空 {vec_table} 表数据'
                logger.info(f"[向量化] 已取消, 清空了 {vec_table}")
                _prefetch_executor.shutdown(wait=False)
                return

            addresses = df['address'].tolist()
            source_ids = df['id'].tolist()

            if table_type == 'enterprise':
                extra = df['name'].tolist()
            else:
                extra = df.get('room_no', [''] * len(addresses)).tolist()

            vectors = embedder.encode(addresses)
            inserted = working_vector_store.insert_vectors(vectors, source_ids, addresses, vec_table, extra, table_type=table_type)

            processed_count += len(addresses)
            elapsed = time.time() - start_time
            speed = processed_count / elapsed if elapsed > 0 else 0

            vec_status['processed_count'] = processed_count
            vec_status['progress'] = processed_count / total_count
            vec_status['speed'] = speed
            vec_status['elapsed'] = elapsed
            vec_status['remaining'] = (total_count - processed_count) / speed if speed > 0 else 0
            vec_status['status_message'] = f'批次 {batch_num}: {processed_count:,}/{total_count:,}'

            if batch_num % 5 == 0:
                logger.info(f"[向量化] 批次={batch_num}, 进度={processed_count}/{total_count}")

        _prefetch_executor.shutdown(wait=True)

        # ---- 批量导入完成：回收空间并恢复 autovacuum ----
        vec_status['status_message'] = '正在 VACUUM ANALYZE...'
        working_vector_store.vacuum_table(vec_table, analyze=True)
        vec_status['status_message'] = '正在恢复 autovacuum...'
        working_vector_store.enable_autovacuum(vec_table)
        logger.info(f"[向量化] 表维护完成: VACUUM ANALYZE + autovacuum 已恢复")

        vec_status['completed'] = True
        vec_status['is_running'] = False
        vec_status['end_datetime'] = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
        vec_status['execution_time'] = time.time() - start_time
        # 检查是否有降级批次（模型推理失败时用随机向量填充）
        fallback_count = getattr(embedder, '_fallback_count', 0)
        if fallback_count > 0:
            vec_status['status_message'] = f'向量化完成，共处理 {processed_count:,} 条地址（⚠ {fallback_count} 批次推理失败，已用随机向量降级填充）'
            logger.warning(f"[向量化] 存在 {fallback_count} 批次降级填充，请检查模型状态")
        else:
            vec_status['status_message'] = f'向量化完成，共处理 {processed_count:,} 条地址'
        logger.info(f"[向量化] 完成: {processed_count}条, 耗时{vec_status['execution_time']:.2f}s")

    except Exception as e:
        logger.error(f"[向量化] 异常: {e}")
        import traceback
        logger.error(f"[向量化] Traceback: {traceback.format_exc()}")
        # 尝试更新状态
        try:
            if vec_status is not None:
                vec_status['is_running'] = False
                vec_status['error_message'] = str(e)
        except Exception:
            pass
        # 回退：直接修改 session_state
        try:
            st.session_state.vec_status['is_running'] = False
            st.session_state.vec_status['error_message'] = str(e)
        except Exception:
            pass
    finally:
        if working_conn:
            try:
                # 确保 autovacuum 一定恢复（包括取消/异常路径）
                working_vector_store = VectorStore(working_conn)
                working_vector_store.enable_autovacuum(vec_table)
                logger.info(f"[向量化] finally: autovacuum 已恢复 ({vec_table})")
            except Exception:
                pass
            try:
                working_conn.close()
            except Exception:
                pass


def _start_index_creation(db_config, table_name, index_name, index_type,
                          lists, m, ef_construction, maintenance_work_mem):
    """启动索引创建后台线程"""
    st.session_state.index_status = _init_index_status()
    st.session_state.index_status['is_running'] = True
    st.session_state.index_status['start_datetime'] = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
    st.session_state.index_status['start_time'] = time.time()

    thread = threading.Thread(
        target=run_index_creation_background,
        args=(db_config.copy(), table_name, index_name, index_type,
              lists, m, ef_construction, maintenance_work_mem),
        daemon=True
    )
    thread.start()


def run_index_creation_background(db_config, table_name, index_name, index_type,
                                  lists, m, ef_construction, maintenance_work_mem):
    """后台运行索引创建"""
    index_status = st.session_state.index_status
    working_conn = None
    logger.info(f"[索引创建] 开始: table={table_name}, index={index_name}, type={index_type}")

    try:
        logger.info(f"[索引创建] 连接数据库 host={db_config.get('host')} dbname={db_config.get('dbname')}")
        working_conn = DBConnection(
            host=db_config['host'],
            port=db_config['port'],
            schema=db_config['schema'],
            dbname=db_config['dbname'],
            user=db_config['user'],
            password=db_config['password']
        )

        if not working_conn.connect():
            index_status['error_message'] = '无法连接数据库'
            index_status['is_running'] = False
            logger.error("[索引创建] 数据库连接失败")
            return

        logger.info("[索引创建] 数据库连接成功")
        working_vector_store = VectorStore(working_conn)
        row_count = working_vector_store.get_vector_count(table_name)
        logger.info(f"[索引创建] 表 {table_name} 数据量: {row_count}")

        success = working_vector_store.create_vector_index(
            table_name=table_name,
            index_name=index_name,
            index_type=index_type,
            lists=lists,
            m=m,
            ef_construction=ef_construction,
            maintenance_work_mem=maintenance_work_mem
        )

        if success:
            index_status['completed'] = True
            index_status['end_datetime'] = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
            index_status['execution_time'] = time.time() - index_status['start_time']
            logger.info(f"Index {index_name} created successfully in {index_status['execution_time']:.2f}s")
        else:
            index_status['error_message'] = '索引创建失败，请查看日志'
            logger.error(f"[索引创建] create_vector_index 返回 False")
    except Exception as e:
        index_status['error_message'] = str(e)
        logger.error(f"[索引创建] 异常: {e}")
        import traceback
        logger.error(f"[索引创建] Traceback: {traceback.format_exc()}")
    finally:
        index_status['is_running'] = False
        logger.info(f"[索引创建] 线程结束, is_running={index_status['is_running']}, completed={index_status.get('completed')}, error={index_status.get('error_message')}")
        if working_conn:
            working_conn.close()


VEC_POLL_INTERVAL = 2  # 秒


@st.fragment(run_every=VEC_POLL_INTERVAL)
def render_vec_status_fragment():
    """
    向量化状态实时展示 fragment。
    每 2 秒自刷新一次，只刷新进度区域，不触发整页 rerun。
    后台线程通过 vec_status 引用直接更新状态，fragment 直接读取即可。
    """
    vec_status = st.session_state.vec_status

    st.progress(min(vec_status['progress'], 1.0))
    st.text(f"📦 已处理 {vec_status['processed_count']:,}/{vec_status['total_count']:,} ({vec_status['progress']*100:.1f}%)")
    st.text(f"⚡ 处理速度: {vec_status['speed']:.2f} 条/秒")
    st.text(f"⏱ 已执行时间: {format_time(vec_status['elapsed'])}")
    if vec_status['remaining'] > 0:
        st.text(f"⏳ 预计剩余时间: {format_time(vec_status['remaining'])}")
    st.info(vec_status['status_message'])

    if st.button("⏹ 取消向量化", type="primary"):
        st.session_state.vec_status['cancel_requested'] = True
        st.rerun()

    # 检测完成：设置触发器并主动触发整页刷新，切换到完成 UI。
    # 此前只设置 trigger 不 rerun，导致后台任务完成后页面仍停留在进度状态，
    # 必须等用户交互才会更新；现在在 fragment 内直接 st.rerun() 一次即可自动刷新。
    if not vec_status['is_running']:
        st.session_state['_vec_finished_trigger'] = True
        st.rerun()


def show_vector_preprocess():
    """向量预处理页面：配置企业表和标准地址表的字段映射，执行向量化"""
    db_ready = True
    tables = []
    vector_store = None

    if not st.session_state.connected:
        st.warning("⚠️ 向量预处理功能需要数据库连接，请先在【数据库配置】页面配置并连接数据库")
        db_ready = False

    db_conn = None
    if db_ready:
        db_config = st.session_state.db_config
        db_conn = _get_cached_db_connection(
            host=db_config['host'],
            port=db_config['port'],
            schema=db_config['schema'],
            dbname=db_config['dbname'],
            user=db_config['user'],
            password=db_config['password']
        )
        if db_conn is None:
            st.error("无法连接数据库，请检查配置")
            db_ready = False

    if db_ready:
        try:
            # 使用缓存的表列表查询（30秒TTL）
            all_tables = list(get_cached_tables(
                db_config['host'], db_config['port'], db_config['dbname'],
                db_config['user'], db_config['schema']
            ))
            if not all_tables:
                st.warning("数据库中没有可用的数据表")
                db_ready = False
            else:
                # 获取向量表列表，用于从源表 selectbox 中过滤掉向量表
                # 避免用户误将向量表（如 enterprise_vectors）选为源表，
                # 否则会触发字段清除逻辑，导致企业表配置丢失、字段显示为同一个值
                _vector_table_set = set(get_cached_vector_tables(
                    db_config['host'], db_config['port'], db_config['dbname'],
                    db_config['user'], db_config['password'], db_config['schema']
                ))
                tables = [t for t in all_tables if t not in _vector_table_set]
                if not tables:
                    # 极端情况：所有表都是向量表，保留全部以避免空列表
                    tables = all_tables
        except Exception as e:
            st.error(f"获取数据表列表失败: {str(e)}")
            db_ready = False

    if db_ready:
        vector_store = VectorStore(db_conn)

    # ========== 页面级统一按钮样式 ==========
    st.markdown(f"""
    <style>
    .vec-page-btn {{
        height: 36px !important;
        font-size: 14px !important;
        font-weight: 500 !important;
        border-radius: {Radius.SM} !important;
        border-width: 1px !important;
        border-style: solid !important;
        box-shadow: none !important;
        transition: all 0.15s ease !important;
        padding: 0 16px !important;
    }}
    .vec-page-btn:hover {{
        transform: translateY(-1px);
        box-shadow: 0 2px 4px rgba(0,0,0,0.08) !important;
    }}

    /* 主操作按钮 - 蓝色 */
    .vec-btn-primary {{
        background-color: {Colors.PRIMARY_LIGHT} !important;
        border-color: {Colors.PRIMARY_LIGHT} !important;
        color: white !important;
    }}
    .vec-btn-primary:hover {{
        background-color: {Colors.PRIMARY} !important;
        border-color: {Colors.PRIMARY} !important;
    }}

    /* 次要操作按钮 - 浅蓝 */
    .vec-btn-secondary {{
        background-color: {Colors.INFO_BG} !important;
        border-color: {Colors.INFO_BORDER} !important;
        color: {Colors.INFO} !important;
    }}
    .vec-btn-secondary:hover {{
        background-color: #bfdbfe !important;
        border-color: {Colors.PRIMARY} !important;
        color: {Colors.PRIMARY} !important;
    }}

    /* 警告操作按钮 - 浅黄 */
    .vec-btn-warning {{
        background-color: {Colors.WARNING_BG} !important;
        border-color: {Colors.WARNING_BORDER} !important;
        color: {Colors.WARNING} !important;
    }}
    .vec-btn-warning:hover {{
        background-color: #fde68a !important;
        border-color: #ca8a04 !important;
        color: #713f12 !important;
    }}

    /* 危险操作按钮 - 浅红 */
    .vec-btn-danger {{
        background-color: {Colors.ERROR_BG} !important;
        border-color: {Colors.ERROR_BORDER} !important;
        color: {Colors.ERROR} !important;
    }}
    .vec-btn-danger:hover {{
        background-color: #fecaca !important;
        border-color: #b91c1c !important;
        color: #7f1d1d !important;
    }}

    /* 模块标题样式 */
    .vec-module-title {{
        font-size: 16px;
        font-weight: {Typography.WEIGHT_SEMIBOLD};
        color: {Colors.TEXT_PRIMARY};
        margin: 0 0 12px 0;
        padding-bottom: 8px;
        border-bottom: 2px solid {Colors.PRIMARY};
        display: flex;
        align-items: center;
        gap: 8px;
    }}
    .vec-step-num {{
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 24px;
        height: 24px;
        border-radius: 50%;
        background: {Colors.PRIMARY};
        color: white;
        font-size: 12px;
        font-weight: 700;
        flex-shrink: 0;
    }}

    /* 小标签样式 */
    .vec-badge {{
        display: inline-flex;
        align-items: center;
        padding: 2px 8px;
        border-radius: {Radius.SM};
        font-size: 12px;
        font-weight: 500;
        margin-left: 8px;
    }}
    .vec-badge-blue {{
        background-color: {Colors.INFO_BG};
        color: {Colors.INFO};
    }}
    .vec-badge-green {{
        background-color: {Colors.SUCCESS_BG};
        color: {Colors.SUCCESS};
    }}
    .vec-badge-gray {{
        background-color: {Colors.SURFACE_SECONDARY};
        color: {Colors.TEXT_MUTED};
    }}

    </style>
    """, unsafe_allow_html=True)

    # ========== 步骤1：向量表创建与配置 ==========
    st.markdown('<div class="vec-module-title"><span class="vec-step-num">1</span> 向量表创建与字段配置</div>', unsafe_allow_html=True)

    # 创建向量表 + 向量表管理 左右布局
    create_col, manage_col = st.columns([3, 2])

    with create_col:
        # 企业表配置
        with st.container(border=True):
            ent_vec_table = st.session_state.vec_config.get('enterprise_vector_table', Config.ENTERPRISE_VECTOR_TABLE)
            ent_table_exists = vector_store.check_table_exists(ent_vec_table) if db_ready else False
            ent_count_in_table = vector_store.get_vector_count(ent_vec_table) if ent_table_exists else 0

            st.markdown(
                f'<div style="font-weight: {Typography.WEIGHT_SEMIBOLD}; font-size: 14px; margin-bottom: 10px;">'
                f'🏢 企业表配置'
                f'<span class="vec-badge vec-badge-{"green" if ent_count_in_table > 0 else "gray"}">'
                f'{ent_count_in_table:,} 条</span></div>',
                unsafe_allow_html=True
            )

            ent_col1, ent_col2 = st.columns([1, 1])
            with ent_col1:
                # 构建选项列表，始终包含已保存的值，防止 db 异常时 selectbox 被迫重置
                _ent_options = [''] + tables
                _saved_ent_table = st.session_state.vec_config.get('enterprise_table', '')
                if _saved_ent_table and _saved_ent_table not in _ent_options:
                    _ent_options.append(_saved_ent_table)

                # session_state 恢复机制：仅在 widget 值失效时从 vec_config 恢复
                _current_ent = st.session_state.get('enterprise_table_vec', '')
                if not _current_ent or _current_ent not in _ent_options:
                    if _saved_ent_table and _saved_ent_table in _ent_options:
                        st.session_state['enterprise_table_vec'] = _saved_ent_table

                enterprise_table = st.selectbox(
                    "选择企业表",
                    _ent_options,
                    key='enterprise_table_vec'
                )
                if enterprise_table and enterprise_table != st.session_state.vec_config.get('enterprise_table'):
                    st.session_state.vec_config['enterprise_id_col'] = ''
                    st.session_state.vec_config['enterprise_name_col'] = ''
                    st.session_state.vec_config['enterprise_address_col'] = ''
                    _mapping = st.session_state.vec_config.get('table_vec_mapping', {})
                    new_ent_vec_table = _mapping.get(enterprise_table, f"{enterprise_table}_vectors")
                    st.session_state.vec_config['enterprise_vector_table'] = new_ent_vec_table
                    # 清理旧表的字段选择状态
                    for key in ['enterprise_id_vec', 'enterprise_name_vec', 'enterprise_addr_vec']:
                        if key in st.session_state:
                            del st.session_state[key]
                if enterprise_table:
                    st.session_state.vec_config['enterprise_table'] = enterprise_table
                # 重新计算：selectbox change handler 可能已更新 vec_config，确保后续 text_input 使用最新值
                ent_vec_table = st.session_state.vec_config.get('enterprise_vector_table', Config.ENTERPRISE_VECTOR_TABLE)

            enterprise_columns = []
            if enterprise_table and db_conn:
                try:
                    enterprise_columns = [col[0] for col in db_conn.get_columns(enterprise_table)]
                except Exception as e:
                    st.error(f"获取企业表字段失败: {str(e)}")
                    enterprise_columns = []

            with ent_col2:
                if enterprise_columns:
                    # session_state 恢复机制：仅在 widget 值失效时从 vec_config 恢复
                    _current_id_val = st.session_state.get('enterprise_id_vec', '')
                    _current_name_val = st.session_state.get('enterprise_name_vec', '')
                    _current_addr_val = st.session_state.get('enterprise_addr_vec', '')
                    if _current_id_val not in enterprise_columns:
                        _saved_id = st.session_state.vec_config.get('enterprise_id_col', '')
                        if _saved_id and _saved_id in enterprise_columns:
                            st.session_state['enterprise_id_vec'] = _saved_id
                    if _current_name_val not in enterprise_columns:
                        _saved_name = st.session_state.vec_config.get('enterprise_name_col', '')
                        if _saved_name and _saved_name in enterprise_columns:
                            st.session_state['enterprise_name_vec'] = _saved_name
                    if _current_addr_val not in enterprise_columns:
                        _saved_addr = st.session_state.vec_config.get('enterprise_address_col', '')
                        if _saved_addr and _saved_addr in enterprise_columns:
                            st.session_state['enterprise_addr_vec'] = _saved_addr

                    st.session_state.vec_config['enterprise_id_col'] = st.selectbox(
                        "企业标识字段", enterprise_columns, key='enterprise_id_vec')
                    st.session_state.vec_config['enterprise_name_col'] = st.selectbox(
                        "企业名字段", enterprise_columns, key='enterprise_name_vec')
                    st.session_state.vec_config['enterprise_address_col'] = st.selectbox(
                        "企业地址字段", enterprise_columns, key='enterprise_addr_vec')
                else:
                    # 保留 widget key，避免 Streamlit 因 widget 未渲染而删除 session_state
                    # 优先从 session_state 取，为空则从 vec_config 恢复
                    _cur_id = st.session_state.get('enterprise_id_vec', '') or st.session_state.vec_config.get('enterprise_id_col', '')
                    _cur_name = st.session_state.get('enterprise_name_vec', '') or st.session_state.vec_config.get('enterprise_name_col', '')
                    _cur_addr = st.session_state.get('enterprise_addr_vec', '') or st.session_state.vec_config.get('enterprise_address_col', '')
                    st.selectbox("企业标识字段", [_cur_id] if _cur_id else ['请先选择企业表'],
                                disabled=True, key='enterprise_id_vec')
                    st.selectbox("企业名字段", [_cur_name] if _cur_name else ['请先选择企业表'],
                                disabled=True, key='enterprise_name_vec')
                    st.selectbox("企业地址字段", [_cur_addr] if _cur_addr else ['请先选择企业表'],
                                disabled=True, key='enterprise_addr_vec')

            # 自定义向量表名
            st.markdown('<div style="font-size: 12px; color: {Colors.TEXT_SECONDARY}; margin: 8px 0 4px 0;">向量表名</div>'.format(Colors=Colors), unsafe_allow_html=True)
            ent_name_col1, ent_name_col2 = st.columns([3, 1])
            with ent_name_col1:
                # 使用包含表名的动态 key，确保切换表时 widget 状态重置
                _ent_name_key = f'enterprise_vector_table_name_{enterprise_table}' if enterprise_table else 'enterprise_vector_table_name'
                ent_custom_name = st.text_input(
                    "企业向量表名",
                    value=ent_vec_table,
                    key=_ent_name_key,
                    label_visibility="collapsed",
                    help="可自定义企业向量表名称，默认为系统自动生成"
                )
                if ent_custom_name and ent_custom_name != ent_vec_table:
                    st.session_state.vec_config['enterprise_vector_table'] = ent_custom_name.strip()
            with ent_name_col2:
                if st.button("创建", key='create_ent_btn',
                            help="创建企业向量表（如已存在则跳过）", disabled=not db_ready):
                    if db_ready:
                        with st.spinner("正在创建..."):
                            target_name = st.session_state.vec_config.get('enterprise_vector_table', Config.ENTERPRISE_VECTOR_TABLE)
                            src_table = st.session_state.vec_config.get('enterprise_table', '')
                            if vector_store.check_table_exists(target_name):
                                st.info(f"企业向量表 {target_name} 已存在，无需重复创建")
                                if src_table:
                                    st.session_state.vec_config.setdefault('table_vec_mapping', {})[src_table] = target_name
                            elif vector_store.create_vector_table(target_name, table_type='enterprise'):
                                st.success(f"企业向量表 {target_name} 创建成功")
                                if src_table:
                                    st.session_state.vec_config.setdefault('table_vec_mapping', {})[src_table] = target_name
                                # 清除向量表缓存，触发右侧管理区立即刷新
                                invalidate_vector_tables_cache()
                                # 立即 rerun，让右侧"向量表管理"显示新表
                                # 同时避免按钮回调与后续操作的状态时序混乱
                                st.rerun()
                            else:
                                st.error("创建失败，请查看日志")

        # 标准地址表配置
        with st.container(border=True):
            std_vec_table = st.session_state.vec_config.get('standard_vector_table', Config.STANDARD_VECTOR_TABLE)
            std_table_exists = vector_store.check_table_exists(std_vec_table) if db_ready else False
            std_count_in_table = vector_store.get_vector_count(std_vec_table) if std_table_exists else 0

            st.markdown(
                f'<div style="font-weight: {Typography.WEIGHT_SEMIBOLD}; font-size: 14px; margin-bottom: 10px;">'
                f'📍 标准地址表配置'
                f'<span class="vec-badge vec-badge-{"green" if std_count_in_table > 0 else "gray"}">'
                f'{std_count_in_table:,} 条</span></div>',
                unsafe_allow_html=True
            )

            std_col1, std_col2 = st.columns([1, 1])
            with std_col1:
                # 构建选项列表，始终包含已保存的值，防止 db 异常时 selectbox 被迫重置
                _std_options = [''] + tables
                _saved_std_table = st.session_state.vec_config.get('standard_table', '')
                if _saved_std_table and _saved_std_table not in _std_options:
                    _std_options.append(_saved_std_table)

                # session_state 恢复机制：仅在 widget 值失效时从 vec_config 恢复
                _current_std = st.session_state.get('standard_table_vec', '')
                if not _current_std or _current_std not in _std_options:
                    if _saved_std_table and _saved_std_table in _std_options:
                        st.session_state['standard_table_vec'] = _saved_std_table

                standard_table = st.selectbox(
                    "选择标准地址表",
                    _std_options,
                    key='standard_table_vec'
                )
                if standard_table and standard_table != st.session_state.vec_config.get('standard_table'):
                    st.session_state.vec_config['standard_id_col'] = ''
                    st.session_state.vec_config['standard_address_col'] = ''
                    st.session_state.vec_config['standard_room_col'] = ''
                    _mapping = st.session_state.vec_config.get('table_vec_mapping', {})
                    new_std_vec_table = _mapping.get(standard_table, f"{standard_table}_vectors")
                    st.session_state.vec_config['standard_vector_table'] = new_std_vec_table
                    # 清理旧表的字段选择状态
                    for key in ['standard_id_vec', 'standard_addr_vec', 'standard_room_vec']:
                        if key in st.session_state:
                            del st.session_state[key]
                if standard_table:
                    st.session_state.vec_config['standard_table'] = standard_table
                # 重新计算：selectbox change handler 可能已更新 vec_config，确保后续 text_input 使用最新值
                std_vec_table = st.session_state.vec_config.get('standard_vector_table', Config.STANDARD_VECTOR_TABLE)

            standard_columns = []
            if standard_table and db_conn:
                try:
                    standard_columns = [col[0] for col in db_conn.get_columns(standard_table)]
                except Exception as e:
                    st.error(f"获取标准地址表字段失败: {str(e)}")
                    standard_columns = []

            with std_col2:
                if standard_columns:
                    # session_state 恢复机制：仅在 widget 值失效时从 vec_config 恢复
                    _current_std_id = st.session_state.get('standard_id_vec', '')
                    _current_std_addr = st.session_state.get('standard_addr_vec', '')
                    _current_std_room = st.session_state.get('standard_room_vec', '')
                    if _current_std_id not in standard_columns:
                        _saved_std_id = st.session_state.vec_config.get('standard_id_col', '')
                        if _saved_std_id and _saved_std_id in standard_columns:
                            st.session_state['standard_id_vec'] = _saved_std_id
                    if _current_std_addr not in standard_columns:
                        _saved_std_addr = st.session_state.vec_config.get('standard_address_col', '')
                        if _saved_std_addr and _saved_std_addr in standard_columns:
                            st.session_state['standard_addr_vec'] = _saved_std_addr
                    if _current_std_room not in standard_columns:
                        _saved_std_room = st.session_state.vec_config.get('standard_room_col', '')
                        if _saved_std_room and _saved_std_room in standard_columns:
                            st.session_state['standard_room_vec'] = _saved_std_room

                    st.session_state.vec_config['standard_id_col'] = st.selectbox(
                        "地址编码字段", standard_columns, key='standard_id_vec')
                    st.session_state.vec_config['standard_address_col'] = st.selectbox(
                        "标准地址字段", standard_columns, key='standard_addr_vec')
                    st.session_state.vec_config['standard_room_col'] = st.selectbox(
                        "房屋编码字段", standard_columns, key='standard_room_vec')
                else:
                    # 保留 widget key，避免 Streamlit 因 widget 未渲染而删除 session_state
                    # 优先从 session_state 取，为空则从 vec_config 恢复
                    _cur_std_id = st.session_state.get('standard_id_vec', '') or st.session_state.vec_config.get('standard_id_col', '')
                    _cur_std_addr = st.session_state.get('standard_addr_vec', '') or st.session_state.vec_config.get('standard_address_col', '')
                    _cur_std_room = st.session_state.get('standard_room_vec', '') or st.session_state.vec_config.get('standard_room_col', '')
                    st.selectbox("地址编码字段", [_cur_std_id] if _cur_std_id else ['请先选择标准地址表'],
                                disabled=True, key='standard_id_vec')
                    st.selectbox("标准地址字段", [_cur_std_addr] if _cur_std_addr else ['请先选择标准地址表'],
                                disabled=True, key='standard_addr_vec')
                    st.selectbox("房屋编码字段", [_cur_std_room] if _cur_std_room else ['请先选择标准地址表'],
                                disabled=True, key='standard_room_vec')

            # 自定义向量表名
            st.markdown('<div style="font-size: 12px; color: {Colors.TEXT_SECONDARY}; margin: 8px 0 4px 0;">向量表名</div>'.format(Colors=Colors), unsafe_allow_html=True)
            std_name_col1, std_name_col2 = st.columns([3, 1])
            with std_name_col1:
                # 使用包含表名的动态 key，确保切换表时 widget 状态重置
                _std_name_key = f'standard_vector_table_name_{standard_table}' if standard_table else 'standard_vector_table_name'
                std_custom_name = st.text_input(
                    "标准地址向量表名",
                    value=std_vec_table,
                    key=_std_name_key,
                    label_visibility="collapsed",
                    help="可自定义标准地址向量表名称，默认为系统自动生成"
                )
                if std_custom_name and std_custom_name != std_vec_table:
                    st.session_state.vec_config['standard_vector_table'] = std_custom_name.strip()
            with std_name_col2:
                if st.button("创建", key='create_std_btn',
                            help="创建标准地址向量表（如已存在则跳过）", disabled=not db_ready):
                    if db_ready:
                        with st.spinner("正在创建..."):
                            target_name = st.session_state.vec_config.get('standard_vector_table', Config.STANDARD_VECTOR_TABLE)
                            src_table = st.session_state.vec_config.get('standard_table', '')
                            if vector_store.check_table_exists(target_name):
                                st.info(f"标准地址向量表 {target_name} 已存在，无需重复创建")
                                if src_table:
                                    st.session_state.vec_config.setdefault('table_vec_mapping', {})[src_table] = target_name
                            elif vector_store.create_vector_table(target_name, table_type='standard'):
                                st.success(f"标准地址向量表 {target_name} 创建成功")
                                if src_table:
                                    st.session_state.vec_config.setdefault('table_vec_mapping', {})[src_table] = target_name
                                # 清除向量表缓存，触发右侧管理区立即刷新
                                invalidate_vector_tables_cache()
                                # 立即 rerun，让右侧"向量表管理"显示新表
                                # 同时避免按钮回调与后续操作的状态时序混乱
                                st.rerun()
                            else:
                                st.error("创建失败，请查看日志")

    with manage_col:
        # 向量表管理
        with st.container(border=True):
            st.markdown(
                f'<div style="font-weight: {Typography.WEIGHT_SEMIBOLD}; font-size: 14px; margin-bottom: 10px;">'
                f'🗄 向量表管理</div>',
                unsafe_allow_html=True
            )

            vector_tables = list(get_cached_vector_tables(
                db_config['host'], db_config['port'], db_config['dbname'],
                db_config['user'], db_config['password'], db_config['schema']
            )) if db_ready else []

            if vector_tables:
                st.caption(f"当前共 {len(vector_tables)} 个向量表")

                # ========== 向量表列表展示（支持搜索、分页、详情）==========
                st.markdown('<div style="font-size: 13px; color: {Colors.TEXT_SECONDARY}; margin: 8px 0 4px 0;">📋 向量表列表</div>'.format(Colors=Colors), unsafe_allow_html=True)

                # 搜索框
                search_keyword = st.text_input("搜索向量表", placeholder="输入表名关键词过滤...", key='vector_table_search', label_visibility="collapsed")
                filtered_tables = [vt for vt in vector_tables if search_keyword.lower() in vt.lower()] if search_keyword else vector_tables

                # 分页状态初始化
                if 'vector_table_list_page' not in st.session_state:
                    st.session_state.vector_table_list_page = 1
                page_size = 6
                total_tables = len(filtered_tables)
                total_pages = max(1, (total_tables + page_size - 1) // page_size)
                current_page = min(st.session_state.vector_table_list_page, total_pages)
                start_idx = (current_page - 1) * page_size
                end_idx = min(start_idx + page_size, total_tables)
                page_tables = filtered_tables[start_idx:end_idx]

                # 向量表列表区域 - 固定高度，防止列表过长导致右栏与左栏不对齐
                with st.container(height=420):
                    # 展示当前页向量表
                    for i, vt in enumerate(page_tables):
                        cnt = vector_store.get_vector_count(vt)
                        dim = vector_store.check_vector_table_dimension(vt)
                        dim_str = f"{dim}维" if dim else "维度未知"

                        # 详情展开器
                        with st.expander(f"**{vt}**  |  {cnt:,}条  |  {dim_str}", expanded=False):
                            detail = vector_store.get_vector_table_detail(vt)
                            if detail:
                                # 基本信息
                                info_cols = st.columns(3)
                                with info_cols[0]:
                                    st.markdown(f"**数据量**: {detail['row_count']:,} 条")
                                with info_cols[1]:
                                    st.markdown(f"**向量维度**: {detail['vector_dim']} 维" if detail['vector_dim'] else "**向量维度**: 未知")
                                with info_cols[2]:
                                    st.markdown(f"**表大小**: {detail['table_size']}")
                                if detail['created_at']:
                                    st.markdown(f"**最早数据时间**: {detail['created_at']}")

                                # 字段信息
                                if detail['columns']:
                                    st.markdown("**字段结构**:")
                                    col_df_data = []
                                    for col_name, col_type in detail['columns']:
                                        col_df_data.append({"字段名": col_name, "数据类型": col_type})
                                    st.dataframe(col_df_data, use_container_width=True, hide_index=True)

                                # 索引信息
                                if detail['indexes']:
                                    st.markdown("**索引**:")
                                    idx_df_data = []
                                    for idx_name, idx_type in detail['indexes']:
                                        idx_df_data.append({"索引名": idx_name, "类型": idx_type})
                                    st.dataframe(idx_df_data, use_container_width=True, hide_index=True)
                                else:
                                    st.markdown("**索引**: 暂无")
                            else:
                                st.warning("获取表详情失败")

                # 分页控制（放在固定高度容器外面）
                if total_pages > 1:
                    page_col1, page_col2, page_col3, page_col4 = st.columns([1, 1, 2, 1])
                    with page_col1:
                        if st.button("⏮️ 首页", key='vt_first_page', disabled=current_page <= 1):
                            st.session_state.vector_table_list_page = 1
                            st.rerun()
                    with page_col2:
                        if st.button("◀️ 上一页", key='vt_prev_page', disabled=current_page <= 1):
                            st.session_state.vector_table_list_page = max(1, current_page - 1)
                            st.rerun()
                    with page_col3:
                        st.markdown(f'<div style="text-align: center; padding-top: 8px; font-size: 13px;">第 {current_page} / {total_pages} 页 (共 {total_tables} 个)</div>', unsafe_allow_html=True)
                    with page_col4:
                        if st.button("下一页 ▶️", key='vt_next_page', disabled=current_page >= total_pages):
                            st.session_state.vector_table_list_page = min(total_pages, current_page + 1)
                            st.rerun()

                st.divider()

                # 重命名向量表
                st.markdown('<div style="font-size: 13px; color: {Colors.TEXT_SECONDARY}; margin: 8px 0 4px 0;">✏️ 重命名向量表</div>'.format(Colors=Colors), unsafe_allow_html=True)
                rename_col1, rename_col2, rename_col3 = st.columns([2, 2, 1])
                with rename_col1:
                    rename_old = st.selectbox("选择要重命名的向量表", vector_tables, key='rename_table_select')
                with rename_col2:
                    rename_new = st.text_input("新表名", value=rename_old if rename_old else '', key='rename_new_name', label_visibility="collapsed")
                with rename_col3:
                    if st.button("重命名", key='rename_btn', help="重命名选中的向量表"):
                        if rename_new and rename_new != rename_old:
                            if vector_store.check_table_exists(rename_new):
                                st.error(f"表名 {rename_new} 已存在")
                            else:
                                if vector_store.rename_vector_table(rename_old, rename_new):
                                    st.success(f"已重命名为 {rename_new}")
                                    if st.session_state.vec_config.get('enterprise_vector_table') == rename_old:
                                        st.session_state.vec_config['enterprise_vector_table'] = rename_new
                                    if st.session_state.vec_config.get('standard_vector_table') == rename_old:
                                        st.session_state.vec_config['standard_vector_table'] = rename_new
                                    # 清除向量表缓存，让筛选框立即更新
                                    invalidate_vector_tables_cache()
                                    st.rerun()
                                else:
                                    st.error("重命名失败")
                        else:
                            st.warning("请输入不同的新表名")

                st.divider()

                # 清空向量表
                st.markdown('<div style="font-size: 13px; color: {Colors.TEXT_SECONDARY}; margin: 8px 0 4px 0;">🧹 清空向量表</div>'.format(Colors=Colors), unsafe_allow_html=True)
                trunc_col1, trunc_col2 = st.columns([3, 2])
                with trunc_col1:
                    trunc_table = st.selectbox("选择要清空的向量表", vector_tables, key='trunc_table_select')
                with trunc_col2:
                    if st.button("清空", key='trunc_btn', help="清空选中向量表的所有数据"):
                        if st.session_state.get('confirm_trunc') and st.session_state.get('confirm_trunc_table') == trunc_table:
                            if vector_store.truncate_vector_table(trunc_table):
                                st.success(f"{trunc_table} 已清空")
                                st.session_state.confirm_trunc = False
                                st.session_state.confirm_trunc_table = ''
                                # 清除向量表缓存，让列表中的记录数立即更新
                                invalidate_vector_tables_cache()
                                st.rerun()
                        else:
                            st.warning(f"确定清空 {trunc_table}？再次点击确认")
                            st.session_state.confirm_trunc = True
                            st.session_state.confirm_trunc_table = trunc_table

                st.divider()

                # 删除向量表
                st.markdown('<div style="font-size: 13px; color: {Colors.TEXT_SECONDARY}; margin: 8px 0 4px 0;">🗑️ 删除向量表</div>'.format(Colors=Colors), unsafe_allow_html=True)
                del_col1, del_col2 = st.columns([3, 2])
                with del_col1:
                    del_table = st.selectbox("选择要删除的向量表", vector_tables, key='del_table_select')
                with del_col2:
                    if st.button("删除", key='delete_table_btn', help="彻底删除选中向量表（不可恢复）"):
                        if st.session_state.get('confirm_delete') and st.session_state.get('confirm_delete_table') == del_table:
                            if vector_store.drop_vector_table(del_table):
                                st.success(f"{del_table} 删除成功")
                                st.session_state.confirm_delete = False
                                st.session_state.confirm_delete_table = ''
                                # 清除向量表缓存，让筛选框立即移除已删除的表
                                invalidate_vector_tables_cache()
                                st.rerun()
                        else:
                            st.warning(f"确定删除 {del_table}？再次点击确认")
                            st.session_state.confirm_delete = True
                            st.session_state.confirm_delete_table = del_table
            else:
                st.info("暂无向量表")

    st.divider()

    # vec_status 已在 app_common.init_session_state() 中初始化

    # ========== 步骤2：向量化执行 ==========
    st.markdown('<div class="vec-module-title"><span class="vec-step-num">2</span> 向量化执行</div>', unsafe_allow_html=True)

    vec_device = _render_device_selector(key='vec_device_selector')
    batch_size = st.number_input("处理批次大小", value=1000, min_value=100, max_value=10000, key='vec_batch_size')
    vec_mode = st.selectbox(
        "向量化模式",
        options=['全表向量化', '增量向量化'],
        index=0,
        help="全表向量化：重新向量化整张表的所有记录\n增量向量化：仅向量化尚未处理的记录（跳过已存在于向量表中的数据）"
    )

    vec_status = st.session_state.vec_status

    # 检测完成触发器：fragment 检测到任务结束时设置，此处清除并刷新以显示完成 UI
    if st.session_state.get('_vec_finished_trigger'):
        del st.session_state['_vec_finished_trigger']
        st.rerun()

    if vec_status['is_running']:
        # 使用 fragment 局部刷新进度，避免 time.sleep+st.rerun 阻塞主线程
        render_vec_status_fragment()

    elif vec_status['completed']:
        st.success(f"✅ {vec_status['status_message']}")
        st.text(f"开始时间: {vec_status['start_datetime']}")
        st.text(f"结束时间: {vec_status['end_datetime']}")
        st.text(f"总耗时: {format_time(vec_status['execution_time'])}")
        st.text(f"平均速度: {vec_status['processed_count'] / vec_status['execution_time']:.2f} 条/秒" if vec_status['execution_time'] > 0 else "")
        if st.button("清除状态", key='vec_clear_completed'):
            st.session_state.vec_status = _init_vec_status()
            st.rerun()

    elif vec_status['cancelled']:
        st.warning(f"⚠️ 向量化已取消 - {vec_status['status_message']}")
        if st.button("清除状态", key='vec_clear_cancelled'):
            st.session_state.vec_status = _init_vec_status()
            st.rerun()

    elif vec_status['error_message']:
        st.error(f"❌ 向量化失败: {vec_status['error_message']}")
        if st.button("清除状态", key='vec_clear_error'):
            st.session_state.vec_status = _init_vec_status()
            st.rerun()

    else:
        # 向量化执行按钮 - 采用紧凑精致的卡片式布局
        st.markdown(f"""
        <style>
        .vec-action-container {{
            display: flex;
            gap: 16px;
            margin-top: 8px;
        }}
        .vec-action-card {{
            flex: 1;
            background: {Colors.SURFACE};
            border: 1px solid {Colors.BORDER};
            border-radius: {Radius.MD};
            padding: 20px;
            text-align: center;
            transition: all 0.2s ease;
            cursor: pointer;
        }}
        .vec-action-card:hover {{
            border-color: {Colors.PRIMARY};
            box-shadow: {Shadow.ELEVATED};
            transform: translateY(-2px);
        }}
        .vec-action-icon {{
            font-size: 24px;
            margin-bottom: 8px;
        }}
        .vec-action-title {{
            font-size: 15px;
            font-weight: {Typography.WEIGHT_SEMIBOLD};
            color: {Colors.TEXT_PRIMARY};
            margin-bottom: 4px;
        }}
        .vec-action-desc {{
            font-size: 12px;
            color: {Colors.TEXT_MUTED};
            margin-bottom: 16px;
        }}
        </style>
        """, unsafe_allow_html=True)

        # 获取当前配置的向量表名及存在状态
        ent_vec_table = st.session_state.vec_config.get('enterprise_vector_table', Config.ENTERPRISE_VECTOR_TABLE)
        std_vec_table = st.session_state.vec_config.get('standard_vector_table', Config.STANDARD_VECTOR_TABLE)
        ent_vec_exists = vector_store.check_table_exists(ent_vec_table) if db_ready else False
        std_vec_exists = vector_store.check_table_exists(std_vec_table) if db_ready else False

        # 获取当前配置的数据源信息
        _ent_src = st.session_state.vec_config
        _ent_table_ok = _ent_src['enterprise_table'] and _ent_src['enterprise_id_col'] and _ent_src['enterprise_name_col'] and _ent_src['enterprise_address_col']
        _std_table_ok = _ent_src['standard_table'] and _ent_src['standard_id_col'] and _ent_src['standard_address_col']

        vec_col1, vec_col2 = st.columns(2)
        with vec_col1:
            with st.container(border=True):
                st.markdown(
                    f'<div style="text-align: center; padding: 8px 0 4px 0;">'
                    f'<div style="font-size: 28px; margin-bottom: 8px;">🏢</div>'
                    f'<div style="font-size: 15px; font-weight: {Typography.WEIGHT_SEMIBOLD}; color: {Colors.TEXT_PRIMARY};">企业表向量化</div>'
                    f'</div>',
                    unsafe_allow_html=True
                )
                # 数据源信息
                if _ent_table_ok:
                    st.caption(f"源表: **{_ent_src['enterprise_table']}** | 标识: `{_ent_src['enterprise_id_col']}` | 名称: `{_ent_src['enterprise_name_col']}` | 地址: `{_ent_src['enterprise_address_col']}`")
                else:
                    st.caption("⚠️ 请先在步骤1中配置企业表及其字段映射")

                # 目标向量表状态
                ent_vec_count = vector_store.get_vector_count(ent_vec_table) if ent_vec_exists else 0
                if ent_vec_exists and ent_vec_count > 0:
                    st.markdown(f'<div style="text-align: center; font-size: 12px; color: {Colors.SUCCESS}; margin-bottom: 8px;">✅ 目标表 <code>{ent_vec_table}</code> 已有 {ent_vec_count:,} 条向量数据</div>', unsafe_allow_html=True)
                elif ent_vec_exists:
                    st.markdown(f'<div style="text-align: center; font-size: 12px; color: {Colors.WARNING}; margin-bottom: 8px;">⚠️ 目标表 <code>{ent_vec_table}</code> 已创建，尚无数据</div>', unsafe_allow_html=True)
                else:
                    st.markdown(f'<div style="text-align: center; font-size: 12px; color: {Colors.WARNING}; margin-bottom: 8px;">⚠️ 目标表 <code>{ent_vec_table}</code> 未创建</div>', unsafe_allow_html=True)

                _ent_btn_disabled = not db_ready or not _ent_table_ok
                _ent_btn_help = "请先在步骤1中配置企业表及字段" if not _ent_table_ok else "开始向量化"
                if st.button("开始企业表向量化", use_container_width=True, key='vec_enterprise_btn',
                            type="primary", disabled=_ent_btn_disabled, help=_ent_btn_help):
                    _start_vectorization('enterprise', batch_size, vec_device, vec_mode)
                    st.rerun()

        with vec_col2:
            with st.container(border=True):
                st.markdown(
                    f'<div style="text-align: center; padding: 8px 0 4px 0;">'
                    f'<div style="font-size: 28px; margin-bottom: 8px;">📍</div>'
                    f'<div style="font-size: 15px; font-weight: {Typography.WEIGHT_SEMIBOLD}; color: {Colors.TEXT_PRIMARY};">标准地址表向量化</div>'
                    f'</div>',
                    unsafe_allow_html=True
                )
                # 数据源信息
                if _std_table_ok:
                    st.caption(f"源表: **{_ent_src['standard_table']}** | 编码: `{_ent_src['standard_id_col']}` | 地址: `{_ent_src['standard_address_col']}` | 房号: `{_ent_src['standard_room_col']}`")
                else:
                    st.caption("⚠️ 请先在步骤1中配置标准地址表及其字段映射")

                # 目标向量表状态
                std_vec_count = vector_store.get_vector_count(std_vec_table) if std_vec_exists else 0
                if std_vec_exists and std_vec_count > 0:
                    st.markdown(f'<div style="text-align: center; font-size: 12px; color: {Colors.SUCCESS}; margin-bottom: 8px;">✅ 目标表 <code>{std_vec_table}</code> 已有 {std_vec_count:,} 条向量数据</div>', unsafe_allow_html=True)
                elif std_vec_exists:
                    st.markdown(f'<div style="text-align: center; font-size: 12px; color: {Colors.WARNING}; margin-bottom: 8px;">⚠️ 目标表 <code>{std_vec_table}</code> 已创建，尚无数据</div>', unsafe_allow_html=True)
                else:
                    st.markdown(f'<div style="text-align: center; font-size: 12px; color: {Colors.WARNING}; margin-bottom: 8px;">⚠️ 目标表 <code>{std_vec_table}</code> 未创建</div>', unsafe_allow_html=True)

                _std_btn_disabled = not db_ready or not _std_table_ok
                _std_btn_help = "请先在步骤1中配置标准地址表及字段" if not _std_table_ok else "开始向量化"
                if st.button("开始标准地址表向量化", use_container_width=True, key='vec_standard_btn',
                            type="primary", disabled=_std_btn_disabled, help=_std_btn_help):
                    _start_vectorization('standard', batch_size, vec_device, vec_mode)
                    st.rerun()

    st.divider()

    # ========== 步骤3：向量索引管理 ==========
    st.markdown('<div class="vec-module-title"><span class="vec-step-num">3</span> 向量索引管理</div>', unsafe_allow_html=True)

    # 动态获取所有有数据的向量表
    all_vector_tables = list(get_cached_vector_tables(
        db_config['host'], db_config['port'], db_config['dbname'],
        db_config['user'], db_config['password'], db_config['schema']
    )) if db_ready else []
    index_vec_tables = {}
    for vt in all_vector_tables:
        cnt = vector_store.get_vector_count(vt)
        if cnt > 0:
            # 自动生成索引名：表名 + _idx
            idx_name = f"idx_{vt}"
            index_vec_tables[vt] = (vt, idx_name)

    if not index_vec_tables:
        st.info("暂无已向量化的数据表，请先执行向量化")
    else:
        idx_col1, idx_col2 = st.columns([1, 1])
        with idx_col1:
            selected_label = st.selectbox("选择向量表", list(index_vec_tables.keys()), key='index_vec_table_selector')
        selected_table, selected_index = index_vec_tables[selected_label]
        row_count = vector_store.get_vector_count(selected_table)

        with idx_col2:
            st.markdown(f'<div style="padding-top: 32px; color: {Colors.TEXT_SECONDARY}; font-size: 14px;">数据量: {row_count:,} 条</div>', unsafe_allow_html=True)

        index_type = st.selectbox("索引类型", ['ivfflat', 'hnsw'], key='index_type_selector')

        # 自动计算默认参数
        if row_count <= 1_000_000:
            auto_lists = max(100, min(4000, row_count // 1000))
        else:
            auto_lists = max(100, min(4000, int(row_count ** 0.5)))

        maintenance_work_mem = st.text_input("maintenance_work_mem", value="1GB",
                                             help="索引创建时的维护内存，如 1GB、512MB")

        if index_type == 'ivfflat':
            lists = st.number_input("lists 参数", value=auto_lists, min_value=10, max_value=10000,
                                    help=f"自动计算值: {auto_lists}（基于 {row_count:,} 条数据）")
            m = None
            ef_construction = None
        else:
            lists = None
            m = st.number_input("m 参数", value=16, min_value=2, max_value=100,
                                help="连接数，默认16，值越大召回率越高但构建越慢")
            ef_construction = st.number_input("ef_construction 参数", value=200, min_value=40, max_value=2000,
                                              help="构建时搜索深度，默认200，值越大召回率越高但构建越慢")

        index_exists = vector_store.check_index_exists(selected_table, selected_index)

        idx_btn_col1, idx_btn_col2 = st.columns([1, 1])
        with idx_btn_col1:
            if index_exists:
                if st.button("删除现有索引", key='drop_index_btn'):
                    if vector_store.drop_vector_index(selected_index):
                        st.success(f"索引 {selected_index} 已删除")
                        st.rerun()
            else:
                st.markdown(f'<div style="color: {Colors.TEXT_MUTED}; font-size: 13px; padding-top: 8px;">索引 {selected_index} 不存在</div>', unsafe_allow_html=True)

        with idx_btn_col2:
            if st.button("创建索引", key='create_index_btn', type="primary"):
                if index_exists:
                    st.warning("索引已存在，请先删除再创建")
                else:
                    start_time = time.time()
                    start_datetime = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
                    st.info(f"⏱ 开始时间: {start_datetime}")
                    with st.spinner("正在创建索引..."):
                        success = vector_store.create_vector_index(
                            table_name=selected_table,
                            index_name=selected_index,
                            index_type=index_type,
                            lists=lists,
                            m=m,
                            ef_construction=ef_construction,
                            maintenance_work_mem=maintenance_work_mem
                        )
                    end_datetime = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
                    execution_time = time.time() - start_time

                    if success:
                        st.success(f"索引 {selected_index} 创建成功")
                        st.text(f"开始时间: {start_datetime}")
                        st.text(f"结束时间: {end_datetime}")
                        st.text(f"执行耗时: {format_time(execution_time)}")
                    else:
                        st.error("索引创建失败，请查看日志")

    # 注：db_conn 走缓存（_get_cached_db_connection），不在此关闭，由 TTL 自然过期
