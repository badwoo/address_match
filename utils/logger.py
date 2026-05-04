"""
日志工具模块
===========

提供统一的日志记录功能，支持控制台、内存缓存和文件三重输出。

核心功能：
    1. StreamHandler - 内存缓存日志处理器，支持UI实时展示
    2. setup_logger - 初始化文件日志输出
    3. get_log_messages - 获取内存中的日志消息列表
    4. clear_logs - 清空内存日志缓存

日志输出目标：
    - 内存缓存（StreamHandler）：最多保留10000条，供Streamlit UI展示
    - 文件输出（FileHandler）：写入app.log文件，持久化存储

使用说明：
    from utils.logger import logger
    logger.info("信息日志")
    logger.error("错误日志")
"""

import logging
from io import StringIO

log_stream = StringIO()


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
        """
        处理一条日志记录
        
        Args:
            record: logging.LogRecord 对象
        """
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

logger = logging.getLogger('address_matcher')
logger.setLevel(logging.INFO)
logger.addHandler(stream_handler)


def setup_logger():
    """
    初始化文件日志输出
    
    创建app.log文件处理器并添加到logger，支持UTF-8编码。
    应在应用启动时调用一次。
    """
    file_handler = logging.FileHandler('app.log', encoding='utf-8')
    file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    logger.addHandler(file_handler)


def get_log_messages():
    """
    获取内存中的日志消息列表
    
    Returns:
        list: 日志消息列表，每条记录包含 level, message, time
    """
    return stream_handler.logs


def clear_logs():
    """
    清空内存日志缓存
    """
    stream_handler.logs = []
