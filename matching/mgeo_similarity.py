"""
MGeo地址相似度匹配模块
========================

独立于粗召回和MGeo精确匹配的地址相似度匹配功能。
直接调用模型 iic/mgeo_geographic_entity_alignment_chinese_base 对地址对进行匹配。

核心功能：
    1. 支持文件输入（Excel/CSV）和数据库表输入
    2. 对地址字段A和地址字段B逐行进行相似度匹配
    3. 输出exact_match、partial_match、not_match三个匹配概率
    4. 支持数据库表输入时生成_mgeo副本表

匹配逻辑：
    - 每行数据中地址A和地址B组成一个地址对
    - 模型返回三个概率: exact_match(索引0)、not_match(索引1)、partial_match(索引2)
    - 三个概率值四舍五入保留两位小数后，取最大值对应的状态作为匹配结果：
      exact_match 最大 → 精确匹配
      partial_match 最大 → 部分匹配
      not_match 最大 → 不匹配

性能优化：
    - 使用 predict_optimized 替代 predict，减少内存占用和返回数据量
    - 分块预测（CHUNK_SIZE=5000），每块预测完立即更新进度
    - 数据库输入使用服务端游标分批fetch，避免fetchall OOM
    - 数据库输入边预测边写入结果表，不累积全量结果在内存中
"""

import time
import threading
import pandas as pd
from model.mgeo_model import MGeoModel
from config import Config
from utils.logger import logger
from matching.utils import determine_match_status

# 分块大小：每处理一个chunk更新一次进度，数据库输入时每chunk写入一次DB
CHUNK_SIZE = 5000


class MGeoSimilarityMatcher:
    """
    MGeo地址相似度匹配器

    独立的地址相似度匹配功能，直接对地址对进行匹配，
    不依赖向量召回流程。

    Attributes:
        device: 运行设备 ('cuda' 或 'cpu')
        model: MGeoModel 对象
        is_running: 是否正在运行
        progress: 进度(0-1)
        processed_count: 已处理数量
        total_count: 总数量
        speed: 处理速度(条/秒)
        remaining_time: 预计剩余时间(秒)
        status_message: 状态消息
        error_message: 错误信息
    """

    def __init__(self, device=None):
        """
        初始化MGeo地址相似度匹配器

        Args:
            device: 运行设备 ('cuda' 或 'cpu')
        """
        self.device = device or Config.DEVICE
        self.model = None
        self.is_running = False
        self.progress = 0.0
        self.processed_count = 0
        self.total_count = 0
        self.speed = 0.0
        self.remaining_time = 0.0
        self.status_message = ''
        self.error_message = ''
        self._lock = threading.Lock()
        self.completed = False
        self.completion_success = False
        self.completion_message = ''
        self.completion_results = None
        self.completion_end_time = None
        self.completion_copy_table = ''
        self.completion_source_table = ''
        self.completion_result_count = 0

    def _load_model(self):
        """
        延迟加载MGeo模型（在后台线程中调用）

        Returns:
            bool: 加载成功返回 True
        """
        if self.model is None:
            logger.info("[MGeo相似度匹配] 加载MGeo模型...")
            # 使用全局缓存的模型实例，避免每次匹配都重新加载（5-15秒/次）
            from app_common import get_cached_mgeo_model
            self.model = get_cached_mgeo_model(self.device)
            logger.info("[MGeo相似度匹配] MGeo模型加载完成")
        return True

    @staticmethod
    def _read_csv_auto_encoding(file_path):
        """
        自动检测编码读取CSV文件

        依次尝试常见中文编码：utf-8-sig, utf-8, gbk, gb2312, gb18030, latin1

        Args:
            file_path: CSV文件路径

        Returns:
            DataFrame: 读取的数据帧
        """
        encodings = ['utf-8-sig', 'utf-8', 'gbk', 'gb2312', 'gb18030', 'latin1']
        for encoding in encodings:
            try:
                df = pd.read_csv(file_path, encoding=encoding)
                logger.info(f"[MGeo相似度匹配] CSV文件使用编码: {encoding}")
                return df
            except UnicodeDecodeError:
                continue
            except Exception:
                continue
        raise ValueError(f"无法识别CSV文件编码，请将文件转换为UTF-8编码后重试: {file_path}")

    def get_status(self):
        """
        获取当前匹配状态（线程安全）

        Returns:
            dict: 状态信息字典
        """
        with self._lock:
            return {
                'is_running': self.is_running,
                'progress': self.progress,
                'processed_count': self.processed_count,
                'total_count': self.total_count,
                'speed': self.speed,
                'remaining_time': self.remaining_time,
                'status_message': self.status_message,
                'error_message': self.error_message,
                'completed': self.completed,
                'completion_success': self.completion_success,
                'completion_message': self.completion_message,
                'completion_results': self.completion_results,
                'completion_end_time': self.completion_end_time,
                'completion_copy_table': self.completion_copy_table,
                'completion_source_table': self.completion_source_table,
                'completion_result_count': self.completion_result_count,
            }

    def _update_status(self, **kwargs):
        """
        更新匹配状态（线程安全）

        Args:
            **kwargs: 状态键值对
        """
        with self._lock:
            for key, value in kwargs.items():
                if hasattr(self, key):
                    setattr(self, key, value)

    def stop(self):
        """停止匹配任务"""
        self._update_status(is_running=False)
        logger.info("[MGeo相似度匹配] 用户停止了匹配")

    def _build_result(self, addr_a, addr_b, identifier, pred, extra_value=None):
        """构建单条匹配结果字典"""
        # 匹配状态判断：统一使用 matching.utils.determine_match_status
        # 默认 round_scores=True（先 round(2) 再比较），保持本模块原行为
        match_status = determine_match_status(
            pred['exact_match'], pred['partial_match'], pred['not_match']
        )
        return {
            'address_a': addr_a,
            'address_b': addr_b,
            'identifier': identifier or None,
            'extra_col': extra_value,
            'exact_match': pred['exact_match'],
            'partial_match': pred['partial_match'],
            'not_match': pred['not_match'],
            'match_status': match_status
        }

    def _build_empty_result(self, addr_a, addr_b, identifier, extra_value=None):
        """构建空地址行的不匹配结果"""
        return {
            'address_a': addr_a,
            'address_b': addr_b,
            'identifier': identifier or None,
            'extra_col': extra_value,
            'exact_match': 0.0,
            'partial_match': 0.0,
            'not_match': 1.0,
            'match_status': '不匹配'
        }

    def match_from_dataframe(self, df, address_a_col, address_b_col, id_col=None, extra_col=None, batch_size=None):
        """
        从DataFrame进行MGeo地址相似度匹配（分块预测，支持进度更新）

        性能优化：
            1. 使用 predict_optimized 替代 predict，减少内存占用
            2. 分块预测（CHUNK_SIZE），每块预测完立即更新进度
            3. 用向量化操作替代全量 list 拷贝，减少内存峰值

        Args:
            df: 包含地址数据的DataFrame
            address_a_col: 地址A字段列名
            address_b_col: 地址B字段列名
            id_col: 可选的标识字段列名
            extra_col: 可选的其他附加字段列名
            batch_size: 模型批处理大小，默认None（由模型自动选择）

        Returns:
            list: 匹配结果列表
        """
        self._load_model()

        addr_a_series = df[address_a_col].fillna('').astype(str)
        addr_b_series = df[address_b_col].fillna('').astype(str)
        total = len(df)

        if id_col and id_col in df.columns:
            id_series = df[id_col].fillna('').astype(str)
        else:
            id_series = pd.Series('', index=df.index)

        if extra_col and extra_col in df.columns:
            extra_series = df[extra_col].fillna('').astype(str)
        else:
            extra_series = pd.Series([None] * total, index=df.index)

        # 向量化空值检测
        valid_mask = addr_a_series.str.strip().str.len().gt(0) & addr_b_series.str.strip().str.len().gt(0)
        valid_idx = valid_mask[valid_mask].index.tolist()

        self._update_status(
            is_running=True,
            total_count=total,
            processed_count=0,
            progress=0.0,
            status_message='正在执行MGeo相似度匹配...'
        )

        results = [None] * total

        # 空地址行直接标记为不匹配
        for idx in valid_mask[~valid_mask].index.tolist():
            results[idx] = self._build_empty_result(
                addr_a_series.iat[idx], addr_b_series.iat[idx], id_series.iat[idx],
                extra_value=extra_series.iat[idx]
            )

        start_time = time.time()

        if valid_idx:
            # 分块预测，每块处理完后更新进度
            for chunk_start in range(0, len(valid_idx), CHUNK_SIZE):
                if not self.is_running:
                    logger.info("[MGeo相似度匹配] 用户停止了匹配")
                    break

                chunk_valid_idx = valid_idx[chunk_start:chunk_start + CHUNK_SIZE]
                chunk_pairs = [
                    (addr_a_series.iat[i], addr_b_series.iat[i])
                    for i in chunk_valid_idx
                ]

                try:
                    predictions = self.model.predict_optimized(chunk_pairs)
                except Exception as e:
                    logger.error(f"[MGeo相似度匹配] 分块预测失败: {str(e)}")
                    for i in chunk_valid_idx:
                        results[i] = self._build_empty_result(
                            addr_a_series.iat[i], addr_b_series.iat[i], id_series.iat[i],
                            extra_value=extra_series.iat[i]
                        )
                    continue

                for pair_idx, result_idx in enumerate(chunk_valid_idx):
                    results[result_idx] = self._build_result(
                        addr_a_series.iat[result_idx],
                        addr_b_series.iat[result_idx],
                        id_series.iat[result_idx],
                        predictions[pair_idx],
                        extra_value=extra_series.iat[result_idx]
                    )

                # 更新进度
                processed_count = min(chunk_start + CHUNK_SIZE, len(valid_idx))
                # 将有效行的处理进度映射到总进度
                overall_progress = processed_count / len(valid_idx) if valid_idx else 1.0
                elapsed = time.time() - start_time
                speed = processed_count / elapsed if elapsed > 0 else 0
                remaining = (len(valid_idx) - processed_count) / speed if speed > 0 else 0

                self._update_status(
                    processed_count=processed_count,
                    progress=overall_progress,
                    speed=speed,
                    remaining_time=remaining
                )

                del chunk_pairs, predictions

        elapsed = time.time() - start_time
        speed = total / elapsed if elapsed > 0 else 0

        # 注意：不在此处设置 is_running=False，由 run_mgeo_similarity_async 统一管理完成状态
        self._update_status(
            progress=1.0,
            processed_count=total,
            speed=speed,
            remaining_time=0,
            status_message='MGeo相似度匹配预测完成，正在写入结果...'
        )

        logger.info(f"[MGeo相似度匹配] 完成，共处理 {total} 条记录，耗时 {elapsed:.2f}s，速度 {speed:.1f}条/秒")
        return results

    def match_from_file(self, file_path, address_a_col, address_b_col, id_col=None, extra_col=None, batch_size=None):
        """
        从文件（Excel/CSV）进行MGeo地址相似度匹配

        Args:
            file_path: 文件路径
            address_a_col: 地址A字段列名
            address_b_col: 地址B字段列名
            id_col: 可选的标识字段列名
            extra_col: 可选的其他附加字段列名
            batch_size: 模型批处理大小

        Returns:
            list: 匹配结果列表
        """
        if file_path.endswith('.csv'):
            df = self._read_csv_auto_encoding(file_path)
        elif file_path.endswith(('.xlsx', '.xls')):
            df = pd.read_excel(file_path)
        else:
            raise ValueError(f"不支持的文件格式: {file_path}，仅支持CSV和Excel文件")

        if address_a_col not in df.columns:
            raise ValueError(f"文件中未找到地址A字段: {address_a_col}")
        if address_b_col not in df.columns:
            raise ValueError(f"文件中未找到地址B字段: {address_b_col}")
        if id_col and id_col not in df.columns:
            raise ValueError(f"文件中未找到标识字段: {id_col}")
        if extra_col and extra_col not in df.columns:
            raise ValueError(f"文件中未找到其他字段: {extra_col}")

        return self.match_from_dataframe(df, address_a_col, address_b_col, id_col, extra_col, batch_size)

    def match_from_db_streaming(self, db_conn, table_name, address_a_col, address_b_col,
                                 id_col=None, extra_col=None, data_loader=None, result_table_name=None):
        """
        从数据库表流式进行MGeo地址相似度匹配（支持千万级数据）

        使用独立连接的服务端游标分批fetch，每批预测后立即写入结果表，避免全量加载到内存。
        查询连接与写入连接隔离，避免写入操作的commit破坏服务端游标事务。

        Args:
            db_conn: 数据库连接对象（用于写入结果）
            table_name: 表名
            address_a_col: 地址A字段名
            address_b_col: 地址B字段名
            id_col: 可选的标识字段名
            extra_col: 可选的其他附加字段名
            data_loader: DataLoader实例（用于写入结果）
            result_table_name: 结果表名，默认使用 Config.MGEO_SIMILARITY_RESULTS_TABLE

        Returns:
            int: 匹配结果总数
        """
        from database.connection import quote_identifier
        import psycopg2.extras

        self._load_model()

        # 先获取总行数（用写入连接查询）
        count_sql = f"SELECT COUNT(*) as cnt FROM {quote_identifier(table_name)}"
        count_cursor = db_conn.execute(count_sql)
        if not count_cursor:
            raise ValueError(f"无法查询表: {table_name}")
        total = count_cursor.fetchone()['cnt']

        if total == 0:
            self._update_status(
                is_running=False,
                total_count=0,
                processed_count=0,
                progress=1.0,
                status_message='表中无数据'
            )
            return 0

        self._update_status(
            is_running=True,
            total_count=total,
            processed_count=0,
            progress=0.0,
            status_message='正在执行MGeo相似度匹配...'
        )

        # 构建查询SQL，只选需要的列
        cols = [quote_identifier(address_a_col), quote_identifier(address_b_col)]
        if id_col:
            cols.append(quote_identifier(id_col))
        if extra_col:
            cols.append(quote_identifier(extra_col))
        cols_sql = ', '.join(cols)
        query_sql = f"SELECT {cols_sql} FROM {quote_identifier(table_name)}"

        # 使用独立连接创建服务端游标，与写入连接完全隔离
        # 这样写入操作的commit不会破坏服务端游标所在的事务
        read_conn = psycopg2.connect(
            host=db_conn.host,
            port=db_conn.port,
            dbname=db_conn.dbname,
            user=db_conn.user,
            password=db_conn.password,
            cursor_factory=psycopg2.extras.RealDictCursor
        )
        # 设置 search_path 与写入连接一致
        if db_conn.schema and db_conn.schema != 'public':
            read_conn.autocommit = True
            with read_conn.cursor() as cur:
                cur.execute(f'SET search_path TO {quote_identifier(db_conn.schema)}, public')
            read_conn.autocommit = False

        fetch_size = CHUNK_SIZE

        try:
            # 创建服务端游标（named cursor 自动启用服务端游标）
            cursor_name = f"mgeo_sim_cursor_{id(self)}"
            server_cursor = read_conn.cursor(name=cursor_name)
            server_cursor.itersize = fetch_size
            server_cursor.execute(query_sql)

            start_time = time.time()
            processed_count = 0
            total_result_count = 0

            while True:
                if not self.is_running:
                    logger.info("[MGeo相似度匹配] 用户停止了匹配")
                    break

                rows = server_cursor.fetchmany(fetch_size)
                if not rows:
                    break

                chunk_df = pd.DataFrame(rows)
                chunk_total = len(chunk_df)

                # 构建地址对
                addr_a_series = chunk_df[address_a_col].fillna('').astype(str)
                addr_b_series = chunk_df[address_b_col].fillna('').astype(str)
                if id_col and id_col in chunk_df.columns:
                    id_series = chunk_df[id_col].fillna('').astype(str)
                else:
                    id_series = pd.Series([''] * chunk_total, index=chunk_df.index)
                if extra_col and extra_col in chunk_df.columns:
                    extra_series = chunk_df[extra_col].fillna('').astype(str)
                else:
                    extra_series = pd.Series([None] * chunk_total, index=chunk_df.index)

                # 分离有效和无效地址对
                valid_mask = addr_a_series.str.strip().str.len().gt(0) & addr_b_series.str.strip().str.len().gt(0)
                chunk_results = []

                # 无效地址行
                for idx in valid_mask[~valid_mask].index.tolist():
                    chunk_results.append(self._build_empty_result(
                        addr_a_series.iat[idx], addr_b_series.iat[idx], id_series.iat[idx],
                        extra_value=extra_series.iat[idx]
                    ))

                # 有效地址行批量预测
                if valid_mask.any():
                    valid_idx = valid_mask[valid_mask].index.tolist()
                    chunk_pairs = [
                        (addr_a_series.iat[i], addr_b_series.iat[i])
                        for i in valid_idx
                    ]

                    try:
                        predictions = self.model.predict_optimized(chunk_pairs)
                    except Exception as e:
                        logger.error(f"[MGeo相似度匹配] 分块预测失败: {str(e)}")
                        for i in valid_idx:
                            chunk_results.append(self._build_empty_result(
                                addr_a_series.iat[i], addr_b_series.iat[i], id_series.iat[i],
                                extra_value=extra_series.iat[i]
                            ))
                        predictions = None

                    if predictions:
                        for pair_idx, result_idx in enumerate(valid_idx):
                            chunk_results.append(self._build_result(
                                addr_a_series.iat[result_idx],
                                addr_b_series.iat[result_idx],
                                id_series.iat[result_idx],
                                predictions[pair_idx],
                                extra_value=extra_series.iat[result_idx]
                            ))

                    del chunk_pairs
                    if predictions is not None:
                        del predictions

                # 立即写入DB（使用写入连接，不影响读取连接的服务端游标）
                if data_loader and chunk_results:
                    data_loader.insert_mgeo_similarity_results(chunk_results, table_name=result_table_name)

                total_result_count += len(chunk_results)
                processed_count += chunk_total

                # 更新进度
                elapsed = time.time() - start_time
                speed = processed_count / elapsed if elapsed > 0 else 0
                remaining = (total - processed_count) / speed if speed > 0 else 0

                self._update_status(
                    processed_count=processed_count,
                    progress=processed_count / total,
                    speed=speed,
                    remaining_time=remaining
                )

                del chunk_df, chunk_results

            # 关闭服务端游标和读取连接
            server_cursor.close()
            read_conn.close()

            elapsed = time.time() - start_time
            speed = total / elapsed if elapsed > 0 else 0

            # 注意：不在此处设置 is_running=False，由 run_mgeo_similarity_async 统一管理完成状态
            # 否则后续的 create_mgeo_copy_table 期间 fragment 不会刷新，completed 状态无法同步
            self._update_status(
                progress=1.0,
                processed_count=total,
                speed=speed,
                remaining_time=0,
                status_message='MGeo相似度匹配预测完成，正在写入结果...'
            )

            logger.info(f"[MGeo相似度匹配] 完成，共处理 {total} 条记录，耗时 {elapsed:.2f}s，速度 {speed:.1f}条/秒")
            return total_result_count

        except Exception as e:
            # 确保读取连接关闭
            try:
                read_conn.close()
            except:
                pass
            raise e


def run_mgeo_similarity_async(matcher, data_source, address_a_col, address_b_col,
                               id_col=None, extra_col=None, db_conn=None, table_name=None, result_table_name=None,
                               completed_callback=None):
    """
    异步执行MGeo地址相似度匹配

    Args:
        matcher: MGeoSimilarityMatcher 对象
        data_source: 数据源（DataFrame 或文件路径）
        address_a_col: 地址A字段名
        address_b_col: 地址B字段名
        id_col: 可选的标识字段名
        extra_col: 可选的其他附加字段名
        db_conn: 数据库连接对象（库表输入时需要）
        table_name: 数据库表名（库表输入时需要）
        result_table_name: 结果表名
        completed_callback: 完成回调函数

    Returns:
        threading.Thread: 后台线程对象
    """
    from database.data_loader import DataLoader

    def task_func():
        try:
            matcher._update_status(is_running=True, status_message='正在加载数据...')

            copy_table = ''
            source_table = table_name or ''
            result_count = 0

            # ===== 数据库表输入：流式处理，边预测边写入 =====
            if db_conn and table_name:
                data_loader = DataLoader(db_conn)
                target_table = result_table_name or Config.MGEO_SIMILARITY_RESULTS_TABLE

                # 先创建并清空结果表
                data_loader.create_mgeo_similarity_table(target_table)
                data_loader.truncate_mgeo_similarity_table(target_table)

                # 流式匹配：服务端游标分批fetch + 边预测边写入
                result_count = matcher.match_from_db_streaming(
                    db_conn, table_name, address_a_col, address_b_col, id_col, extra_col,
                    data_loader=data_loader, result_table_name=target_table
                )

                logger.info(f"[MGeo相似度匹配] 结果已写入 {target_table}，共 {result_count} 条")

                # 生成_mgeo副本表
                if table_name and result_count > 0:
                    matcher._update_status(status_message='正在生成_mgeo副本表...')
                    copy_table = data_loader.create_mgeo_copy_table(
                        table_name, address_a_col, address_b_col,
                        result_table=target_table
                    )
                    if copy_table:
                        logger.info(f"[MGeo相似度匹配] 副本表 {copy_table} 创建成功")
                    else:
                        logger.warning("[MGeo相似度匹配] 副本表创建失败")

            # ===== 文件输入：全量预测，结果保存在内存 =====
            else:
                if isinstance(data_source, pd.DataFrame):
                    results = matcher.match_from_dataframe(data_source, address_a_col, address_b_col, id_col, extra_col)
                elif isinstance(data_source, str):
                    results = matcher.match_from_file(data_source, address_a_col, address_b_col, id_col, extra_col)
                else:
                    raise ValueError("不支持的数据源类型")

                if not results:
                    with matcher._lock:
                        matcher.is_running = False
                        matcher.status_message = '无匹配结果'
                        matcher.error_message = '没有可匹配的数据'
                        matcher.completed = True
                        matcher.completion_success = False
                        matcher.completion_message = '没有可匹配的数据'
                    if completed_callback:
                        completed_callback(False, '没有可匹配的数据', None)
                    return

                result_count = len(results)

                # 文件输入的结果写入DB（如果有db_conn）
                if db_conn:
                    matcher._update_status(
                        is_running=True,
                        status_message='正在写入匹配结果到数据库...'
                    )

                    data_loader = DataLoader(db_conn)
                    target_table = result_table_name or Config.MGEO_SIMILARITY_RESULTS_TABLE

                    data_loader.create_mgeo_similarity_table(target_table)
                    data_loader.truncate_mgeo_similarity_table(target_table)

                    # 分批写入
                    write_batch = 5000
                    for i in range(0, len(results), write_batch):
                        batch = results[i:i + write_batch]
                        data_loader.insert_mgeo_similarity_results(batch, target_table)

                    logger.info(f"[MGeo相似度匹配] 结果已写入 {target_table}，共 {len(results)} 条")

                # 文件输入：保存结果到内存（供下载）
                with matcher._lock:
                    matcher.completion_results = results

            # 原子设置所有完成状态字段
            end_time = time.time()
            with matcher._lock:
                matcher.is_running = False
                matcher.progress = 1.0
                matcher.status_message = 'MGeo相似度匹配完成'
                matcher.completed = True
                matcher.completion_success = True
                matcher.completion_message = '匹配完成'
                matcher.completion_end_time = end_time
                matcher.completion_copy_table = copy_table
                matcher.completion_source_table = source_table
                matcher.completion_result_count = result_count

            if completed_callback:
                completed_callback(True, '匹配完成', None)

        except Exception as e:
            logger.error(f"[MGeo相似度匹配] 失败: {str(e)}")
            import traceback
            logger.error(f"[MGeo相似度匹配] 详细堆栈: {traceback.format_exc()}")
            end_time = time.time()
            with matcher._lock:
                matcher.is_running = False
                matcher.error_message = str(e)
                matcher.status_message = 'MGeo相似度匹配失败'
                matcher.completed = True
                matcher.completion_success = False
                matcher.completion_message = str(e)
                matcher.completion_end_time = end_time
            if completed_callback:
                completed_callback(False, str(e), None)

    thread = threading.Thread(target=task_func, daemon=True)
    thread.start()
    return thread
