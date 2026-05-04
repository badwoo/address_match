"""
数据库连接模块
==============

负责管理 PostgreSQL 数据库连接，支持 pgvector 扩展用于向量存储和检索。

核心功能：
    1. 建立/关闭数据库连接
    2. 执行SQL查询和事务管理
    3. 获取数据库表结构信息
    4. 注册 pgvector 向量类型支持
    5. 自动设置 search_path 到用户指定的 schema

技术要点：
    - 使用 psycopg2 作为 PostgreSQL 驱动
    - 注册 pgvector 扩展以支持向量数据类型
    - 支持连接池和自动重连机制
    - 连接后自动设置 search_path，确保所有表操作在正确的 schema 下执行
"""

import psycopg2
import psycopg2.extras
from config import Config
from utils.logger import logger


def quote_identifier(name):
    """
    对 PostgreSQL 标识符（表名、列名等）进行双引号引用

    处理中文表名、特殊字符、保留字等情况，确保 SQL 语句中的标识符正确解析。

    Args:
        name: 标识符名称（表名或列名）

    Returns:
        str: 用双引号引用后的标识符，如 "企业表"
    """
    if not name:
        return name
    return '"' + name.replace('"', '""') + '"'

class DBConnection:
    """
    PostgreSQL 数据库连接管理器
    
    Attributes:
        host: 数据库主机地址
        port: 数据库端口
        dbname: 数据库名称
        user: 数据库用户名
        password: 数据库密码
        schema: 数据库模式（schema）
        conn: psycopg2 连接对象
        cursor: 数据库游标
    """
    
    def __init__(self, host=None, port=None, dbname=None, user=None, password=None, schema=None):
        """
        初始化数据库连接配置
        
        Args:
            host: 数据库主机地址，默认使用 Config.DB_HOST
            port: 数据库端口，默认使用 Config.DB_PORT
            dbname: 数据库名称，默认使用 Config.DB_NAME
            user: 数据库用户名，默认使用 Config.DB_USER
            password: 数据库密码，默认使用 Config.DB_PASSWORD
            schema: 数据库模式，默认使用 Config.DB_SCHEMA（默认为'public'）
        """
        self.host = host or Config.DB_HOST
        self.port = port or Config.DB_PORT
        self.dbname = dbname or Config.DB_NAME
        self.user = user or Config.DB_USER
        self.password = password or Config.DB_PASSWORD
        self.schema = schema or Config.DB_SCHEMA
        self.conn = None
        self.cursor = None
    
    def connect(self):
        """
        建立数据库连接
        
        连接成功后会自动：
        1. 注册 pgvector 扩展以支持向量数据类型
        2. 设置 search_path 到用户指定的 schema（同时保留 public 以访问 pgvector 等扩展）
        
        Returns:
            bool: 连接成功返回 True，失败返回 False
        """
        try:
            self.conn = psycopg2.connect(
                host=self.host,
                port=self.port,
                dbname=self.dbname,
                user=self.user,
                password=self.password
            )
            # 使用 RealDictCursor 返回字典形式的查询结果
            self.cursor = self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            
            # 注册 pgvector 扩展，支持向量类型
            try:
                import pgvector.psycopg2
                pgvector.psycopg2.register_vector(self.conn)
                logger.info("pgvector registered successfully")
            except Exception as pg_e:
                logger.warning(f"Failed to register pgvector: {str(pg_e)}")
            
            # 设置 search_path 到用户指定的 schema，同时保留 public 以访问 pgvector 等扩展
            # 这样所有未指定 schema 前缀的表操作都会在正确的 schema 下执行
            try:
                schema_quoted = quote_identifier(self.schema)
                self.cursor.execute(f"SET search_path TO {schema_quoted}, public")
                logger.info(f"search_path set to {self.schema}, public")
            except Exception as sp_e:
                logger.warning(f"Failed to set search_path: {str(sp_e)}")
            
            logger.info(f"Successfully connected to database: {self.dbname}, schema: {self.schema}")
            return True
        except Exception as e:
            logger.error(f"Database connection failed: {str(e)}")
            return False
    
    def close(self):
        """关闭数据库连接"""
        if self.cursor:
            self.cursor.close()
        if self.conn:
            self.conn.close()
        logger.info("Database connection closed")
    
    def _check_connection(self):
        """
        检查数据库连接是否正常
        
        通过执行简单的 SELECT 1 查询来验证连接状态。
        
        Returns:
            bool: 连接正常返回 True，否则返回 False
        """
        try:
            if self.conn:
                cur = self.conn.cursor()
                cur.execute("SELECT 1")
                cur.close()
                return True
        except Exception:
            pass
        return False
    
    def execute(self, sql, params=None):
        """
        执行 SQL 语句
        
        支持自动重连机制，如果连接断开会尝试重新连接。
        
        Args:
            sql: SQL 语句
            params: SQL 参数（可选）
        
        Returns:
            cursor: 执行成功返回游标对象，失败返回 None
        """
        try:
            # 检查连接状态，必要时重新连接
            if not self.conn or not self._check_connection():
                if not self.connect():
                    return None
            self.cursor.execute(sql, params)
            return self.cursor
        except Exception as e:
            logger.error(f"SQL execution error: {str(e)}")
            return None
    
    def commit(self):
        """提交事务"""
        if self.conn:
            self.conn.commit()
            logger.info("Transaction committed")
    
    def rollback(self):
        """回滚事务"""
        if self.conn:
            self.conn.rollback()
            logger.info("Transaction rolled back")
    
    def test_connection(self):
        """
        测试数据库连接
        
        用于验证连接参数是否正确，不保持连接。
        
        Returns:
            bool: 连接成功返回 True，失败返回 False
        """
        try:
            conn = psycopg2.connect(
                host=self.host,
                port=self.port,
                dbname=self.dbname,
                user=self.user,
                password=self.password
            )
            conn.close()
            return True
        except Exception as e:
            logger.error(f"Connection test failed: {str(e)}")
            return False
    
    def get_tables(self):
        """
        获取数据库中指定模式下的所有表名
        
        Returns:
            list: 表名列表
        """
        sql = """
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = %s
        """
        cursor = self.execute(sql, (self.schema,))
        if cursor:
            return [row['table_name'] for row in cursor.fetchall()]
        return []
    
    def get_columns(self, table_name):
        """
        获取指定表的字段信息
        
        Args:
            table_name: 表名
        
        Returns:
            list: 字段元组列表，每个元组包含 (字段名, 数据类型)
        """
        sql = """
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_name = %s AND table_schema = %s
        """
        cursor = self.execute(sql, (table_name, self.schema))
        if cursor:
            return [(row['column_name'], row['data_type']) for row in cursor.fetchall()]
        return []
