"""
日志工具模块
===========

提供统一的日志记录功能，支持内存缓存和数据库双重输出。

核心功能：
    1. StreamHandler - 内存缓存日志处理器，支持UI实时展示
    2. DBLogHandler - 数据库日志处理器，持久化存储到 app_log 表
    3. get_log_messages - 获取内存中的日志消息列表
    4. clear_logs - 清空内存日志缓存

日志输出目标：
    - 内存缓存（StreamHandler）：最多保留10000条，供Streamlit UI展示
    - 数据库存储（DBLogHandler）：写入 app_log 表，持久化存储
"""

import logging
import threading

logger = logging.getLogger('address_matcher')
logger.setLevel(logging.WARNING)  # 默认只记录 WARNING 及以上，精简日志内容


class StreamHandler(logging.Handler):
    """
    内存缓存日志处理器

    将日志消息缓存到内存列表中，供Streamlit UI实时展示。
    当缓存超过10000条时，自动丢弃最早的记录。

    Attributes:
        logs: 日志消息列表，每条记录包含 level, message, time
    """

    def __init__(self):
        super().__init__()
        self.logs = []

    def emit(self, record):
        msg = self.format(record)
        self.logs.append({
            'level': record.levelname,
            'message': msg,
            'time': record.created
        })
        if len(self.logs) > 10000:
            self.logs = self.logs[-10000:]


stream_handler = StreamHandler()
stream_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logger.addHandler(stream_handler)


class DBLogHandler(logging.Handler):
    """
    数据库日志处理器

    将 WARNING 及以上级别的日志写入数据库 app_log 表。
    线程安全，自动处理数据库断连重试。

    表结构:
        id: 主键
        level: 日志级别
        message: 日志消息
        created_at: 创建时间
    """

    _instance = None
    _lock = threading.Lock()

    def __init__(self):
        super().__init__()
        self.db_conn = None
        self._queue = []
        self._max_queue = 1000  # 最大缓存条数，防止内存溢出

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def set_db_connection(self, db_conn):
        """设置数据库连接并确保 app_log 表存在"""
        self.db_conn = db_conn
        self._ensure_table()
        self._flush_queue()

    def _ensure_table(self):
        """确保 app_log 表存在"""
        if not self.db_conn:
            return
        try:
            sql = """
                CREATE TABLE IF NOT EXISTS app_log (
                    id SERIAL PRIMARY KEY,
                    level VARCHAR(10) NOT NULL,
                    message TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """
            self.db_conn.execute(sql)
            self.db_conn.commit()
        except Exception:
            pass

    def _flush_queue(self):
        """将队列中的日志批量写入数据库"""
        if not self._queue or not self.db_conn:
            return
        try:
            sql = "INSERT INTO app_log (level, message) VALUES %s"
            from psycopg2 import extras
            extras.execute_values(self.db_conn.cursor, sql, self._queue, page_size=100)
            self.db_conn.commit()
        except Exception:
            pass
        self._queue = []

    def emit(self, record):
        if record.levelno < logging.WARNING:
            return
        msg = self.format(record)
        if self.db_conn:
            try:
                self._flush_queue()
                check_sql = "SELECT 1"
                self.db_conn.cursor.execute(check_sql)
                sql = "INSERT INTO app_log (level, message) VALUES (%s, %s)"
                self.db_conn.execute(sql, (record.levelname, msg))
                self.db_conn.commit()
            except Exception:
                self._queue.append((record.levelname, msg))
                if len(self._queue) > self._max_queue:
                    self._queue = self._queue[-self._max_queue:]
        else:
            self._queue.append((record.levelname, msg))
            if len(self._queue) > self._max_queue:
                self._queue = self._queue[-self._max_queue:]


db_handler = DBLogHandler.get_instance()
db_handler.setFormatter(logging.Formatter('%(asctime)s - %(message)s'))
logger.addHandler(db_handler)


def setup_db_logging(db_conn):
    """初始化数据库日志，在数据库连接成功后调用"""
    db_handler.set_db_connection(db_conn)


def get_log_messages():
    """
    获取内存中的日志消息列表

    Returns:
        list: 日志消息列表，每条记录包含 level, message, time
    """
    return stream_handler.logs


def clear_logs():
    """清空内存日志缓存"""
    stream_handler.logs = []


def get_db_logs(db_conn, limit=200, level=None):
    """
    从数据库获取日志

    Args:
        db_conn: 数据库连接
        limit: 返回条数限制
        level: 过滤日志级别，None 表示不过滤

    Returns:
        list: 日志记录列表
    """
    try:
        if level:
            sql = "SELECT id, level, message, created_at FROM app_log WHERE level = %s ORDER BY id DESC LIMIT %s"
            cursor = db_conn.execute(sql, (level, limit))
        else:
            sql = "SELECT id, level, message, created_at FROM app_log ORDER BY id DESC LIMIT %s"
            cursor = db_conn.execute(sql, (limit,))
        if cursor:
            return list(cursor.fetchall())
    except Exception:
        pass
    return []


def clear_db_logs(db_conn):
    """清空数据库日志表"""
    try:
        db_conn.execute("TRUNCATE TABLE app_log")
        db_conn.commit()
    except Exception:
        pass
