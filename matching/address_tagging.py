"""
MGeo门址地址结构化要素解析模块
================================

独立的地址结构化解析功能，直接调用模型对地址进行分词和要素提取。

核心功能：
    1. 支持文件输入（Excel/CSV）和数据库表输入
    2. 对地址字段逐行进行结构化解析
    3. 输出12级结构化要素：province, city, district, street, community,
       road, roadno, area, bldg, unit, floor, house
    4. 支持数据库表输入时生成结果表
"""

import time
import threading
import pandas as pd
from database.connection import quote_identifier
from model.address_tagging_model import (
    AddressTaggingModel, OUTPUT_FIELDS,
    OUTPUT_FIELDS_17, OUTPUT_FIELDS_17_2,
    OUTPUT_FIELD_LABELS, OUTPUT_FIELD_LABELS_17, OUTPUT_FIELD_LABELS_17_2
)
from config import Config
from utils.logger import logger


class AddressTaggingParser:
    """
    MGeo门址地址结构化要素解析器

    独立的地址结构化解析功能，直接对地址进行NER分词，
    支持12级或17级结构化输出。

    Attributes:
        device: 运行设备 ('cuda' 或 'cpu')
        mode: 输出模式 '12' 或 '17'
        model: AddressTaggingModel 对象
        is_running: 是否正在运行
        progress: 进度(0-1)
        processed_count: 已处理数量
        total_count: 总数量
        speed: 处理速度(条/秒)
        remaining_time: 预计剩余时间(秒)
        status_message: 状态消息
        error_message: 错误信息
    """

    def __init__(self, device=None, mode='12'):
        self.device = device or Config.DEVICE
        self.mode = mode
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

    @property
    def output_fields(self):
        """当前模式对应的输出字段列表"""
        if self.mode == '17_2':
            return OUTPUT_FIELDS_17_2
        elif self.mode == '17':
            return OUTPUT_FIELDS_17
        return OUTPUT_FIELDS

    @property
    def output_field_labels(self):
        """当前模式对应的输出字段标签"""
        if self.mode == '17_2':
            return OUTPUT_FIELD_LABELS_17_2
        elif self.mode == '17':
            return OUTPUT_FIELD_LABELS_17
        return OUTPUT_FIELD_LABELS

    @property
    def level_name(self):
        """当前模式的显示名称"""
        if self.mode == '17_2':
            return '17级（双字段）'
        elif self.mode == '17':
            return '17级'
        return '12级'

    def _load_model(self):
        if self.model is None:
            logger.info("[地址结构化解析] 加载地址要素解析模型...")
            self.model = AddressTaggingModel(device=self.device)
            logger.info("[地址结构化解析] 地址要素解析模型加载完成")
        return True

    @staticmethod
    def _read_csv_auto_encoding(file_path):
        encodings = ['utf-8-sig', 'utf-8', 'gbk', 'gb2312', 'gb18030', 'latin1']
        for encoding in encodings:
            try:
                df = pd.read_csv(file_path, encoding=encoding)
                logger.info(f"[地址结构化解析] CSV文件使用编码: {encoding}")
                return df
            except UnicodeDecodeError:
                continue
            except Exception:
                continue
        raise ValueError(f"无法识别CSV文件编码，请将文件转换为UTF-8编码后重试: {file_path}")

    def get_status(self):
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
        with self._lock:
            for key, value in kwargs.items():
                if hasattr(self, key):
                    setattr(self, key, value)

    def stop(self):
        self._update_status(is_running=False)
        logger.info("[地址结构化解析] 用户停止了解析")

    def parse_from_dataframe(self, df, address_col, batch_size=None, id_field=None):
        """
        从DataFrame进行地址结构化解析

        Args:
            df: 包含地址数据的DataFrame
            address_col: 地址字段列名
            batch_size: 模型批处理大小
            id_field: 标识字段列名（可选，仅17_2模式使用）

        Returns:
            list: 解析结果列表
        """
        self._load_model()

        addresses = df[address_col].fillna('').astype(str).tolist()
        total = len(addresses)
        fields = self.output_fields
        is_17 = (self.mode == '17')
        is_17_2 = (self.mode == '17_2')
        need_id_field = (is_17 or is_17_2)

        # 提取标识字段值
        id_values = None
        if need_id_field and id_field and id_field in df.columns:
            id_values = df[id_field].fillna('').astype(str).tolist()

        self._update_status(
            is_running=True,
            total_count=total,
            processed_count=0,
            progress=0.0,
            status_message=f'正在执行地址{self.level_name}结构化解析...'
        )

        start_time = time.time()

        try:
            if is_17_2:
                results = self.model.predict_17_2(addresses, batch_size=batch_size)
            elif self.mode == '17':
                results = self.model.predict_17(addresses, batch_size=batch_size)
            else:
                results = self.model.predict(addresses, batch_size=batch_size)
        except Exception as e:
            logger.error(f"[地址结构化解析] 批量预测失败: {str(e)}")
            self._update_status(
                is_running=False, progress=1.0, processed_count=total,
                status_message=f'地址{self.level_name}结构化解析失败'
            )
            empty = {field: '' for field in fields}
            return [{'original_address': a, **empty} for a in addresses]

        # 17/17_2模式：将 id_field 插入到结果最前面
        if need_id_field and id_values:
            for i, r in enumerate(results):
                r['_id_field'] = id_values[i] if i < len(id_values) else ''

        elapsed = time.time() - start_time
        speed = total / elapsed if elapsed > 0 else 0

        self._update_status(
            is_running=False, progress=1.0, processed_count=total,
            speed=speed, remaining_time=0,
            status_message=f'地址{self.level_name}结构化解析完成'
        )

        logger.info(f"[地址结构化解析] {self.level_name}完成，共处理 {total} 条记录，耗时 {elapsed:.2f}s，速度 {speed:.1f}条/秒")
        return results

    def parse_from_file(self, file_path, address_col, batch_size=None, id_field=None):
        if file_path.endswith('.csv'):
            df = self._read_csv_auto_encoding(file_path)
        elif file_path.endswith(('.xlsx', '.xls')):
            df = pd.read_excel(file_path)
        else:
            raise ValueError(f"不支持的文件格式: {file_path}，仅支持CSV和Excel文件")

        if address_col not in df.columns:
            raise ValueError(f"文件中未找到地址字段: {address_col}")

        return self.parse_from_dataframe(df, address_col, batch_size, id_field)

    def parse_from_db_table(self, db_conn, table_name, address_col, batch_size=None):
        from database.data_loader import DataLoader

        data_loader = DataLoader(db_conn)

        sql = f"SELECT * FROM {quote_identifier(table_name)}"
        cursor = db_conn.execute(sql)
        if not cursor:
            raise ValueError(f"无法查询表: {table_name}")

        rows = cursor.fetchall()
        df = pd.DataFrame(rows)

        if address_col not in df.columns:
            raise ValueError(f"表中未找到地址字段: {address_col}")

        return self.parse_from_dataframe(df, address_col, batch_size)

    def parse_from_db_streaming(self, db_conn, table_name, address_col,
                                 result_table_name, data_loader,
                                 db_batch_size=10000, id_field=None):
        """
        流式处理数据库表：分批读取→预测→写入结果表，避免全部加载到内存

        适用于百万级大表，每批只加载 db_batch_size 行到内存，
        预测完成后立即写入结果表并释放内存。

        Args:
            db_conn: 数据库连接（用于读取源表）
            table_name: 源表名
            address_col: 地址字段名
            result_table_name: 结果表名
            data_loader: DataLoader 实例（用于写入结果）
            db_batch_size: 每批从数据库读取的行数，默认10000
            id_field: 标识字段列名（可选，仅17_2模式使用）

        Returns:
            int: 总处理行数
        """
        self._load_model()
        fields = self.output_fields
        is_17 = (self.mode == '17')
        is_17_2 = (self.mode == '17_2')
        need_id_field = (is_17 or is_17_2)

        # 获取总行数
        count_sql = f"SELECT COUNT(*) as count FROM {quote_identifier(table_name)}"
        cursor = db_conn.execute(count_sql)
        if not cursor:
            raise ValueError(f"无法查询表行数: {table_name}")
        total = cursor.fetchone()['count']

        logger.info(f"[地址{self.level_name}结构化解析] 流式处理开始，总行数={total:,}, 每批={db_batch_size:,}")

        self._update_status(
            is_running=True, total_count=total, processed_count=0,
            progress=0.0, status_message=f'正在执行地址{self.level_name}结构化解析...'
        )

        start_time = time.time()
        processed = 0
        offset = 0

        while offset < total:
            if not self.is_running:
                logger.info(f"[地址{self.level_name}结构化解析] 用户停止，已处理 {processed:,} 行")
                break

            # 分批读取源表数据
            sql = f"SELECT * FROM {quote_identifier(table_name)} ORDER BY ctid LIMIT {db_batch_size} OFFSET {offset}"
            cursor = db_conn.execute(sql)
            if not cursor:
                break
            rows = cursor.fetchall()
            if not rows:
                break

            df = pd.DataFrame(rows)
            addresses = df[address_col].fillna('').astype(str).tolist()
            batch_count = len(addresses)

            # 提取标识字段值（17/17_2模式）
            id_values = None
            if need_id_field and id_field and id_field in df.columns:
                id_values = df[id_field].fillna('').astype(str).tolist()

            # 模型预测
            try:
                if is_17_2:
                    batch_results = self.model.predict_17_2(addresses)
                elif self.mode == '17':
                    batch_results = self.model.predict_17(addresses)
                else:
                    batch_results = self.model.predict(addresses)
            except Exception as e:
                logger.error(f"[地址{self.level_name}结构化解析] 批次预测失败 offset={offset}: {e}")
                batch_results = [{'original_address': a, **{f: '' for f in fields}} for a in addresses]

            # 17/17_2模式：将 id_field 插入到结果最前面
            if need_id_field and id_values:
                for i, r in enumerate(batch_results):
                    r['_id_field'] = id_values[i] if i < len(id_values) else ''

            # 立即写入结果表，不在内存中累积
            if is_17_2:
                inserted = data_loader.insert_address_tagging_17_2_results(batch_results, result_table_name)
            elif self.mode == '17':
                inserted = data_loader.insert_address_tagging_17_results(batch_results, result_table_name)
            else:
                inserted = data_loader.insert_address_tagging_results(batch_results, result_table_name)

            if inserted == 0 and batch_results:
                logger.error(f"[地址{self.level_name}结构化解析] 批次写入失败 offset={offset}, 行数={batch_count}")
                break

            processed += batch_count
            offset += db_batch_size

            # 更新进度
            elapsed = time.time() - start_time
            speed = processed / elapsed if elapsed > 0 else 0
            remaining = (total - processed) / speed if speed > 0 else 0

            self._update_status(
                processed_count=processed,
                progress=processed / total if total > 0 else 0,
                speed=speed,
                remaining_time=remaining,
                status_message=f'正在执行地址{self.level_name}结构化解析... ({processed:,}/{total:,})'
            )

            # 显式释放内存
            del df, addresses, batch_results

        elapsed = time.time() - start_time
        speed = processed / elapsed if elapsed > 0 else 0
        logger.info(f"[地址{self.level_name}结构化解析] 流式处理完成，共 {processed:,} 条，"
                   f"耗时 {elapsed:.2f}s，速度 {speed:.1f}条/秒")

        self._update_status(
            is_running=False, progress=1.0, processed_count=processed,
            speed=speed, remaining_time=0,
            status_message=f'地址{self.level_name}结构化解析完成'
        )

        return processed


def run_address_tagging_async(parser, data_source, address_col,
                               db_conn=None, table_name=None, result_table_name=None,
                               completed_callback=None, mode='12', id_field=None):
    """
    异步执行地址结构化解析

    文件/DataFrame模式：全量加载后批量处理
    数据库模式：流式分批读取→预测→写入，避免全部加载到内存

    Args:
        parser: AddressTaggingParser 对象
        data_source: 数据源（DataFrame、文件路径，数据库模式时为 None）
        address_col: 地址字段名
        db_conn: 数据库连接对象（库表输入时需要）
        table_name: 数据库表名（库表输入时需要）
        result_table_name: 结果表名
        completed_callback: 完成回调函数
        mode: 输出模式 '12' / '17' / '17_2'
        id_field: 标识字段列名（可选，仅17_2模式使用）

    Returns:
        threading.Thread: 后台线程对象
    """
    from database.data_loader import DataLoader

    is_17 = (mode == '17')
    is_17_2 = (mode == '17_2')
    is_db_mode = db_conn is not None and table_name is not None

    def task_func():
        copy_table = ''
        source_table = table_name or ''
        end_time = None
        result_count = 0

        try:
            parser._update_status(is_running=True, status_message='正在加载数据...')

            if is_db_mode:
                # ---- 数据库流式模式 ----
                parser._update_status(status_message='正在准备数据库流式处理...')
                data_loader = DataLoader(db_conn)

                if is_17_2:
                    target_table = result_table_name or Config.ADDRESS_TAGGING_17_2_RESULTS_TABLE
                    data_loader.create_address_tagging_17_2_table(target_table)
                    data_loader.truncate_address_tagging_17_2_table(target_table)
                elif is_17:
                    target_table = result_table_name or Config.ADDRESS_TAGGING_17_RESULTS_TABLE
                    data_loader.create_address_tagging_17_table(target_table)
                    data_loader.truncate_address_tagging_17_table(target_table)
                else:
                    target_table = result_table_name or Config.ADDRESS_TAGGING_RESULTS_TABLE
                    data_loader.create_address_tagging_table(target_table)
                    data_loader.truncate_address_tagging_table(target_table)

                # 流式处理：分批读取→预测→写入
                result_count = parser.parse_from_db_streaming(
                    db_conn=db_conn, table_name=table_name, address_col=address_col,
                    result_table_name=target_table, data_loader=data_loader,
                    id_field=id_field
                )

                # 使用 SQL JOIN 创建副本表
                parser._update_status(status_message='正在生成副本表...')
                if is_17_2:
                    copy_table = data_loader.create_tagging_17_2_copy_table_from_result(
                        table_name, address_col, target_table
                    )
                elif is_17:
                    copy_table = data_loader.create_tagging_17_copy_table_from_result(
                        table_name, address_col, target_table
                    )
                else:
                    copy_table = data_loader.create_tagging_copy_table_from_result(
                        table_name, address_col, target_table
                    )

                logger.info(f"[地址结构化解析] 流式处理完成，共 {result_count:,} 条，副本表={copy_table}")

            else:
                # ---- 文件/DataFrame 模式 ----
                if isinstance(data_source, pd.DataFrame):
                    results = parser.parse_from_dataframe(data_source, address_col, id_field=id_field)
                elif isinstance(data_source, str):
                    results = parser.parse_from_file(data_source, address_col, id_field=id_field)
                else:
                    raise ValueError("不支持的数据源类型")

                if not results:
                    parser._update_status(
                        is_running=False, status_message='无解析结果',
                        error_message='没有可解析的数据'
                    )
                    with parser._lock:
                        parser.completed = True
                        parser.completion_success = False
                        parser.completion_message = '没有可解析的数据'
                    if completed_callback:
                        completed_callback(False, '没有可解析的数据', None)
                    return

                result_count = len(results)

                if db_conn:
                    data_loader = DataLoader(db_conn)
                    if is_17_2:
                        target_table = result_table_name or Config.ADDRESS_TAGGING_17_2_RESULTS_TABLE
                        data_loader.create_address_tagging_17_2_table(target_table)
                        data_loader.truncate_address_tagging_17_2_table(target_table)
                    elif is_17:
                        target_table = result_table_name or Config.ADDRESS_TAGGING_17_RESULTS_TABLE
                        data_loader.create_address_tagging_17_table(target_table)
                        data_loader.truncate_address_tagging_17_table(target_table)
                    else:
                        target_table = result_table_name or Config.ADDRESS_TAGGING_RESULTS_TABLE
                        data_loader.create_address_tagging_table(target_table)
                        data_loader.truncate_address_tagging_table(target_table)

                    batch_size = 100
                    total_inserted = 0
                    for i in range(0, len(results), batch_size):
                        batch = results[i:i + batch_size]
                        if is_17_2:
                            n = data_loader.insert_address_tagging_17_2_results(batch, target_table)
                        elif is_17:
                            n = data_loader.insert_address_tagging_17_results(batch, target_table)
                        else:
                            n = data_loader.insert_address_tagging_results(batch, target_table)
                        total_inserted += n

                    logger.info(f"[地址结构化解析] 结果已写入 {target_table}，共 {total_inserted}/{len(results)} 条")

                    if table_name:
                        parser._update_status(status_message='正在生成副本表...')
                        if is_17_2:
                            copy_table = data_loader.create_tagging_17_2_copy_table_from_result(
                                table_name, address_col, target_table
                            )
                        elif is_17:
                            copy_table = data_loader.create_tagging_17_copy_table_from_result(
                                table_name, address_col, target_table
                            )
                        else:
                            copy_table = data_loader.create_tagging_copy_table_from_result(
                                table_name, address_col, target_table
                            )

            end_time = time.time()
            parser._update_status(
                is_running=False, progress=1.0,
                status_message='地址结构化解析完成'
            )
            with parser._lock:
                parser.completed = True
                parser.completion_success = True
                parser.completion_message = '解析完成'
                parser.completion_results = None
                parser.completion_end_time = end_time
                parser.completion_copy_table = copy_table
                parser.completion_source_table = source_table

            if completed_callback:
                completed_callback(True, '解析完成', None)

        except Exception as e:
            logger.error(f"[地址结构化解析] 失败: {str(e)}")
            import traceback
            logger.error(f"[地址结构化解析] 详细堆栈: {traceback.format_exc()}")
            end_time = time.time()
            parser._update_status(
                is_running=False,
                error_message=str(e),
                status_message='地址结构化解析失败'
            )
            with parser._lock:
                parser.completed = True
                parser.completion_success = False
                parser.completion_message = str(e)
                parser.completion_end_time = end_time
            if completed_callback:
                completed_callback(False, str(e), None)

        finally:
            if is_db_mode and db_conn:
                try:
                    db_conn.close()
                    logger.info("[地址结构化解析] 数据库连接已释放")
                except Exception:
                    pass

    thread = threading.Thread(target=task_func, daemon=True)
    thread.start()
    return thread
