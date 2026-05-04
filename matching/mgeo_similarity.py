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
    - 模型返回三个概率: exact_match, partial_match, not_match
    - 三个概率值中取最大值对应的状态作为匹配结果：
      exact_match最大 → 精确匹配
      partial_match最大 → 部分匹配
      not_match最大 → 不匹配
"""

import time
import threading
import pandas as pd
from model.mgeo_model import MGeoModel
from config import Config
from utils.logger import logger


def determine_similarity_status(exact_match, partial_match, not_match):
    """
    根据exact_match、partial_match、not_match三个概率值判断匹配状态

    判断逻辑：三个概率值中哪个最大，状态就是哪个
        - exact_match最大 → 精确匹配
        - partial_match最大 → 部分匹配
        - not_match最大 → 不匹配

    Args:
        exact_match: 精确匹配概率
        partial_match: 部分匹配概率
        not_match: 不匹配概率

    Returns:
        str: 匹配状态（精确匹配/部分匹配/不匹配）
    """
    max_val = max(exact_match, partial_match, not_match)
    if exact_match == max_val:
        return '精确匹配'
    elif partial_match == max_val:
        return '部分匹配'
    else:
        return '不匹配'


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

    def _load_model(self):
        """
        延迟加载MGeo模型（在后台线程中调用）

        Returns:
            bool: 加载成功返回 True
        """
        if self.model is None:
            logger.info("[MGeo相似度匹配] 加载MGeo模型...")
            self.model = MGeoModel(device=self.device)
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
                'completion_source_table': self.completion_source_table
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

    def match_from_dataframe(self, df, address_a_col, address_b_col, batch_size=None):
        """
        从DataFrame进行MGeo地址相似度匹配

        性能优化：
            1. batch_size默认由模型根据设备自动选择（GPU=128, CPU=64）
            2. 先过滤空地址，收集所有有效地址对后一次性批量预测
            3. 减少多次小批量调用带来的GPU空闲开销

        Args:
            df: 包含地址数据的DataFrame
            address_a_col: 地址A字段列名
            address_b_col: 地址B字段列名
            batch_size: 模型批处理大小，默认None（由模型自动选择）

        Returns:
            list: 匹配结果列表，每个元素包含 address_a, address_b, exact_match, partial_match, not_match, match_status
        """
        self._load_model()

        addresses_a = df[address_a_col].fillna('').astype(str).tolist()
        addresses_b = df[address_b_col].fillna('').astype(str).tolist()
        total = len(addresses_a)

        self._update_status(
            is_running=True,
            total_count=total,
            processed_count=0,
            progress=0.0,
            status_message='正在执行MGeo相似度匹配...'
        )

        results = [None] * total
        valid_pairs = []
        valid_indices = []

        for idx in range(total):
            a = addresses_a[idx]
            b = addresses_b[idx]
            if a.strip() and b.strip():
                valid_pairs.append((a, b))
                valid_indices.append(idx)
            else:
                results[idx] = {
                    'address_a': a,
                    'address_b': b,
                    'exact_match': 0.0,
                    'partial_match': 0.0,
                    'not_match': 1.0,
                    'match_status': '不匹配'
                }

        start_time = time.time()

        if valid_pairs:
            try:
                predictions = self.model.predict(valid_pairs, batch_size=batch_size)
            except Exception as e:
                logger.error(f"[MGeo相似度匹配] 批量预测失败: {str(e)}")
                for idx in valid_indices:
                    results[idx] = {
                        'address_a': addresses_a[idx],
                        'address_b': addresses_b[idx],
                        'exact_match': 0.0,
                        'partial_match': 0.0,
                        'not_match': 1.0,
                        'match_status': '不匹配'
                    }
                self._update_status(
                    is_running=False,
                    progress=1.0,
                    processed_count=total,
                    status_message='MGeo相似度匹配失败'
                )
                return results

            for pair_idx, result_idx in enumerate(valid_indices):
                pred = predictions[pair_idx]
                match_status = determine_similarity_status(
                    pred['exact_match'], pred['partial_match'], pred['not_match']
                )
                results[result_idx] = {
                    'address_a': addresses_a[result_idx],
                    'address_b': addresses_b[result_idx],
                    'exact_match': pred['exact_match'],
                    'partial_match': pred['partial_match'],
                    'not_match': pred['not_match'],
                    'match_status': match_status
                }

        elapsed = time.time() - start_time
        speed = total / elapsed if elapsed > 0 else 0

        self._update_status(
            is_running=False,
            progress=1.0,
            processed_count=total,
            speed=speed,
            remaining_time=0,
            status_message='MGeo相似度匹配完成'
        )

        logger.info(f"[MGeo相似度匹配] 完成，共处理 {total} 条记录，耗时 {elapsed:.2f}s，速度 {speed:.1f}条/秒")
        return results

    def match_from_file(self, file_path, address_a_col, address_b_col, batch_size=None):
        """
        从文件（Excel/CSV）进行MGeo地址相似度匹配

        Args:
            file_path: 文件路径
            address_a_col: 地址A字段列名
            address_b_col: 地址B字段列名
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

        return self.match_from_dataframe(df, address_a_col, address_b_col, batch_size)

    def match_from_db_table(self, db_conn, table_name, address_a_col, address_b_col, batch_size=None):
        """
        从数据库表进行MGeo地址相似度匹配

        Args:
            db_conn: 数据库连接对象
            table_name: 表名
            address_a_col: 地址A字段名
            address_b_col: 地址B字段名
            batch_size: 模型批处理大小

        Returns:
            list: 匹配结果列表
        """
        from database.data_loader import DataLoader

        data_loader = DataLoader(db_conn)

        sql = f"SELECT * FROM {table_name}"
        cursor = db_conn.execute(sql)
        if not cursor:
            raise ValueError(f"无法查询表: {table_name}")

        rows = cursor.fetchall()
        df = pd.DataFrame(rows)

        if address_a_col not in df.columns:
            raise ValueError(f"表中未找到地址A字段: {address_a_col}")
        if address_b_col not in df.columns:
            raise ValueError(f"表中未找到地址B字段: {address_b_col}")

        return self.match_from_dataframe(df, address_a_col, address_b_col, batch_size)


def run_mgeo_similarity_async(matcher, data_source, address_a_col, address_b_col,
                               db_conn=None, table_name=None, result_table_name=None,
                               completed_callback=None):
    """
    异步执行MGeo地址相似度匹配

    Args:
        matcher: MGeoSimilarityMatcher 对象
        data_source: 数据源（DataFrame 或文件路径）
        address_a_col: 地址A字段名
        address_b_col: 地址B字段名
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

            if isinstance(data_source, pd.DataFrame):
                results = matcher.match_from_dataframe(data_source, address_a_col, address_b_col)
            elif isinstance(data_source, str):
                results = matcher.match_from_file(data_source, address_a_col, address_b_col)
            else:
                raise ValueError("不支持的数据源类型")

            if not results:
                matcher._update_status(
                    is_running=False,
                    status_message='无匹配结果',
                    error_message='没有可匹配的数据'
                )
                with matcher._lock:
                    matcher.completed = True
                    matcher.completion_success = False
                    matcher.completion_message = '没有可匹配的数据'
                if completed_callback:
                    completed_callback(False, '没有可匹配的数据', None)
                return

            copy_table = ''
            source_table = table_name or ''

            if db_conn:
                data_loader = DataLoader(db_conn)
                target_table = result_table_name or Config.MGEO_SIMILARITY_RESULTS_TABLE

                data_loader.create_mgeo_similarity_table(target_table)
                data_loader.truncate_mgeo_similarity_table(target_table)

                batch_size = 100
                for i in range(0, len(results), batch_size):
                    batch = results[i:i + batch_size]
                    data_loader.insert_mgeo_similarity_results(batch, target_table)

                logger.info(f"[MGeo相似度匹配] 结果已写入 {target_table}，共 {len(results)} 条")

                if table_name:
                    matcher._update_status(status_message='正在生成_mgeo副本表...')
                    copy_table = data_loader.create_mgeo_copy_table(
                        table_name, address_a_col, address_b_col, results
                    )
                    if copy_table:
                        logger.info(f"[MGeo相似度匹配] 副本表 {copy_table} 创建成功")
                    else:
                        logger.warning("[MGeo相似度匹配] 副本表创建失败")

            end_time = time.time()
            matcher._update_status(
                is_running=False,
                progress=1.0,
                status_message='MGeo相似度匹配完成'
            )
            with matcher._lock:
                matcher.completed = True
                matcher.completion_success = True
                matcher.completion_message = '匹配完成'
                matcher.completion_results = results
                matcher.completion_end_time = end_time
                matcher.completion_copy_table = copy_table
                matcher.completion_source_table = source_table

            if completed_callback:
                completed_callback(True, '匹配完成', results)

        except Exception as e:
            logger.error(f"[MGeo相似度匹配] 失败: {str(e)}")
            import traceback
            logger.error(f"[MGeo相似度匹配] 详细堆栈: {traceback.format_exc()}")
            end_time = time.time()
            matcher._update_status(
                is_running=False,
                error_message=str(e),
                status_message='MGeo相似度匹配失败'
            )
            with matcher._lock:
                matcher.completed = True
                matcher.completion_success = False
                matcher.completion_message = str(e)
                matcher.completion_end_time = end_time
            if completed_callback:
                completed_callback(False, str(e), None)

    thread = threading.Thread(target=task_func, daemon=True)
    thread.start()
    return thread
