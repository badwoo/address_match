"""
数据加载模块
============

负责数据的批量加载、结果存储和统计查询。

核心功能：
    1. 批量加载企业数据（支持分页）
    2. 批量加载标准地址数据（支持分页）
    3. 创建和管理召回结果表（recall_results）
    4. 创建和管理匹配结果表（match_results）
    5. 插入召回结果和匹配结果
    6. 查询匹配结果和统计信息

技术要点：
    - 使用 pandas DataFrame 进行数据处理
    - 支持批量插入提高性能
    - 使用 psycopg2.extras.execute_values 进行高效批量插入
"""

import time
import pandas as pd
import psycopg2
from config import Config
from database.connection import quote_identifier
from utils.logger import logger

class DataLoader:
    """
    数据加载器
    
    负责从数据库批量加载企业数据和标准地址数据，以及管理匹配结果的存储和查询。
    
    Attributes:
        db: 数据库连接对象
    """
    
    def __init__(self, db_connection):
        """
        初始化数据加载器

        Args:
            db_connection: DBConnection 对象
        """
        self.db = db_connection

    # ==================== 通用方法（减少重复代码） ====================

    def _generic_truncate_table(self, table_name, log_label=''):
        """
        通用清空表

        Args:
            table_name: 表名
            log_label: 日志标签，用于标识表类型

        Returns:
            bool: 清空成功返回 True
        """
        sql = f"TRUNCATE TABLE {quote_identifier(table_name)}"
        cursor = self.db.execute(sql)
        if cursor:
            self.db.commit()
            logger.info(f"{log_label}{table_name} 已清空")
            return True
        return False

    def _generic_get_count(self, table_name, filters=None, filter_builder=None):
        """
        通用计数查询

        Args:
            table_name: 表名
            filters: 过滤条件字典
            filter_builder: 筛选条件构建函数，签名为 (filters) -> (conditions, params)

        Returns:
            int: 记录总数
        """
        sql = f"SELECT COUNT(*) as count FROM {quote_identifier(table_name)}"
        params = None

        if filters and filter_builder:
            conditions, params = filter_builder(filters)
            if conditions:
                sql += " WHERE " + " AND ".join(conditions)

        try:
            cursor = self.db.execute(sql, params)
            if cursor:
                result = cursor.fetchone()
                return result['count'] if result else 0
        except Exception as e:
            logger.error(f"获取记录总数失败: {str(e)}")
        return 0

    def _generic_get_paginated(self, table_name, filters=None, filter_builder=None,
                                page=1, page_size=20, order_by='id'):
        """
        通用分页查询

        Args:
            table_name: 表名
            filters: 过滤条件字典
            filter_builder: 筛选条件构建函数，签名为 (filters) -> (conditions, params)
            page: 页码（从1开始）
            page_size: 每页记录数
            order_by: 排序子句

        Returns:
            DataFrame: 查询结果数据帧
        """
        sql = f"SELECT * FROM {quote_identifier(table_name)}"
        params = []

        if filters and filter_builder:
            conditions, params = filter_builder(filters)
            if conditions:
                sql += " WHERE " + " AND ".join(conditions)

        sql += f" ORDER BY {order_by}"

        offset = (page - 1) * page_size
        sql += f" LIMIT {page_size} OFFSET {offset}"

        try:
            cursor = self.db.execute(sql, params if params else None)
            if cursor:
                rows = cursor.fetchall()
                return pd.DataFrame(rows)
        except Exception as e:
            logger.error(f"分页查询失败: {str(e)}")
        return pd.DataFrame()

    def _generic_get_statistics(self, table_name, count_exprs, default_stats):
        """
        通用统计查询

        Args:
            table_name: 表名
            count_exprs: SQL统计表达式字符串（逗号分隔的聚合表达式）
            default_stats: 查询失败时返回的默认统计字典

        Returns:
            dict: 统计信息字典
        """
        sql = f"SELECT COUNT(*) as total_count, {count_exprs} FROM {quote_identifier(table_name)}"

        try:
            cursor = self.db.execute(sql)
            if cursor:
                result = cursor.fetchone()
                return result, result['total_count'] if result else 0
        except Exception as e:
            logger.error(f"获取统计信息失败: {str(e)}")
        return None, 0

    def _generic_export_batch(self, table_name, filters, filter_builder,
                               count_method, paginated_method, batch_size=5000):
        """
        通用批量导出

        Args:
            table_name: 表名
            filters: 过滤条件字典
            filter_builder: 筛选条件构建函数
            count_method: 计数方法引用
            paginated_method: 分页方法引用
            batch_size: 每批加载的记录数

        Yields:
            DataFrame: 每批结果数据帧
        """
        total = count_method(table_name, filters)
        if total == 0:
            return

        offset = 0
        while offset < total:
            results = paginated_method(
                table_name=table_name, filters=filters,
                page=(offset // batch_size) + 1, page_size=batch_size
            )
            if not results.empty:
                yield results
            offset += batch_size

    # ==================== 数据加载方法 ====================
    
    def load_enterprise_data(self, table_name, id_col, name_col, address_col, batch_size=None):
        """
        批量加载企业数据（游标分页加载）
        
        使用基于 id > last_id 的游标分页替代 OFFSET 分页，
        避免深度分页时数据库扫描并丢弃大量行的性能问题。
        
        Args:
            table_name: 企业表名
            id_col: 企业标识字段名
            name_col: 企业名字段名
            address_col: 企业地址字段名
            batch_size: 每批大小，默认使用 Config.BATCH_SIZE_DB

        Yields:
            DataFrame: 包含 id, name, address 列的数据帧
        """
        batch_size = batch_size or Config.BATCH_SIZE_DB

        if not name_col:
            name_col = id_col

        last_id = None

        while True:
            if last_id is None:
                sql = f"""
                    SELECT {quote_identifier(id_col)} AS id, {quote_identifier(name_col)} AS name, {quote_identifier(address_col)} AS address
                    FROM {quote_identifier(table_name)}
                    WHERE {quote_identifier(address_col)} IS NOT NULL AND {quote_identifier(address_col)} != ''
                    ORDER BY {quote_identifier(id_col)}
                    LIMIT %s
                """
                cursor = self.db.execute(sql, (batch_size,))
            else:
                sql = f"""
                    SELECT {quote_identifier(id_col)} AS id, {quote_identifier(name_col)} AS name, {quote_identifier(address_col)} AS address
                    FROM {quote_identifier(table_name)}
                    WHERE {quote_identifier(address_col)} IS NOT NULL AND {quote_identifier(address_col)} != ''
                    AND {quote_identifier(id_col)} > %s
                    ORDER BY {quote_identifier(id_col)}
                    LIMIT %s
                """
                cursor = self.db.execute(sql, (last_id, batch_size))

            if not cursor:
                break

            rows = cursor.fetchall()
            if not rows:
                break

            df = pd.DataFrame(rows)
            if len(df.columns) == 3:
                df.columns = ['id', 'name', 'address']
            else:
                logger.error(f"Expected 3 columns but got {len(df.columns)}")
                break

            df['id'] = df['id'].astype(str)

            last_id = rows[-1]['id']  # SELECT 使用 AS id 别名，RealDictCursor 以别名作为 key
            yield df

    def load_standard_addresses(self, table_name, id_col, address_col, room_col=None, batch_size=None):
        """
        批量加载标准地址数据（游标分页加载）

        使用基于 id > last_id 的游标分页替代 OFFSET 分页，
        避免深度分页时数据库扫描并丢弃大量行的性能问题。

        Args:
            table_name: 标准地址表名
            id_col: 地址编码字段名
            address_col: 标准地址字段名
            room_col: 房屋编码字段名（可选）
            batch_size: 每批大小，默认使用 Config.BATCH_SIZE_DB
        
        Yields:
            DataFrame: 包含 id, address, [room_no] 列的数据帧
        """
        batch_size = batch_size or Config.BATCH_SIZE_DB
        
        last_id = None
        
        while True:
            if room_col:
                if last_id is None:
                    sql = f"""
                        SELECT {quote_identifier(id_col)} AS id, {quote_identifier(address_col)} AS address, {quote_identifier(room_col)} AS room_no
                        FROM {quote_identifier(table_name)}
                        WHERE {quote_identifier(address_col)} IS NOT NULL AND {quote_identifier(address_col)} != ''
                        ORDER BY {quote_identifier(id_col)}
                        LIMIT %s
                    """
                    cursor = self.db.execute(sql, (batch_size,))
                else:
                    sql = f"""
                        SELECT {quote_identifier(id_col)} AS id, {quote_identifier(address_col)} AS address, {quote_identifier(room_col)} AS room_no
                        FROM {quote_identifier(table_name)}
                        WHERE {quote_identifier(address_col)} IS NOT NULL AND {quote_identifier(address_col)} != ''
                        AND {quote_identifier(id_col)} > %s
                        ORDER BY {quote_identifier(id_col)}
                        LIMIT %s
                    """
                    cursor = self.db.execute(sql, (last_id, batch_size))
            else:
                if last_id is None:
                    sql = f"""
                        SELECT {quote_identifier(id_col)} AS id, {quote_identifier(address_col)} AS address
                        FROM {quote_identifier(table_name)}
                        WHERE {quote_identifier(address_col)} IS NOT NULL AND {quote_identifier(address_col)} != ''
                        ORDER BY {quote_identifier(id_col)}
                        LIMIT %s
                    """
                    cursor = self.db.execute(sql, (batch_size,))
                else:
                    sql = f"""
                        SELECT {quote_identifier(id_col)} AS id, {quote_identifier(address_col)} AS address
                        FROM {quote_identifier(table_name)}
                        WHERE {quote_identifier(address_col)} IS NOT NULL AND {quote_identifier(address_col)} != ''
                        AND {quote_identifier(id_col)} > %s
                        ORDER BY {quote_identifier(id_col)}
                        LIMIT %s
                    """
                    cursor = self.db.execute(sql, (last_id, batch_size))
            
            if not cursor:
                break
            
            rows = cursor.fetchall()
            if not rows:
                break
            
            df = pd.DataFrame(rows)
            if room_col:
                df.columns = ['id', 'address', 'room_no']
            else:
                df.columns = ['id', 'address']

            df['id'] = df['id'].astype(str)
            
            last_id = rows[-1]['id']  # SELECT 使用 AS id 别名，RealDictCursor 以别名作为 key
            yield df
    
    def get_unvectorized_count(self, table_name, id_col, address_col, vector_table):
        """
        获取未向量化的记录数（源表中的 source_id 不存在于向量表中）

        Args:
            table_name: 源表名
            id_col: 源表标识字段名
            address_col: 地址字段名
            vector_table: 向量表名

        Returns:
            int: 未向量化的有效地址记录数
        """
        sql = f"""
            SELECT COUNT(*) as count
            FROM {quote_identifier(table_name)} s
            WHERE s.{quote_identifier(address_col)} IS NOT NULL AND s.{quote_identifier(address_col)} != ''
            AND NOT EXISTS (
                SELECT 1 FROM {quote_identifier(vector_table)} v
                WHERE v.source_id = s.{quote_identifier(id_col)}::text
            )
        """
        cursor = self.db.execute(sql)
        if cursor:
            result = cursor.fetchone()
            return result['count'] if result else 0
        return 0

    def load_unvectorized_enterprise_data(self, table_name, id_col, name_col, address_col,
                                           vector_table, batch_size=None):
        """
        增量加载未向量化的企业数据（source_id 不在向量表中）

        Args:
            table_name: 企业表名
            id_col: 企业标识字段名
            name_col: 企业名字段名
            address_col: 企业地址字段名
            vector_table: 向量表名
            batch_size: 每批大小

        Yields:
            DataFrame: 包含 id, name, address 列的数据帧
        """
        batch_size = batch_size or Config.BATCH_SIZE_DB
        if not name_col:
            name_col = id_col

        last_id = None
        while True:
            if last_id is None:
                sql = f"""
                    SELECT s.{quote_identifier(id_col)} AS id, s.{quote_identifier(name_col)} AS name, s.{quote_identifier(address_col)} AS address
                    FROM {quote_identifier(table_name)} s
                    WHERE s.{quote_identifier(address_col)} IS NOT NULL AND s.{quote_identifier(address_col)} != ''
                    AND NOT EXISTS (
                        SELECT 1 FROM {quote_identifier(vector_table)} v
                        WHERE v.source_id = s.{quote_identifier(id_col)}::text
                    )
                    ORDER BY s.{quote_identifier(id_col)}
                    LIMIT %s
                """
                cursor = self.db.execute(sql, (batch_size,))
            else:
                sql = f"""
                    SELECT s.{quote_identifier(id_col)} AS id, s.{quote_identifier(name_col)} AS name, s.{quote_identifier(address_col)} AS address
                    FROM {quote_identifier(table_name)} s
                    WHERE s.{quote_identifier(address_col)} IS NOT NULL AND s.{quote_identifier(address_col)} != ''
                    AND s.{quote_identifier(id_col)} > %s
                    AND NOT EXISTS (
                        SELECT 1 FROM {quote_identifier(vector_table)} v
                        WHERE v.source_id = s.{quote_identifier(id_col)}::text
                    )
                    ORDER BY s.{quote_identifier(id_col)}
                    LIMIT %s
                """
                cursor = self.db.execute(sql, (last_id, batch_size))

            if not cursor:
                break
            rows = cursor.fetchall()
            if not rows:
                break
            df = pd.DataFrame(rows)
            if len(df.columns) == 3:
                df.columns = ['id', 'name', 'address']
            else:
                logger.error(f"Expected 3 columns but got {len(df.columns)}")
                break
            df['id'] = df['id'].astype(str)
            last_id = rows[-1]['id']  # SELECT 使用 AS id 别名，RealDictCursor 以别名作为 key
            yield df

    def load_unvectorized_standard_addresses(self, table_name, id_col, address_col, room_col,
                                              vector_table, batch_size=None):
        """
        增量加载未向量化的标准地址数据

        Args:
            table_name: 标准地址表名
            id_col: 地址编码字段名
            address_col: 标准地址字段名
            room_col: 房屋编码字段名（可选）
            vector_table: 向量表名
            batch_size: 每批大小

        Yields:
            DataFrame: 包含 id, address, [room_no] 列的数据帧
        """
        batch_size = batch_size or Config.BATCH_SIZE_DB
        last_id = None

        while True:
            if room_col:
                if last_id is None:
                    sql = f"""
                        SELECT s.{quote_identifier(id_col)} AS id, s.{quote_identifier(address_col)} AS address, s.{quote_identifier(room_col)} AS room_no
                        FROM {quote_identifier(table_name)} s
                        WHERE s.{quote_identifier(address_col)} IS NOT NULL AND s.{quote_identifier(address_col)} != ''
                        AND NOT EXISTS (
                            SELECT 1 FROM {quote_identifier(vector_table)} v
                            WHERE v.source_id = s.{quote_identifier(id_col)}::text
                        )
                        ORDER BY s.{quote_identifier(id_col)}
                        LIMIT %s
                    """
                    cursor = self.db.execute(sql, (batch_size,))
                else:
                    sql = f"""
                        SELECT s.{quote_identifier(id_col)} AS id, s.{quote_identifier(address_col)} AS address, s.{quote_identifier(room_col)} AS room_no
                        FROM {quote_identifier(table_name)} s
                        WHERE s.{quote_identifier(address_col)} IS NOT NULL AND s.{quote_identifier(address_col)} != ''
                        AND s.{quote_identifier(id_col)} > %s
                        AND NOT EXISTS (
                            SELECT 1 FROM {quote_identifier(vector_table)} v
                            WHERE v.source_id = s.{quote_identifier(id_col)}::text
                        )
                        ORDER BY s.{quote_identifier(id_col)}
                        LIMIT %s
                    """
                    cursor = self.db.execute(sql, (last_id, batch_size))
            else:
                if last_id is None:
                    sql = f"""
                        SELECT s.{quote_identifier(id_col)} AS id, s.{quote_identifier(address_col)} AS address
                        FROM {quote_identifier(table_name)} s
                        WHERE s.{quote_identifier(address_col)} IS NOT NULL AND s.{quote_identifier(address_col)} != ''
                        AND NOT EXISTS (
                            SELECT 1 FROM {quote_identifier(vector_table)} v
                            WHERE v.source_id = s.{quote_identifier(id_col)}::text
                        )
                        ORDER BY s.{quote_identifier(id_col)}
                        LIMIT %s
                    """
                    cursor = self.db.execute(sql, (batch_size,))
                else:
                    sql = f"""
                        SELECT s.{quote_identifier(id_col)} AS id, s.{quote_identifier(address_col)} AS address
                        FROM {quote_identifier(table_name)} s
                        WHERE s.{quote_identifier(address_col)} IS NOT NULL AND s.{quote_identifier(address_col)} != ''
                        AND s.{quote_identifier(id_col)} > %s
                        AND NOT EXISTS (
                            SELECT 1 FROM {quote_identifier(vector_table)} v
                            WHERE v.source_id = s.{quote_identifier(id_col)}::text
                        )
                        ORDER BY s.{quote_identifier(id_col)}
                        LIMIT %s
                    """
                    cursor = self.db.execute(sql, (last_id, batch_size))

            if not cursor:
                break
            rows = cursor.fetchall()
            if not rows:
                break
            df = pd.DataFrame(rows)
            if room_col:
                df.columns = ['id', 'address', 'room_no']
            else:
                df.columns = ['id', 'address']
            df['id'] = df['id'].astype(str)
            last_id = rows[-1]['id']  # SELECT 使用 AS id 别名，RealDictCursor 以别名作为 key
            yield df

    def get_total_count(self, table_name):
        """
        获取表的总记录数
        
        Args:
            table_name: 表名
        
        Returns:
            int: 记录数
        """
        sql = f"SELECT COUNT(*) as count FROM {quote_identifier(table_name)}"
        cursor = self.db.execute(sql)
        if cursor:
            result = cursor.fetchone()
            return result['count'] if result else 0
        return 0
    
    def get_valid_address_count(self, table_name, address_col):
        """
        获取有效地址记录数（地址不为空）
        
        Args:
            table_name: 表名
            address_col: 地址字段名
        
        Returns:
            int: 有效地址记录数
        """
        sql = f"SELECT COUNT(*) as count FROM {quote_identifier(table_name)} WHERE {quote_identifier(address_col)} IS NOT NULL AND {quote_identifier(address_col)} != ''"
        cursor = self.db.execute(sql)
        if cursor:
            result = cursor.fetchone()
            return result['count'] if result else 0
        return 0
    
    def create_recall_table(self, table_name=None):
        """
        创建粗召回结果表
        
        表结构:
            id: 主键
            enterprise_id: 企业标识
            enterprise_name: 企业名称
            enterprise_address: 企业地址
            standard_id: 标准地址编码
            standard_address: 标准地址
            room_no: 房屋编码
            similarity: 相似度分数
            created_at: 创建时间
        
        Args:
            table_name: 表名，默认使用 Config.RECALL_RESULTS_TABLE
        
        Returns:
            bool: 创建成功返回 True
        """
        table_name = table_name or Config.RECALL_RESULTS_TABLE
        sql = f"""
            CREATE TABLE IF NOT EXISTS {quote_identifier(table_name)} (
                id SERIAL PRIMARY KEY,
                enterprise_id VARCHAR(255) NOT NULL,
                enterprise_name TEXT,
                enterprise_address TEXT,
                standard_id VARCHAR(255),
                standard_address TEXT,
                room_no VARCHAR(100),
                similarity DOUBLE PRECISION,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """
        cursor = self.db.execute(sql)
        if cursor:
            self.db.commit()
            logger.info(f"Recall results table {table_name} created successfully")
        
        self._migrate_float_to_double(table_name)
        
        return True
    
    def insert_recall_results(self, results, table_name=None):
        """
        批量插入粗召回结果（分批提交，避免大数据量时内存峰值过高）

        Args:
            results: 召回结果列表，每个元素包含 enterprise_id, enterprise_name, enterprise_address, candidates
            table_name: 表名，默认使用 Config.RECALL_RESULTS_TABLE

        Returns:
            int: 成功插入的记录数
        """
        table_name = table_name or Config.RECALL_RESULTS_TABLE
        if not results:
            return 0

        sql = f"""
            INSERT INTO {quote_identifier(table_name)}
            (enterprise_id, enterprise_name, enterprise_address, standard_id, standard_address, room_no, similarity)
            VALUES %s
        """

        try:
            total_inserted = 0
            # 分批构建 values 并提交，避免一次性展开所有候选导致内存峰值
            BATCH_SIZE = 5000
            batch_values = []
            for item in results:
                enterprise_id = str(item['enterprise_id'])
                enterprise_name = item.get('enterprise_name', '')
                enterprise_address = item['enterprise_address']
                for candidate in item['candidates']:
                    batch_values.append((
                        enterprise_id,
                        enterprise_name,
                        enterprise_address,
                        str(candidate['source_id']),
                        candidate['address'],
                        candidate.get('room_no', ''),
                        float(candidate['similarity'])
                    ))
                    # 达到批次大小时立即提交
                    if len(batch_values) >= BATCH_SIZE:
                        cursor = self.db.get_cursor()
                        if not cursor:
                            raise Exception("获取数据库游标失败")
                        try:
                            psycopg2.extras.execute_values(
                                cursor, sql, batch_values, template=None, page_size=1000
                            )
                        finally:
                            cursor.close()
                        self.db.commit()
                        total_inserted += len(batch_values)
                        batch_values = []

            # 提交剩余数据
            if batch_values:
                cursor = self.db.get_cursor()
                if not cursor:
                    raise Exception("获取数据库游标失败")
                try:
                    psycopg2.extras.execute_values(
                        cursor, sql, batch_values, template=None, page_size=1000
                    )
                finally:
                    cursor.close()
                self.db.commit()
                total_inserted += len(batch_values)

            logger.info(f"Inserted {total_inserted} recall results")
            return total_inserted
        except Exception as e:
            logger.error(f"Failed to insert recall results: {str(e)}")
            self.db.rollback()
            return 0
    
    def get_recall_results(self, page=1, page_size=20, table_name=None):
        """
        分页获取粗召回结果
        
        Args:
            page: 页码
            page_size: 每页大小
            table_name: 表名，默认使用 Config.RECALL_RESULTS_TABLE
        
        Returns:
            DataFrame: 召回结果数据帧
        """
        table_name = table_name or Config.RECALL_RESULTS_TABLE
        offset = (page - 1) * page_size
        sql = f"SELECT * FROM {quote_identifier(table_name)} ORDER BY enterprise_id, similarity DESC LIMIT %s OFFSET %s"
        cursor = self.db.execute(sql, (page_size, offset))
        if cursor:
            rows = cursor.fetchall()
            return pd.DataFrame(rows)
        return pd.DataFrame()
    
    def _build_recall_filter_conditions(self, filters):
        """
        构建粗召回结果的筛选条件

        Args:
            filters: 过滤条件字典，支持以下键:
                - keyword: 关键词搜索（企业名/企业地址/标准地址）
                - min_similarity: 最小相似度
                - max_similarity: 最大相似度

        Returns:
            tuple: (conditions列表, params列表)
        """
        conditions = []
        params = []

        if 'keyword' in filters and filters['keyword']:
            conditions.append("(enterprise_name LIKE %s OR enterprise_address LIKE %s OR standard_address LIKE %s)")
            keyword = f"%{filters['keyword']}%"
            params.extend([keyword, keyword, keyword])

        if 'min_similarity' in filters and filters['min_similarity'] is not None and filters['min_similarity'] > 0:
            conditions.append("similarity >= %s")
            params.append(filters['min_similarity'])

        if 'max_similarity' in filters and filters['max_similarity'] is not None and filters['max_similarity'] < 1.0:
            conditions.append("similarity <= %s")
            params.append(filters['max_similarity'])

        return conditions, params

    def get_recall_results_count(self, table_name=None, filters=None):
        """
        获取粗召回结果总数（支持筛选，用于分页）

        Args:
            table_name: 表名，默认使用 Config.RECALL_RESULTS_TABLE
            filters: 过滤条件字典

        Returns:
            int: 记录总数
        """
        table_name = table_name or Config.RECALL_RESULTS_TABLE
        return self._generic_get_count(table_name, filters, self._build_recall_filter_conditions)

    def get_recall_results_paginated(self, table_name=None, filters=None, page=1, page_size=20):
        """
        分页获取粗召回结果（支持筛选）

        Args:
            table_name: 表名，默认使用 Config.RECALL_RESULTS_TABLE
            filters: 过滤条件字典
            page: 页码（从1开始）
            page_size: 每页记录数

        Returns:
            DataFrame: 召回结果数据帧
        """
        table_name = table_name or Config.RECALL_RESULTS_TABLE

        return self._generic_get_paginated(
            table_name, filters, self._build_recall_filter_conditions,
            page=page, page_size=page_size, order_by='enterprise_id, similarity DESC, id ASC'
        )
    
    def truncate_recall_table(self, table_name=None):
        """
        清空粗召回结果表

        Args:
            table_name: 表名，默认使用 Config.RECALL_RESULTS_TABLE

        Returns:
            bool: 清空成功返回 True
        """
        table_name = table_name or Config.RECALL_RESULTS_TABLE
        return self._generic_truncate_table(table_name, log_label='Recall table ')
    
    def load_recall_results(self, table_name=None):
        """
        加载所有召回结果，用于MGeo精排
        
        Args:
            table_name: 表名，默认使用 Config.RECALL_RESULTS_TABLE
        
        Returns:
            list: 召回结果列表，每个元素包含 enterprise_id, enterprise_name, enterprise_address, candidates
        """
        table_name = table_name or Config.RECALL_RESULTS_TABLE
        sql = f"""
            SELECT 
                enterprise_id,
                enterprise_name,
                enterprise_address,
                standard_id,
                standard_address,
                room_no,
                similarity
            FROM {quote_identifier(table_name)}
            ORDER BY enterprise_id, similarity DESC
        """
        cursor = self.db.execute(sql)
        if not cursor:
            return []
        
        rows = cursor.fetchall()
        
        # 按企业分组组织数据
        recall_results = []
        current_enterprise = None
        current_item = None
        
        for row in rows:
            enterprise_id = row['enterprise_id']
            enterprise_name = row['enterprise_name']
            enterprise_address = row['enterprise_address']
            standard_id = row['standard_id']
            standard_address = row['standard_address']
            room_no = row['room_no']
            similarity = row['similarity']
            
            # 如果是一个新的企业
            if current_enterprise != enterprise_id:
                if current_item:
                    recall_results.append(current_item)
                
                current_enterprise = enterprise_id
                current_item = {
                    'enterprise_id': enterprise_id,
                    'enterprise_name': enterprise_name,
                    'enterprise_address': enterprise_address,
                    'candidates': []
                }
            
            # 添加候选地址
            if standard_id:  # 只添加有效的候选
                current_item['candidates'].append({
                    'source_id': standard_id,
                    'address': standard_address,
                    'room_no': room_no,
                    'similarity': similarity
                })
        
        # 添加最后一个企业
        if current_item:
            recall_results.append(current_item)
        
        logger.info(f"Loaded {len(recall_results)} recall results from database")
        return recall_results
    
    def create_result_table(self, table_name=None):
        """
        创建匹配结果表
        
        表结构:
            id: 主键
            enterprise_id: 企业标识
            enterprise_name: 企业名称
            enterprise_address: 企业地址
            address_id: 匹配到的标准地址编码
            standard_address: 匹配到的标准地址
            room_no: 房屋编码
            partial_match: 部分匹配概率（MGeo模型输出）
            exact_match: 精确匹配概率（MGeo模型输出）
            not_match: 不匹配概率（MGeo模型输出）
            match_status: 匹配状态（精确匹配/部分匹配/不匹配，由三个概率最大值决定）
            correction_source: 纠正来源（自动匹配/人工纠正/人工匹配）
            created_at: 创建时间
        
        Args:
            table_name: 表名，默认使用 Config.RESULT_TABLE
        
        Returns:
            bool: 创建成功返回 True
        """
        table_name = table_name or Config.RESULT_TABLE
        
        sql = f"""
            CREATE TABLE IF NOT EXISTS {quote_identifier(table_name)} (
                id SERIAL PRIMARY KEY,
                enterprise_id VARCHAR(255) NOT NULL,
                enterprise_name TEXT,
                enterprise_address TEXT,
                address_id VARCHAR(255),
                standard_address TEXT,
                room_no VARCHAR(100),
                partial_match DOUBLE PRECISION DEFAULT 0.0,
                exact_match DOUBLE PRECISION DEFAULT 0.0,
                not_match DOUBLE PRECISION DEFAULT 0.0,
                match_status VARCHAR(20) DEFAULT '不匹配',
                correction_source VARCHAR(20) DEFAULT '自动匹配',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """
        cursor = self.db.execute(sql)
        if cursor:
            self.db.commit()
            logger.info(f"Result table {table_name} created successfully")
        
        self._migrate_float_to_double(table_name)
        self._add_correction_source_column(table_name)
        
        return True
    
    def insert_match_results(self, results, table_name=None):
        """
        批量插入匹配结果
        
        Args:
            results: 匹配结果列表，每个元素包含 enterprise_id, enterprise_name, enterprise_address,
                     address_id, standard_address, room_no, partial_match, exact_match, not_match, match_status
            table_name: 表名，默认使用 Config.RESULT_TABLE
        
        Returns:
            int: 成功插入的记录数
        """
        table_name = table_name or Config.RESULT_TABLE
        if not results:
            return 0
        
        logger.debug(f"[insert_match_results] 准备插入 {len(results)} 条结果")
        
        for i, r in enumerate(results[:3]):
            logger.debug(f"[insert_match_results] 样本{i+1}: enterprise_id={r['enterprise_id']}, "
                       f"address_id={r['address_id']}, match_status={r['match_status']}, "
                       f"exact_match={r.get('exact_match', 0)}, partial_match={r.get('partial_match', 0)}, not_match={r.get('not_match', 0)}")
        
        sql = f"""
            INSERT INTO {quote_identifier(table_name)} 
            (enterprise_id, enterprise_name, enterprise_address, address_id, standard_address, room_no, 
             partial_match, exact_match, not_match, match_status)
            VALUES %s
        """
        
        try:
            values = [
                (
                    str(r['enterprise_id']),
                    r['enterprise_name'],
                    r['enterprise_address'],
                    str(r['address_id']) if r.get('address_id') is not None else None,
                    r['standard_address'],
                    r.get('room_no', ''),
                    float(r.get('partial_match', 0.0)),
                    float(r.get('exact_match', 0.0)),
                    float(r.get('not_match', 0.0)),
                    r['match_status']
                )
                for r in results
            ]
            
            cursor = self.db.get_cursor()
            if not cursor:
                raise Exception("获取数据库游标失败")
            try:
                psycopg2.extras.execute_values(
                    cursor, sql, values, template=None, page_size=1000
                )
            finally:
                cursor.close()
            self.db.commit()
            logger.info(f"Inserted {len(results)} match results into {table_name}")
            return len(results)
        except Exception as e:
            logger.error(f"Failed to insert match results: {str(e)}")
            import traceback
            logger.error(f"[insert_match_results] 详细堆栈: {traceback.format_exc()}")
            self.db.rollback()
            return 0
    
    def get_match_results(self, table_name=None, filters=None):
        """
        获取匹配结果（支持过滤条件）
        
        Args:
            table_name: 表名，默认使用 Config.RESULT_TABLE
            filters: 过滤条件字典，支持以下键:
                - match_status: 匹配状态过滤
                - min_exact_match: 最小精确匹配概率
                - max_exact_match: 最大精确匹配概率
                - min_partial_match: 最小部分匹配概率
                - max_partial_match: 最大部分匹配概率
                - min_not_match: 最小不匹配概率
                - max_not_match: 最大不匹配概率
                - keyword: 关键词搜索（企业名/企业地址/标准地址）
        
        Returns:
            DataFrame: 匹配结果数据帧
        """
        table_name = table_name or Config.RESULT_TABLE
        sql = f"SELECT * FROM {quote_identifier(table_name)}"
        params = None
        
        if filters:
            conditions, params = self._build_filter_conditions(filters)
            if conditions:
                sql += " WHERE " + " AND ".join(conditions)
        
        sql += " ORDER BY exact_match DESC, partial_match DESC"
        
        cursor = self.db.execute(sql, params)
        if cursor:
            rows = cursor.fetchall()
            return pd.DataFrame(rows)
        return pd.DataFrame()
    
    def _build_filter_conditions(self, filters):
        """
        构建筛选条件（公共方法，供多个查询方法复用）
        
        Args:
            filters: 过滤条件字典
        
        Returns:
            tuple: (conditions列表, params列表)
        """
        conditions = []
        params = []
        
        if 'match_status' in filters and filters['match_status']:
            conditions.append("match_status = %s")
            params.append(filters['match_status'])
        
        if 'min_exact_match' in filters and filters['min_exact_match']:
            conditions.append("exact_match >= %s")
            params.append(filters['min_exact_match'])
        
        if 'max_exact_match' in filters and filters['max_exact_match'] < 1.0:
            conditions.append("exact_match <= %s")
            params.append(filters['max_exact_match'])
        
        if 'min_partial_match' in filters and filters['min_partial_match']:
            conditions.append("partial_match >= %s")
            params.append(filters['min_partial_match'])
        
        if 'max_partial_match' in filters and filters['max_partial_match'] < 1.0:
            conditions.append("partial_match <= %s")
            params.append(filters['max_partial_match'])
        
        if 'min_not_match' in filters and filters['min_not_match']:
            conditions.append("not_match >= %s")
            params.append(filters['min_not_match'])
        
        if 'max_not_match' in filters and filters['max_not_match'] < 1.0:
            conditions.append("not_match <= %s")
            params.append(filters['max_not_match'])
        
        if 'keyword' in filters and filters['keyword']:
            conditions.append("(enterprise_name LIKE %s OR enterprise_address LIKE %s OR standard_address LIKE %s)")
            keyword = f"%{filters['keyword']}%"
            params.extend([keyword, keyword, keyword])
        
        if 'correction_source' in filters and filters['correction_source']:
            conditions.append("correction_source = %s")
            params.append(filters['correction_source'])
        
        return conditions, params

    def get_match_results_count(self, table_name=None, filters=None):
        """
        获取匹配结果总数（用于分页）

        Args:
            table_name: 表名，默认使用 Config.RESULT_TABLE
            filters: 过滤条件字典

        Returns:
            int: 记录总数
        """
        table_name = table_name or Config.RESULT_TABLE

        self.create_result_table(table_name)

        return self._generic_get_count(table_name, filters, self._build_filter_conditions)
    
    def get_match_results_paginated(self, table_name=None, filters=None, page=1, page_size=20):
        """
        分页获取匹配结果

        Args:
            table_name: 表名，默认使用 Config.RESULT_TABLE
            filters: 过滤条件字典
            page: 页码（从1开始）
            page_size: 每页记录数

        Returns:
            DataFrame: 匹配结果数据帧
        """
        table_name = table_name or Config.RESULT_TABLE

        self.create_result_table(table_name)

        return self._generic_get_paginated(
            table_name, filters, self._build_filter_conditions,
            page=page, page_size=page_size, order_by='exact_match DESC, partial_match DESC, id ASC'
        )
    
    def get_result_count(self, table_name=None):
        """
        获取匹配结果表记录数
        
        Args:
            table_name: 表名，默认使用 Config.RESULT_TABLE
        
        Returns:
            int: 记录数
        """
        table_name = table_name or Config.RESULT_TABLE
        sql = f"SELECT COUNT(*) as count FROM {quote_identifier(table_name)}"
        cursor = self.db.execute(sql)
        if cursor:
            result = cursor.fetchone()
            return result['count'] if result else 0
        return 0
    
    def _add_correction_source_column(self, table_name):
        """
        为已有的匹配结果表添加correction_source字段（兼容旧表）

        Args:
            table_name: 表名
        """
        try:
            schema = self.db.schema if hasattr(self.db, 'schema') else 'public'
            check_sql = f"""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_schema = %s AND table_name = %s AND column_name = 'correction_source'
            """
            cursor = self.db.execute(check_sql, (schema, table_name))
            if cursor:
                rows = cursor.fetchall()
                if not rows:
                    alter_sql = f"ALTER TABLE {quote_identifier(table_name)} ADD COLUMN correction_source VARCHAR(20) DEFAULT '自动匹配'"
                    self.db.execute(alter_sql)
                    self.db.commit()
                    logger.info(f"Added correction_source column to {table_name}")
        except Exception as e:
            logger.warning(f"Failed to add correction_source column: {e}")

    def _migrate_float_to_double(self, table_name):
        """
        将表中FLOAT类型的概率列迁移为DOUBLE PRECISION，避免精度丢失

        由于CREATE TABLE IF NOT EXISTS不会修改已有表的列类型，
        需要通过ALTER TABLE逐列修改。

        Args:
            table_name: 表名
        """
        float_columns = []
        try:
            schema = self.db.schema if hasattr(self.db, 'schema') else 'public'
            check_sql = f"""
                SELECT column_name, data_type 
                FROM information_schema.columns 
                WHERE table_schema = %s AND table_name = %s 
                AND column_name IN ('exact_match', 'partial_match', 'not_match', 'similarity')
            """
            cursor = self.db.execute(check_sql, (schema, table_name))
            if cursor:
                rows = cursor.fetchall()
                for row in rows:
                    if row['data_type'] == 'real':
                        float_columns.append(row['column_name'])
        except Exception:
            pass

        if float_columns:
            for col in float_columns:
                try:
                    alter_sql = f"ALTER TABLE {quote_identifier(table_name)} ALTER COLUMN {quote_identifier(col)} TYPE DOUBLE PRECISION"
                    self.db.execute(alter_sql)
                    logger.info(f"Migrated {table_name}.{col} from FLOAT to DOUBLE PRECISION")
                except Exception as e:
                    logger.warning(f"Failed to migrate {table_name}.{col}: {e}")
            try:
                self.db.commit()
            except Exception:
                pass

    def _migrate_mgeo_similarity_add_identifier(self, table_name):
        """
        为旧版 mgeo_similarity_results 表添加 identifier 列（如果不存在）

        Args:
            table_name: 表名
        """
        try:
            schema = self.db.schema if hasattr(self.db, 'schema') else 'public'
            check_sql = f"""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = %s AND table_name = %s
                AND column_name = 'identifier'
            """
            cursor = self.db.execute(check_sql, (schema, table_name))
            if cursor and cursor.fetchone():
                return

            alter_sql = f"ALTER TABLE {quote_identifier(table_name)} ADD COLUMN identifier TEXT"
            self.db.execute(alter_sql)
            self.db.commit()
            logger.info(f"Added identifier column to {table_name}")
        except Exception as e:
            logger.warning(f"Failed to add identifier column to {table_name}: {e}")

    def _migrate_mgeo_similarity_add_extra_col(self, table_name):
        """
        为旧版 mgeo_similarity_results 表添加 extra_col 列（如果不存在）

        Args:
            table_name: 表名
        """
        try:
            schema = self.db.schema if hasattr(self.db, 'schema') else 'public'
            check_sql = f"""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = %s AND table_name = %s
                AND column_name = 'extra_col'
            """
            cursor = self.db.execute(check_sql, (schema, table_name))
            if cursor and cursor.fetchone():
                return

            alter_sql = f"ALTER TABLE {quote_identifier(table_name)} ADD COLUMN extra_col TEXT"
            self.db.execute(alter_sql)
            self.db.commit()
            logger.info(f"Added extra_col column to {table_name}")
        except Exception as e:
            logger.warning(f"Failed to add extra_col column to {table_name}: {e}")

    def truncate_result_table(self, table_name=None):
        """
        清空匹配结果表

        Args:
            table_name: 表名，默认使用 Config.RESULT_TABLE

        Returns:
            bool: 清空成功返回 True
        """
        table_name = table_name or Config.RESULT_TABLE
        return self._generic_truncate_table(table_name, log_label='Result table ')
    
    def export_recall_results_batch(self, batch_size=5000, table_name=None):
        """
        批量加载粗召回结果用于导出（避免一次性加载导致内存溢出）
        
        Args:
            batch_size: 每批加载的记录数
            table_name: 表名，默认使用 Config.RECALL_RESULTS_TABLE
        
        Yields:
            DataFrame: 每批召回结果数据帧
        """
        table_name = table_name or Config.RECALL_RESULTS_TABLE
        count_sql = f"SELECT COUNT(*) as count FROM {quote_identifier(table_name)}"
        count_cursor = self.db.execute(count_sql)
        total = count_cursor.fetchone()['count'] if count_cursor else 0
        
        if total == 0:
            return
        
        offset = 0
        while offset < total:
            sql = f"SELECT * FROM {quote_identifier(table_name)} ORDER BY id LIMIT {batch_size} OFFSET {offset}"
            cursor = self.db.execute(sql)
            if cursor:
                rows = cursor.fetchall()
                if rows:
                    yield pd.DataFrame(rows)
            offset += batch_size
    
    def create_mgeo_similarity_table(self, table_name=None):
        """
        创建MGeo地址相似度匹配结果表

        表结构:
            id: 主键
            identifier: 标识字段
            extra_col: 其他附加字段
            address_a: 地址A
            address_b: 地址B
            exact_match: 精确匹配概率
            partial_match: 部分匹配概率
            not_match: 不匹配概率
            match_status: 匹配状态（精确匹配/部分匹配/不匹配）
            created_at: 创建时间

        Args:
            table_name: 表名，默认使用 Config.MGEO_SIMILARITY_RESULTS_TABLE

        Returns:
            bool: 创建成功返回 True
        """
        table_name = table_name or Config.MGEO_SIMILARITY_RESULTS_TABLE

        sql = f"""
            CREATE TABLE IF NOT EXISTS {quote_identifier(table_name)} (
                id SERIAL PRIMARY KEY,
                identifier TEXT,
                extra_col TEXT,
                address_a TEXT,
                address_b TEXT,
                exact_match DOUBLE PRECISION DEFAULT 0.0,
                partial_match DOUBLE PRECISION DEFAULT 0.0,
                not_match DOUBLE PRECISION DEFAULT 0.0,
                match_status VARCHAR(20) DEFAULT '不匹配',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """
        cursor = self.db.execute(sql)
        if cursor:
            self.db.commit()
            logger.info(f"MGeo similarity result table {table_name} created successfully")

        self._migrate_float_to_double(table_name)
        self._migrate_mgeo_similarity_add_identifier(table_name)
        self._migrate_mgeo_similarity_add_extra_col(table_name)

        return True

    def insert_mgeo_similarity_results(self, results, table_name=None):
        """
        批量插入MGeo地址相似度匹配结果

        Args:
            results: 匹配结果列表，每个元素包含 address_a, address_b, identifier, extra_col,
                     exact_match, partial_match, not_match, match_status
            table_name: 表名，默认使用 Config.MGEO_SIMILARITY_RESULTS_TABLE

        Returns:
            int: 成功插入的记录数
        """
        table_name = table_name or Config.MGEO_SIMILARITY_RESULTS_TABLE
        if not results:
            return 0

        sql = f"""
            INSERT INTO {quote_identifier(table_name)}
            (address_a, address_b, identifier, extra_col, exact_match, partial_match, not_match, match_status)
            VALUES %s
        """

        try:
            values = [
                (
                    r['address_a'],
                    r['address_b'],
                    r.get('identifier'),
                    r.get('extra_col'),
                    float(r.get('exact_match', 0.0)),
                    float(r.get('partial_match', 0.0)),
                    float(r.get('not_match', 0.0)),
                    r['match_status']
                )
                for r in results
            ]

            cursor = self.db.get_cursor()
            if not cursor:
                raise Exception("获取数据库游标失败")
            try:
                psycopg2.extras.execute_values(
                    cursor, sql, values, template=None, page_size=1000
                )
            finally:
                cursor.close()
            self.db.commit()
            logger.info(f"Inserted {len(results)} MGeo similarity results into {table_name}")
            return len(results)
        except Exception as e:
            logger.error(f"Failed to insert MGeo similarity results: {str(e)}")
            self.db.rollback()
            return 0

    def truncate_mgeo_similarity_table(self, table_name=None):
        """
        清空MGeo地址相似度匹配结果表

        Args:
            table_name: 表名，默认使用 Config.MGEO_SIMILARITY_RESULTS_TABLE

        Returns:
            bool: 清空成功返回 True
        """
        table_name = table_name or Config.MGEO_SIMILARITY_RESULTS_TABLE
        return self._generic_truncate_table(table_name, log_label='MGeo similarity table ')

    def get_mgeo_similarity_results_count(self, table_name=None, filters=None):
        """
        获取MGeo地址相似度匹配结果总数

        Args:
            table_name: 表名，默认使用 Config.MGEO_SIMILARITY_RESULTS_TABLE
            filters: 过滤条件字典

        Returns:
            int: 记录总数
        """
        table_name = table_name or Config.MGEO_SIMILARITY_RESULTS_TABLE

        self.create_mgeo_similarity_table(table_name)

        return self._generic_get_count(table_name, filters, self._build_mgeo_similarity_filter_conditions)

    def get_mgeo_similarity_results_paginated(self, table_name=None, filters=None, page=1, page_size=20):
        """
        分页获取MGeo地址相似度匹配结果

        Args:
            table_name: 表名，默认使用 Config.MGEO_SIMILARITY_RESULTS_TABLE
            filters: 过滤条件字典
            page: 页码（从1开始）
            page_size: 每页记录数

        Returns:
            DataFrame: 匹配结果数据帧
        """
        table_name = table_name or Config.MGEO_SIMILARITY_RESULTS_TABLE

        self.create_mgeo_similarity_table(table_name)

        return self._generic_get_paginated(
            table_name, filters, self._build_mgeo_similarity_filter_conditions,
            page=page, page_size=page_size, order_by='exact_match DESC, partial_match DESC, id ASC'
        )

    def get_mgeo_similarity_statistics(self, table_name=None):
        """
        获取MGeo地址相似度匹配统计信息

        Args:
            table_name: 表名，默认使用 Config.MGEO_SIMILARITY_RESULTS_TABLE

        Returns:
            dict: 统计信息字典
        """
        table_name = table_name or Config.MGEO_SIMILARITY_RESULTS_TABLE

        self.create_mgeo_similarity_table(table_name)

        count_exprs = """SUM(CASE WHEN match_status = '精确匹配' THEN 1 ELSE 0 END) as exact_match_count,
                SUM(CASE WHEN match_status = '部分匹配' THEN 1 ELSE 0 END) as partial_match_count,
                SUM(CASE WHEN match_status = '不匹配' THEN 1 ELSE 0 END) as not_match_count,
                AVG(exact_match) as avg_exact_match,
                AVG(partial_match) as avg_partial_match,
                AVG(not_match) as avg_not_match"""

        default_stats = {
            'total_count': 0, 'exact_match_count': 0, 'partial_match_count': 0,
            'not_match_count': 0, 'match_rate': 0, 'exact_match_rate': 0,
            'partial_match_rate': 0, 'not_match_rate': 0,
            'avg_exact_match': 0.0, 'avg_partial_match': 0.0, 'avg_not_match': 0.0
        }

        result, total = self._generic_get_statistics(table_name, count_exprs, default_stats)
        if result is None:
            return default_stats

        exact_count = result['exact_match_count'] if result else 0
        partial_count = result['partial_match_count'] if result else 0
        not_count = result['not_match_count'] if result else 0
        return {
            'total_count': total,
            'exact_match_count': exact_count,
            'partial_match_count': partial_count,
            'not_match_count': not_count,
            'match_rate': ((exact_count + partial_count) / total * 100) if total > 0 else 0,
            'exact_match_rate': (exact_count / total * 100) if total > 0 else 0,
            'partial_match_rate': (partial_count / total * 100) if total > 0 else 0,
            'not_match_rate': (not_count / total * 100) if total > 0 else 0,
            'avg_exact_match': float(result['avg_exact_match']) if result and result['avg_exact_match'] else 0.0,
            'avg_partial_match': float(result['avg_partial_match']) if result and result['avg_partial_match'] else 0.0,
            'avg_not_match': float(result['avg_not_match']) if result and result['avg_not_match'] else 0.0
        }

    def export_mgeo_similarity_results_batch(self, table_name=None, filters=None, batch_size=5000):
        """
        批量加载MGeo地址相似度匹配结果用于导出

        Args:
            table_name: 表名，默认使用 Config.MGEO_SIMILARITY_RESULTS_TABLE
            filters: 过滤条件字典
            batch_size: 每批加载的记录数

        Yields:
            DataFrame: 每批匹配结果数据帧
        """
        table_name = table_name or Config.MGEO_SIMILARITY_RESULTS_TABLE
        self.create_mgeo_similarity_table(table_name)

        yield from self._generic_export_batch(
            table_name, filters, self._build_mgeo_similarity_filter_conditions,
            self.get_mgeo_similarity_results_count,
            self.get_mgeo_similarity_results_paginated,
            batch_size=batch_size
        )

    def create_address_tagging_table(self, table_name=None):
        """
        创建地址结构化解析结果表

        表结构:
            id: 主键
            original_address: 原始地址
            province: 省
            city: 城市
            district: 区划
            street: 街道
            community: 社区
            road: 街路巷名、道、路
            roadno: 门楼牌、门牌号、路号
            area: 片区、地物名、居民小区名、自然村名、专属区域名
            bldg: 建筑物名、楼栋
            unit: 单元
            floor: 楼层名
            house: 户室号、房间
            created_at: 创建时间

        Args:
            table_name: 表名，默认使用 Config.ADDRESS_TAGGING_RESULTS_TABLE

        Returns:
            bool: 创建成功返回 True
        """
        table_name = table_name or Config.ADDRESS_TAGGING_RESULTS_TABLE

        sql = f"""
            CREATE TABLE IF NOT EXISTS {quote_identifier(table_name)} (
                id SERIAL PRIMARY KEY,
                original_address TEXT,
                province VARCHAR(100) DEFAULT '',
                city VARCHAR(100) DEFAULT '',
                district VARCHAR(100) DEFAULT '',
                street VARCHAR(100) DEFAULT '',
                community VARCHAR(100) DEFAULT '',
                road VARCHAR(200) DEFAULT '',
                roadno VARCHAR(100) DEFAULT '',
                area VARCHAR(200) DEFAULT '',
                bldg VARCHAR(200) DEFAULT '',
                unit VARCHAR(200) DEFAULT '',
                floor VARCHAR(200) DEFAULT '',
                house VARCHAR(200) DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """
        cursor = self.db.execute(sql)
        if cursor:
            self.db.commit()
            logger.info(f"Address tagging result table {table_name} created successfully")

        # 为原始地址添加索引，加速副本表JOIN和结果查询
        try:
            index_sql = f"CREATE INDEX IF NOT EXISTS idx_{table_name}_original_address ON {quote_identifier(table_name)}(original_address)"
            self.db.execute(index_sql)
            self.db.commit()
        except Exception as e:
            logger.warning(f"Failed to create index on {table_name}.original_address: {e}")

        return True

    def truncate_address_tagging_table(self, table_name=None):
        """
        清空地址结构化解析结果表

        Args:
            table_name: 表名，默认使用 Config.ADDRESS_TAGGING_RESULTS_TABLE

        Returns:
            bool: 清空成功返回 True
        """
        table_name = table_name or Config.ADDRESS_TAGGING_RESULTS_TABLE
        return self._generic_truncate_table(table_name, log_label='Address tagging table ')

    def insert_address_tagging_results(self, results, table_name=None):
        """
        批量插入地址结构化解析结果

        Args:
            results: 解析结果列表，每个元素包含 original_address 和12级结构化字段
            table_name: 表名，默认使用 Config.ADDRESS_TAGGING_RESULTS_TABLE

        Returns:
            int: 成功插入的记录数
        """
        table_name = table_name or Config.ADDRESS_TAGGING_RESULTS_TABLE
        if not results:
            return 0

        sql = f"""
            INSERT INTO {quote_identifier(table_name)}
            (original_address, province, city, district, street, community,
             road, roadno, area, bldg, unit, floor, house)
            VALUES %s
        """

        try:
            values = [
                (
                    r.get('original_address', ''),
                    r.get('province', ''),
                    r.get('city', ''),
                    r.get('district', ''),
                    r.get('street', ''),
                    r.get('community', ''),
                    r.get('road', ''),
                    r.get('roadno', ''),
                    r.get('area', ''),
                    r.get('bldg', ''),
                    r.get('unit', ''),
                    r.get('floor', ''),
                    r.get('house', '')
                )
                for r in results
            ]

            cursor = self.db.get_cursor()
            if not cursor:
                raise Exception("获取数据库游标失败")
            try:
                psycopg2.extras.execute_values(
                    cursor, sql, values, template=None, page_size=1000
                )
            finally:
                cursor.close()
            self.db.commit()
            logger.info(f"Inserted {len(results)} address tagging results into {table_name}")
            return len(results)
        except Exception as e:
            logger.error(f"Failed to insert address tagging results: {str(e)}")
            self.db.rollback()
            return 0

    def get_address_tagging_results_count(self, table_name=None, filters=None):
        """
        获取地址结构化解析结果总数

        Args:
            table_name: 表名，默认使用 Config.ADDRESS_TAGGING_RESULTS_TABLE
            filters: 过滤条件字典

        Returns:
            int: 记录总数
        """
        table_name = table_name or Config.ADDRESS_TAGGING_RESULTS_TABLE

        self.create_address_tagging_table(table_name)

        return self._generic_get_count(table_name, filters, self._build_address_tagging_filter_conditions)

    def get_address_tagging_results_paginated(self, table_name=None, filters=None, page=1, page_size=20):
        """
        分页获取地址结构化解析结果

        Args:
            table_name: 表名，默认使用 Config.ADDRESS_TAGGING_RESULTS_TABLE
            filters: 过滤条件字典
            page: 页码（从1开始）
            page_size: 每页记录数

        Returns:
            DataFrame: 解析结果数据帧
        """
        table_name = table_name or Config.ADDRESS_TAGGING_RESULTS_TABLE

        self.create_address_tagging_table(table_name)

        return self._generic_get_paginated(
            table_name, filters, self._build_address_tagging_filter_conditions,
            page=page, page_size=page_size, order_by='id'
        )

    def get_address_tagging_statistics(self, table_name=None):
        """
        获取地址结构化解析统计信息

        Args:
            table_name: 表名，默认使用 Config.ADDRESS_TAGGING_RESULTS_TABLE

        Returns:
            dict: 统计信息字典
        """
        table_name = table_name or Config.ADDRESS_TAGGING_RESULTS_TABLE

        self.create_address_tagging_table(table_name)

        fields = ['province', 'city', 'district', 'street', 'community',
                   'road', 'roadno', 'area', 'bldg', 'unit', 'floor', 'house']
        count_exprs = ', '.join([
            f"SUM(CASE WHEN {quote_identifier(f)} IS NOT NULL AND {quote_identifier(f)} != '' THEN 1 ELSE 0 END) as {f}_count"
            for f in fields
        ])

        default_stats = {'total_count': 0}
        for f in fields:
            default_stats[f'{f}_count'] = 0
            default_stats[f'{f}_rate'] = 0

        result, total = self._generic_get_statistics(table_name, count_exprs, default_stats)
        if result is None:
            return default_stats

        stats = {'total_count': total}
        for f in fields:
            count = result[f'{f}_count'] if result else 0
            stats[f'{f}_count'] = count
            stats[f'{f}_rate'] = (count / total * 100) if total > 0 else 0
        return stats

    def _build_address_tagging_filter_conditions(self, filters):
        """
        构建地址结构化解析结果的筛选条件

        Args:
            filters: 过滤条件字典

        Returns:
            tuple: (conditions列表, params列表)
        """
        conditions = []
        params = []

        if 'keyword' in filters and filters['keyword']:
            keyword = f"%{filters['keyword']}%"
            conditions.append(
                "(original_address LIKE %s OR province LIKE %s OR city LIKE %s "
                "OR district LIKE %s OR road LIKE %s OR area LIKE %s)"
            )
            params.extend([keyword, keyword, keyword, keyword, keyword, keyword])

        if 'has_province' in filters and filters['has_province']:
            conditions.append("province IS NOT NULL AND province != ''")
        if 'has_city' in filters and filters['has_city']:
            conditions.append("city IS NOT NULL AND city != ''")
        if 'has_district' in filters and filters['has_district']:
            conditions.append("district IS NOT NULL AND district != ''")

        return conditions, params

    def export_address_tagging_results_batch(self, table_name=None, filters=None, batch_size=5000):
        """
        批量加载地址结构化解析结果用于导出

        Args:
            table_name: 表名，默认使用 Config.ADDRESS_TAGGING_RESULTS_TABLE
            filters: 过滤条件字典
            batch_size: 每批加载的记录数

        Yields:
            DataFrame: 每批解析结果数据帧
        """
        table_name = table_name or Config.ADDRESS_TAGGING_RESULTS_TABLE
        self.create_address_tagging_table(table_name)

        yield from self._generic_export_batch(
            table_name, filters, self._build_address_tagging_filter_conditions,
            self.get_address_tagging_results_count,
            self.get_address_tagging_results_paginated,
            batch_size=batch_size
        )

    def create_tagging_copy_table(self, source_table, address_col, results, table_suffix='_tagging'):
        """
        基于原始表创建_tagging副本表，包含原始数据及12级结构化解析字段

        Args:
            source_table: 原始表名
            address_col: 地址字段名
            results: 解析结果列表
            table_suffix: 副本表后缀，默认 '_tagging'

        Returns:
            str: 创建的副本表名，失败返回 None
        """
        copy_table = f"{source_table}{table_suffix}"

        try:
            drop_sql = f"DROP TABLE IF EXISTS {quote_identifier(copy_table)}"
            self.db.execute(drop_sql)
            self.db.commit()

            tagging_fields = ['province', 'city', 'district', 'street', 'community',
                              'road', 'roadno', 'area', 'bldg', 'unit', 'floor', 'house']
            # 保留源表全部字段（与 create_tagging_17_copy_table 保持一致），
            # 副本表可用于后续业务分析，不只局限于分词结果查看
            field_type_map = {
                'province': 'VARCHAR(100)', 'city': 'VARCHAR(100)', 'district': 'VARCHAR(100)',
                'street': 'VARCHAR(100)', 'community': 'VARCHAR(100)',
                'road': 'VARCHAR(200)', 'roadno': 'VARCHAR(100)',
                'area': 'VARCHAR(200)', 'bldg': 'VARCHAR(200)',
                'unit': 'VARCHAR(200)', 'floor': 'VARCHAR(200)', 'house': 'VARCHAR(200)',
            }
            create_sql = f"CREATE TABLE {quote_identifier(copy_table)} AS SELECT * FROM {quote_identifier(source_table)}"
            self.db.execute(create_sql)
            self.db.commit()

            # 添加12级分词字段（如源表已有同名列则跳过，用IF NOT EXISTS保证幂等）
            for f in tagging_fields:
                alter_sql = f"ALTER TABLE {quote_identifier(copy_table)} ADD COLUMN IF NOT EXISTS {quote_identifier(f)} {field_type_map[f]} DEFAULT ''"
                self.db.execute(alter_sql)
            self.db.commit()

            if results:
                set_clause = ', '.join([f"{quote_identifier(f)} = %s" for f in tagging_fields])
                update_sql = f"UPDATE {quote_identifier(copy_table)} SET {set_clause} WHERE {quote_identifier(address_col)} = %s"
                batch_size = 500
                for i in range(0, len(results), batch_size):
                    batch = results[i:i + batch_size]
                    for r in batch:
                        values = [r.get(f, '') for f in tagging_fields]
                        values.append(r.get('original_address', ''))
                        self.db.execute(update_sql, tuple(values))
                    self.db.commit()
                    logger.info(f"Tagging copy table update progress: {min(i + batch_size, len(results))}/{len(results)}")

            logger.info(f"Tagging copy table {copy_table} created successfully with {len(results)} tagging results")
            return copy_table

        except Exception as e:
            logger.error(f"Failed to create tagging copy table: {str(e)}")
            import traceback
            logger.error(f"详细堆栈: {traceback.format_exc()}")
            self.db.rollback()
            return None

    # ==================== 17级地址结构化解析结果管理 ====================

    def _tagging_17_fields(self):
        """17级输出字段列表"""
        return ['prov', 'city', 'district', 'town', 'road', 'roadno', 'intersection',
                'poi', 'subpoi', 'houseno', 'cellno', 'floorno', 'community',
                'assist', 'distance', 'devzone', 'village_group']

    def create_address_tagging_17_table(self, table_name=None):
        """
        创建17级地址结构化解析结果表

        Args:
            table_name: 表名，默认使用 Config.ADDRESS_TAGGING_17_RESULTS_TABLE

        Returns:
            bool: 创建成功返回 True
        """
        table_name = table_name or Config.ADDRESS_TAGGING_17_RESULTS_TABLE

        sql = f"""
            CREATE TABLE IF NOT EXISTS {quote_identifier(table_name)} (
                id SERIAL PRIMARY KEY,
                _id_field TEXT DEFAULT '',
                dom_json TEXT DEFAULT '',
                original_address TEXT,
                prov VARCHAR(100) DEFAULT '',
                city VARCHAR(100) DEFAULT '',
                district VARCHAR(100) DEFAULT '',
                town VARCHAR(100) DEFAULT '',
                road VARCHAR(200) DEFAULT '',
                roadno VARCHAR(100) DEFAULT '',
                intersection VARCHAR(200) DEFAULT '',
                poi VARCHAR(300) DEFAULT '',
                subpoi VARCHAR(200) DEFAULT '',
                houseno VARCHAR(200) DEFAULT '',
                cellno VARCHAR(100) DEFAULT '',
                floorno VARCHAR(100) DEFAULT '',
                community VARCHAR(200) DEFAULT '',
                assist VARCHAR(300) DEFAULT '',
                distance VARCHAR(100) DEFAULT '',
                devzone VARCHAR(200) DEFAULT '',
                village_group VARCHAR(200) DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """
        cursor = self.db.execute(sql)
        if cursor:
            self.db.commit()
            logger.info(f"17级地址结构化解析结果表 {table_name} 创建成功")

        return True

    def truncate_address_tagging_17_table(self, table_name=None):
        """清空17级地址结构化解析结果表"""
        table_name = table_name or Config.ADDRESS_TAGGING_17_RESULTS_TABLE
        return self._generic_truncate_table(table_name, log_label='17级地址结构化解析结果表 ')

    def insert_address_tagging_17_results(self, results, table_name=None):
        """
        批量插入17级地址结构化解析结果

        Args:
            results: 解析结果列表
            table_name: 表名

        Returns:
            int: 成功插入的记录数
        """
        table_name = table_name or Config.ADDRESS_TAGGING_17_RESULTS_TABLE
        if not results:
            return 0

        fields = self._tagging_17_fields()
        columns = ['_id_field', 'dom_json', 'original_address'] + fields
        sql = f"INSERT INTO {quote_identifier(table_name)} ({', '.join(quote_identifier(c) for c in columns)}) VALUES %s"

        try:
            values = [
                tuple(
                    [r.get('_id_field', '')] +
                    [r.get('dom_json', '')] +
                    [r.get('original_address', '')] +
                    [r.get(f, '') for f in fields]
                )
                for r in results
            ]
            cursor = self.db.get_cursor()
            if not cursor:
                raise Exception("获取数据库游标失败")
            try:
                psycopg2.extras.execute_values(
                    cursor, sql, values, template=None, page_size=1000
                )
            finally:
                cursor.close()
            self.db.commit()
            logger.info(f"已插入 {len(results)} 条17级地址结构化解析结果到 {table_name}")
            return len(results)
        except Exception as e:
            logger.error(f"插入17级地址结构化解析结果失败: {str(e)}")
            self.db.rollback()
            return 0

    def get_address_tagging_17_results_count(self, table_name=None, filters=None):
        """获取17级地址结构化解析结果总数"""
        table_name = table_name or Config.ADDRESS_TAGGING_17_RESULTS_TABLE
        self.create_address_tagging_17_table(table_name)

        return self._generic_get_count(table_name, filters, self._build_address_tagging_17_filter_conditions)

    def get_address_tagging_17_results_paginated(self, table_name=None, filters=None, page=1, page_size=20):
        """分页获取17级地址结构化解析结果"""
        table_name = table_name or Config.ADDRESS_TAGGING_17_RESULTS_TABLE
        self.create_address_tagging_17_table(table_name)

        return self._generic_get_paginated(
            table_name, filters, self._build_address_tagging_17_filter_conditions,
            page=page, page_size=page_size, order_by='id'
        )

    def get_address_tagging_17_statistics(self, table_name=None):
        """获取17级地址结构化解析统计信息"""
        table_name = table_name or Config.ADDRESS_TAGGING_17_RESULTS_TABLE
        self.create_address_tagging_17_table(table_name)

        fields = self._tagging_17_fields()
        count_exprs = ', '.join([
            f"SUM(CASE WHEN {quote_identifier(f)} IS NOT NULL AND {quote_identifier(f)} != '' THEN 1 ELSE 0 END) as {f}_count"
            for f in fields
        ])

        default_stats = {'total_count': 0}
        for f in fields:
            default_stats[f'{f}_count'] = 0
            default_stats[f'{f}_rate'] = 0

        result, total = self._generic_get_statistics(table_name, count_exprs, default_stats)
        if result is None:
            return default_stats

        stats = {'total_count': total}
        for f in fields:
            count = result[f'{f}_count'] if result else 0
            stats[f'{f}_count'] = count
            stats[f'{f}_rate'] = (count / total * 100) if total > 0 else 0
        return stats

    def _build_address_tagging_17_filter_conditions(self, filters):
        """构建17级地址结构化解析结果的筛选条件"""
        conditions = []
        params = []
        if 'keyword' in filters and filters['keyword']:
            keyword = f"%{filters['keyword']}%"
            conditions.append(
                "(original_address LIKE %s OR prov LIKE %s OR city LIKE %s "
                "OR district LIKE %s OR road LIKE %s OR poi LIKE %s)"
            )
            params.extend([keyword, keyword, keyword, keyword, keyword, keyword])
        if 'has_province' in filters and filters['has_province']:
            conditions.append("prov IS NOT NULL AND prov != ''")
        return conditions, params

    def export_address_tagging_17_results_batch(self, table_name=None, filters=None, batch_size=5000):
        """批量加载17级地址结构化解析结果用于导出"""
        table_name = table_name or Config.ADDRESS_TAGGING_17_RESULTS_TABLE

        yield from self._generic_export_batch(
            table_name, filters, self._build_address_tagging_17_filter_conditions,
            self.get_address_tagging_17_results_count,
            self.get_address_tagging_17_results_paginated,
            batch_size=batch_size
        )

    def create_tagging_17_copy_table(self, source_table, address_col, results, table_suffix='_tagging_17'):
        """
        基于原始表创建17级_tagging副本表

        Args:
            source_table: 原始表名
            address_col: 地址字段名
            results: 解析结果列表
            table_suffix: 副本表后缀，默认 '_tagging_17'

        Returns:
            str: 创建的副本表名，失败返回 None
        """
        copy_table = f"{source_table}{table_suffix}"

        try:
            drop_sql = f"DROP TABLE IF EXISTS {quote_identifier(copy_table)}"
            self.db.execute(drop_sql)
            self.db.commit()

            create_sql = f"CREATE TABLE {quote_identifier(copy_table)} AS SELECT * FROM {quote_identifier(source_table)}"
            self.db.execute(create_sql)
            self.db.commit()

            for field in self._tagging_17_fields():
                alter_sql = f"ALTER TABLE {quote_identifier(copy_table)} ADD COLUMN IF NOT EXISTS {quote_identifier(field)} VARCHAR(300) DEFAULT ''"
                self.db.execute(alter_sql)
            self.db.commit()

            if results:
                fields = self._tagging_17_fields()
                set_clause = ', '.join([f"{quote_identifier(f)} = %s" for f in fields])
                update_sql = f"UPDATE {quote_identifier(copy_table)} SET {set_clause} WHERE {quote_identifier(address_col)} = %s"
                batch_size = 500
                for i in range(0, len(results), batch_size):
                    batch = results[i:i + batch_size]
                    for r in batch:
                        values = [r.get(f, '') for f in fields]
                        values.append(r.get('original_address', ''))
                        self.db.execute(update_sql, tuple(values))
                    self.db.commit()
                    logger.info(f"17级副本表更新进度: {min(i + batch_size, len(results))}/{len(results)}")

            logger.info(f"17级副本表 {copy_table} 创建成功，包含 {len(results)} 条解析结果")
            return copy_table

        except Exception as e:
            logger.error(f"创建17级副本表失败: {str(e)}")
            import traceback
            logger.error(f"详细堆栈: {traceback.format_exc()}")
            self.db.rollback()
            return None

    # ==================== SQL JOIN 方式创建副本表（流式处理用） ====================

    def _ensure_result_table_index(self, result_table):
        """确保结果表 original_address 上有索引，加速副本表 JOIN 查询"""
        index_name = f"idx_{result_table}_orig_addr"
        check_sql = f"""
            SELECT 1 FROM pg_indexes
            WHERE indexname = %s AND tablename = %s
        """
        try:
            cursor = self.db.execute(check_sql, (index_name, result_table))
            if cursor and cursor.fetchone():
                return  # 索引已存在
            create_idx_sql = f"""
                CREATE INDEX {quote_identifier(index_name)}
                ON {quote_identifier(result_table)} (original_address)
            """
            self.db.execute(create_idx_sql)
            self.db.commit()
            logger.info(f"已为结果表 {result_table} 创建 original_address 索引")
        except Exception as e:
            logger.warning(f"创建结果表索引失败（不影响功能，仅影响副本表创建速度）: {e}")

    def _get_table_row_count(self, table_name):
        """获取表的行数（使用估算值以避免慢查询）"""
        try:
            # pg_class.reltuples 是 ANALYZE 后的估算行数，速度极快
            sql = """
                SELECT reltuples::bigint FROM pg_class
                WHERE relname = %s
            """
            cursor = self.db.execute(sql, (table_name,))
            if cursor:
                row = cursor.fetchone()
                if row and row.get('reltuples', 0) > 0:
                    return row['reltuples']
            # 估算值不准确时回退到精确计数
            count_sql = f"SELECT COUNT(*) as cnt FROM {quote_identifier(table_name)}"
            cursor = self.db.execute(count_sql)
            if cursor:
                return cursor.fetchone()['cnt']
        except Exception:
            pass
        return 0

    def create_tagging_copy_table_from_result(self, source_table, address_col,
                                                result_table, table_suffix='_tagging'):
        """
        使用 SQL JOIN 从结果表创建副本表（无需在内存中累积全部结果）

        适用于流式处理场景：结果已分批写入 result_table，
        直接通过 JOIN 将源表与结果表合并生成副本表。

        设计要点：
            1. 使用 LEFT JOIN LATERAL ... LIMIT 1 避免源表地址重复时行数膨胀
               （普通 LEFT JOIN 在源表存在 M 条相同地址、结果表存在 N 条匹配时
               会产生 M×N 行，导致副本表行数远超源表）
            2. 保留源表全部字段（s.*），副本表可用于后续业务分析，
               不只局限于分词结果查看
            3. 自动创建 original_address 索引加速 JOIN
            4. 千万级大表也可执行，通过结果表索引保证 JOIN 效率，创建耗时随数据量增长

        Args:
            source_table: 原始表名
            address_col: 地址字段名
            result_table: 已写入的结果表名
            table_suffix: 副本表后缀

        Returns:
            str: 副本表名，失败返回 None
        """
        source_count = self._get_table_row_count(source_table)
        logger.info(
            f"开始创建12级副本表，源表 {source_table} 约 {source_count:,} 行，"
            f"结果表 {result_table}，大表创建可能需要较长时间"
        )
        start_time = time.time()

        copy_table = f"{source_table}{table_suffix}"
        tagging_fields = ['province', 'city', 'district', 'street', 'community',
                          'road', 'roadno', 'area', 'bldg', 'unit', 'floor', 'house']

        try:
            # 确保结果表有索引加速 JOIN
            self._ensure_result_table_index(result_table)

            drop_sql = f"DROP TABLE IF EXISTS {quote_identifier(copy_table)}"
            self.db.execute(drop_sql)
            self.db.commit()

            # LATERAL子查询别名用 t，内部结果表别名用 r，避免别名冲突
            # LIMIT 1 确保源表每行最多匹配结果表一条记录，避免地址重复时行数膨胀
            r_columns = ', '.join([f"r.{quote_identifier(f)}" for f in tagging_fields])
            t_columns = ', '.join([f"t.{quote_identifier(f)}" for f in tagging_fields])
            create_sql = f"""
                CREATE TABLE {quote_identifier(copy_table)} AS
                SELECT s.*, {t_columns}
                FROM {quote_identifier(source_table)} s
                LEFT JOIN LATERAL (
                    SELECT {r_columns}
                    FROM {quote_identifier(result_table)} r
                    WHERE r.original_address = s.{quote_identifier(address_col)}
                    LIMIT 1
                ) t ON TRUE
            """
            self.db.execute(create_sql)
            self.db.commit()

            elapsed = time.time() - start_time
            logger.info(
                f"副本表 {copy_table} 通过SQL JOIN创建成功"
                f"（源表={source_table}, 结果表={result_table}, 耗时 {elapsed:.2f}s）"
            )
            return copy_table

        except Exception as e:
            logger.error(f"SQL JOIN创建副本表失败: {str(e)}")
            import traceback
            logger.error(f"详细堆栈: {traceback.format_exc()}")
            self.db.rollback()
            return None

    def create_tagging_17_copy_table_from_result(self, source_table, address_col,
                                                   result_table, table_suffix='_tagging_17'):
        """
        使用 SQL JOIN 从17级结果表创建副本表

        设计要点：使用 LEFT JOIN LATERAL ... LIMIT 1 避免源表地址重复时行数膨胀
            （普通 LEFT JOIN 在源表存在 M 条相同地址、结果表存在 N 条匹配时
             会产生 M×N 行，导致副本表行数远超源表）

        Args:
            source_table: 原始表名
            address_col: 地址字段名
            result_table: 17级结果表名
            table_suffix: 副本表后缀

        Returns:
            str: 副本表名，失败返回 None
        """
        source_count = self._get_table_row_count(source_table)
        logger.info(
            f"开始创建17级副本表，源表 {source_table} 约 {source_count:,} 行，"
            f"结果表 {result_table}，大表创建可能需要较长时间"
        )
        start_time = time.time()

        copy_table = f"{source_table}{table_suffix}"
        fields = self._tagging_17_fields()
        join_fields = ['_id_field', 'dom_json'] + fields

        try:
            # 确保结果表有索引加速 JOIN
            self._ensure_result_table_index(result_table)

            drop_sql = f"DROP TABLE IF EXISTS {quote_identifier(copy_table)}"
            self.db.execute(drop_sql)
            self.db.commit()

            # LATERAL子查询别名用 t，内部结果表别名用 r，避免别名冲突
            r_columns = ', '.join([f"r.{quote_identifier(f)}" for f in join_fields])
            t_columns = ', '.join([f"t.{quote_identifier(f)}" for f in join_fields])
            create_sql = f"""
                CREATE TABLE {quote_identifier(copy_table)} AS
                SELECT s.*, {t_columns}
                FROM {quote_identifier(source_table)} s
                LEFT JOIN LATERAL (
                    SELECT {r_columns}
                    FROM {quote_identifier(result_table)} r
                    WHERE r.original_address = s.{quote_identifier(address_col)}
                    LIMIT 1
                ) t ON TRUE
            """
            self.db.execute(create_sql)
            self.db.commit()

            elapsed = time.time() - start_time
            logger.info(
                f"17级副本表 {copy_table} 通过SQL JOIN创建成功"
                f"（源表={source_table}, 结果表={result_table}, 耗时 {elapsed:.2f}s）"
            )
            return copy_table

        except Exception as e:
            logger.error(f"SQL JOIN创建17级副本表失败: {str(e)}")
            import traceback
            logger.error(f"详细堆栈: {traceback.format_exc()}")
            self.db.rollback()
            return None

    # ==================== 17级双字段地址结构化解析结果管理 ====================

    def _tagging_17_2_fields(self):
        """17级双字段输出字段列表（每个NER标签对应主字段+_2字段，共34个）"""
        base_fields = self._tagging_17_fields()
        fields = []
        for f in base_fields:
            fields.append(f)
            fields.append(f'{f}_2')
        return fields

    def create_address_tagging_17_2_table(self, table_name=None):
        """
        创建17级双字段地址结构化解析结果表

        包含 _id_field（标识字段）、dom_json（解析JSON）、original_address 和 34个双字段

        Args:
            table_name: 表名

        Returns:
            bool: 创建成功返回 True
        """
        table_name = table_name or Config.ADDRESS_TAGGING_17_2_RESULTS_TABLE

        sql = f"""
            CREATE TABLE IF NOT EXISTS {quote_identifier(table_name)} (
                id SERIAL PRIMARY KEY,
                _id_field TEXT DEFAULT '',
                dom_json TEXT DEFAULT '',
                original_address TEXT,
                prov VARCHAR(100) DEFAULT '',
                prov_2 VARCHAR(200) DEFAULT '',
                city VARCHAR(100) DEFAULT '',
                city_2 VARCHAR(200) DEFAULT '',
                district VARCHAR(100) DEFAULT '',
                district_2 VARCHAR(200) DEFAULT '',
                town VARCHAR(100) DEFAULT '',
                town_2 VARCHAR(200) DEFAULT '',
                road VARCHAR(200) DEFAULT '',
                road_2 VARCHAR(200) DEFAULT '',
                roadno VARCHAR(100) DEFAULT '',
                roadno_2 VARCHAR(200) DEFAULT '',
                intersection VARCHAR(200) DEFAULT '',
                intersection_2 VARCHAR(200) DEFAULT '',
                poi VARCHAR(300) DEFAULT '',
                poi_2 VARCHAR(300) DEFAULT '',
                subpoi VARCHAR(200) DEFAULT '',
                subpoi_2 VARCHAR(200) DEFAULT '',
                houseno VARCHAR(200) DEFAULT '',
                houseno_2 VARCHAR(200) DEFAULT '',
                cellno VARCHAR(100) DEFAULT '',
                cellno_2 VARCHAR(200) DEFAULT '',
                floorno VARCHAR(100) DEFAULT '',
                floorno_2 VARCHAR(200) DEFAULT '',
                community VARCHAR(200) DEFAULT '',
                community_2 VARCHAR(200) DEFAULT '',
                assist VARCHAR(300) DEFAULT '',
                assist_2 VARCHAR(300) DEFAULT '',
                distance VARCHAR(100) DEFAULT '',
                distance_2 VARCHAR(200) DEFAULT '',
                devzone VARCHAR(200) DEFAULT '',
                devzone_2 VARCHAR(200) DEFAULT '',
                village_group VARCHAR(200) DEFAULT '',
                village_group_2 VARCHAR(200) DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """
        cursor = self.db.execute(sql)
        if cursor:
            self.db.commit()
            logger.info(f"17级双字段地址结构化解析结果表 {table_name} 创建成功")
        return True

    def truncate_address_tagging_17_2_table(self, table_name=None):
        """清空17级双字段地址结构化解析结果表"""
        table_name = table_name or Config.ADDRESS_TAGGING_17_2_RESULTS_TABLE
        return self._generic_truncate_table(table_name, log_label='17级双字段地址结构化解析结果表 ')

    def insert_address_tagging_17_2_results(self, results, table_name=None):
        """批量插入17级双字段地址结构化解析结果"""
        table_name = table_name or Config.ADDRESS_TAGGING_17_2_RESULTS_TABLE
        if not results:
            return 0

        fields = self._tagging_17_2_fields()
        columns = ['_id_field', 'dom_json', 'original_address'] + fields
        sql = f"INSERT INTO {quote_identifier(table_name)} ({', '.join(quote_identifier(c) for c in columns)}) VALUES %s"

        try:
            values = [
                tuple(
                    [r.get('_id_field', '')] +
                    [r.get('dom_json', '')] +
                    [r.get('original_address', '')] +
                    [r.get(f, '') for f in fields]
                )
                for r in results
            ]
            cursor = self.db.get_cursor()
            if not cursor:
                raise Exception("获取数据库游标失败")
            try:
                psycopg2.extras.execute_values(cursor, sql, values, template=None, page_size=1000)
            finally:
                cursor.close()
            self.db.commit()
            logger.info(f"已插入 {len(results)} 条17级双字段结果到 {table_name}")
            return len(results)
        except Exception as e:
            logger.error(f"插入17级双字段结果失败: {str(e)}")
            self.db.rollback()
            return 0

    def get_address_tagging_17_2_results_count(self, table_name=None, filters=None):
        """获取17级双字段解析结果总数"""
        table_name = table_name or Config.ADDRESS_TAGGING_17_2_RESULTS_TABLE
        self.create_address_tagging_17_2_table(table_name)

        return self._generic_get_count(table_name, filters, self._build_address_tagging_17_filter_conditions)

    def get_address_tagging_17_2_results_paginated(self, table_name=None, filters=None, page=1, page_size=20):
        """分页获取17级双字段解析结果"""
        table_name = table_name or Config.ADDRESS_TAGGING_17_2_RESULTS_TABLE
        self.create_address_tagging_17_2_table(table_name)

        return self._generic_get_paginated(
            table_name, filters, self._build_address_tagging_17_filter_conditions,
            page=page, page_size=page_size, order_by='id'
        )

    def get_address_tagging_17_2_statistics(self, table_name=None):
        """获取17级双字段解析统计信息"""
        table_name = table_name or Config.ADDRESS_TAGGING_17_2_RESULTS_TABLE
        self.create_address_tagging_17_2_table(table_name)

        base_fields = self._tagging_17_fields()
        # 统计主字段有值的比例（不含_2字段）
        count_exprs = ', '.join([
            f"SUM(CASE WHEN {quote_identifier(f)} IS NOT NULL AND {quote_identifier(f)} != '' THEN 1 ELSE 0 END) as {f}_count"
            for f in base_fields
        ])

        default_stats = {'total_count': 0}
        for f in base_fields:
            default_stats[f'{f}_count'] = 0
            default_stats[f'{f}_rate'] = 0

        result, total = self._generic_get_statistics(table_name, count_exprs, default_stats)
        if result is None:
            return default_stats

        stats = {'total_count': total}
        for f in base_fields:
            count = result[f'{f}_count'] if result else 0
            stats[f'{f}_count'] = count
            stats[f'{f}_rate'] = (count / total * 100) if total > 0 else 0
        return stats

    def export_address_tagging_17_2_results_batch(self, table_name=None, filters=None, batch_size=5000):
        """批量加载17级双字段解析结果用于导出"""
        table_name = table_name or Config.ADDRESS_TAGGING_17_2_RESULTS_TABLE

        yield from self._generic_export_batch(
            table_name, filters, self._build_address_tagging_17_filter_conditions,
            self.get_address_tagging_17_2_results_count,
            self.get_address_tagging_17_2_results_paginated,
            batch_size=batch_size
        )

    def create_tagging_17_2_copy_table_from_result(self, source_table, address_col,
                                                     result_table, table_suffix='_tagging_17_2'):
        """
        使用 SQL JOIN 从17级双字段结果表创建副本表

        设计要点：使用 LEFT JOIN LATERAL ... LIMIT 1 避免源表地址重复时行数膨胀
            （普通 LEFT JOIN 在源表存在 M 条相同地址、结果表存在 N 条匹配时
             会产生 M×N 行，导致副本表行数远超源表）

        Args:
            source_table: 原始表名
            address_col: 地址字段名
            result_table: 17级双字段结果表名
            table_suffix: 副本表后缀

        Returns:
            str: 副本表名，失败返回 None
        """
        source_count = self._get_table_row_count(source_table)
        logger.info(
            f"开始创建17级双字段副本表，源表 {source_table} 约 {source_count:,} 行，"
            f"结果表 {result_table}，大表创建可能需要较长时间"
        )
        start_time = time.time()

        copy_table = f"{source_table}{table_suffix}"
        fields = self._tagging_17_2_fields()
        join_fields = ['_id_field', 'dom_json'] + fields

        try:
            # 确保结果表有索引加速 JOIN
            self._ensure_result_table_index(result_table)

            drop_sql = f"DROP TABLE IF EXISTS {quote_identifier(copy_table)}"
            self.db.execute(drop_sql)
            self.db.commit()

            # LATERAL子查询别名用 t，内部结果表别名用 r，避免别名冲突
            r_columns = ', '.join([f"r.{quote_identifier(f)}" for f in join_fields])
            t_columns = ', '.join([f"t.{quote_identifier(f)}" for f in join_fields])
            create_sql = f"""
                CREATE TABLE {quote_identifier(copy_table)} AS
                SELECT s.*, {t_columns}
                FROM {quote_identifier(source_table)} s
                LEFT JOIN LATERAL (
                    SELECT {r_columns}
                    FROM {quote_identifier(result_table)} r
                    WHERE r.original_address = s.{quote_identifier(address_col)}
                    LIMIT 1
                ) t ON TRUE
            """
            self.db.execute(create_sql)
            self.db.commit()

            elapsed = time.time() - start_time
            logger.info(
                f"17级双字段副本表 {copy_table} 通过SQL JOIN创建成功（耗时 {elapsed:.2f}s）"
            )
            return copy_table

        except Exception as e:
            logger.error(f"SQL JOIN创建17级双字段副本表失败: {str(e)}")
            import traceback
            logger.error(f"详细堆栈: {traceback.format_exc()}")
            self.db.rollback()
            return None

    def get_recall_results_by_enterprise_ids(self, enterprise_ids, table_name=None):
        """
        根据企业ID列表获取粗召回结果

        Args:
            enterprise_ids: 企业ID列表
            table_name: 表名，默认使用 Config.RECALL_RESULTS_TABLE

        Returns:
            DataFrame: 召回结果数据帧
        """
        table_name = table_name or Config.RECALL_RESULTS_TABLE
        if not enterprise_ids:
            return pd.DataFrame()

        enterprise_ids = [str(eid) for eid in enterprise_ids]
        placeholders = ','.join(['%s'] * len(enterprise_ids))
        sql = f"""
            SELECT * FROM {quote_identifier(table_name)}
            WHERE enterprise_id IN ({placeholders})
            ORDER BY enterprise_id, similarity DESC
        """
        try:
            cursor = self.db.execute(sql, tuple(enterprise_ids))
            if cursor:
                rows = cursor.fetchall()
                return pd.DataFrame(rows)
        except Exception as e:
            logger.error(f"Failed to get recall results by enterprise IDs: {str(e)}")
        return pd.DataFrame()

    def update_match_result_with_correction(self, enterprise_id, standard_id, standard_address, room_no, table_name=None):
        """
        人工纠正：更新匹配结果为指定的粗召回数据，标记为精确匹配

        Args:
            enterprise_id: 企业标识
            standard_id: 标准地址编码
            standard_address: 标准地址
            room_no: 房屋编码
            table_name: 表名，默认使用 Config.RESULT_TABLE

        Returns:
            bool: 更新成功返回 True
        """
        table_name = table_name or Config.RESULT_TABLE
        sql = f"""
            UPDATE {quote_identifier(table_name)}
            SET address_id = %s,
                standard_address = %s,
                room_no = %s,
                exact_match = 1.0,
                partial_match = 0.0,
                not_match = 0.0,
                match_status = '精确匹配',
                correction_source = '人工纠正'
            WHERE enterprise_id = %s
        """
        try:
            cursor = self.db.execute(sql, (str(standard_id), standard_address, room_no, str(enterprise_id)))
            if cursor:
                self.db.commit()
                logger.info(f"Updated match result for enterprise {enterprise_id} with manual correction")
                return True
            else:
                self.db.rollback()
        except Exception as e:
            logger.error(f"Failed to update match result with correction: {str(e)}")
            self.db.rollback()
        return False

    def batch_update_match_results_with_correction(self, correction_data, table_name=None):
        """
        批量人工纠正：更新多条匹配结果

        Args:
            correction_data: 纠正数据列表，每个元素包含 enterprise_id, standard_id, standard_address, room_no
            table_name: 表名，默认使用 Config.RESULT_TABLE

        Returns:
            int: 成功更新的记录数
        """
        table_name = table_name or Config.RESULT_TABLE
        if not correction_data:
            return 0

        success_count = 0
        for item in correction_data:
            if self.update_match_result_with_correction(
                enterprise_id=item['enterprise_id'],
                standard_id=item['standard_id'],
                standard_address=item['standard_address'],
                room_no=item.get('room_no', ''),
                table_name=table_name
            ):
                success_count += 1

        logger.info(f"Batch correction: {success_count}/{len(correction_data)} records updated")
        return success_count

    def direct_correct_match_result(self, enterprise_id, address_id=None, standard_address=None, room_no=None, table_name=None):
        """
        人工直接纠正：在精排结果页面直接修改匹配数据，标记为精确匹配

        Args:
            enterprise_id: 企业标识
            address_id: 标准地址编码（可选，不传则保留原值）
            standard_address: 标准地址（可选，不传则保留原值）
            room_no: 房屋编码（可选，不传则保留原值）
            table_name: 表名，默认使用 Config.RESULT_TABLE

        Returns:
            bool: 更新成功返回 True
        """
        table_name = table_name or Config.RESULT_TABLE

        set_clauses = [
            "exact_match = 1.0",
            "partial_match = 0.0",
            "not_match = 0.0",
            "match_status = '精确匹配'",
            "correction_source = '人工匹配'"
        ]
        params = []

        if address_id is not None:
            set_clauses.append("address_id = %s")
            params.append(str(address_id))
        if standard_address is not None:
            set_clauses.append("standard_address = %s")
            params.append(standard_address)
        if room_no is not None:
            set_clauses.append("room_no = %s")
            params.append(room_no)

        params.append(str(enterprise_id))

        sql = f"UPDATE {quote_identifier(table_name)} SET {', '.join(set_clauses)} WHERE enterprise_id = %s"
        try:
            cursor = self.db.execute(sql, tuple(params))
            if cursor:
                self.db.commit()
                logger.info(f"Direct corrected match result for enterprise {enterprise_id}")
                return True
            else:
                self.db.rollback()
        except Exception as e:
            logger.error(f"Failed to direct correct match result: {str(e)}")
            self.db.rollback()
        return False

    def batch_direct_correct_match_results(self, correction_data, table_name=None):
        """
        批量人工直接纠正：更新多条匹配结果

        Args:
            correction_data: 纠正数据列表，每个元素包含 enterprise_id, address_id, standard_address, room_no
            table_name: 表名，默认使用 Config.RESULT_TABLE

        Returns:
            int: 成功更新的记录数
        """
        table_name = table_name or Config.RESULT_TABLE
        if not correction_data:
            return 0

        success_count = 0
        for item in correction_data:
            if self.direct_correct_match_result(
                enterprise_id=item['enterprise_id'],
                address_id=item.get('address_id'),
                standard_address=item.get('standard_address'),
                room_no=item.get('room_no'),
                table_name=table_name
            ):
                success_count += 1

        logger.info(f"Batch direct correction: {success_count}/{len(correction_data)} records updated")
        return success_count

    def get_match_statistics(self, table_name=None):
        """
        获取匹配统计信息（含人工纠正统计）

        Args:
            table_name: 表名，默认使用 Config.RESULT_TABLE

        Returns:
            dict: 统计信息字典，包含:
                - total_count: 总记录数
                - exact_match_count: 精确匹配数
                - partial_match_count: 部分匹配数
                - not_match_count: 不匹配数
                - match_rate: 匹配率(%)(精确匹配+部分匹配)
                - exact_match_rate: 精确匹配率(%)
                - partial_match_rate: 部分匹配率(%)
                - not_match_rate: 不匹配率(%)
                - avg_exact_match: 平均精确匹配概率
                - avg_partial_match: 平均部分匹配概率
                - avg_not_match: 平均不匹配概率
                - manual_correction_count: 人工纠正数
                - auto_match_count: 自动匹配数
                - manual_correction_rate: 人工纠正率(%)
        """
        table_name = table_name or Config.RESULT_TABLE

        self.create_result_table(table_name)

        count_exprs = """SUM(CASE WHEN match_status = '精确匹配' THEN 1 ELSE 0 END) as exact_match_count,
                SUM(CASE WHEN match_status = '部分匹配' THEN 1 ELSE 0 END) as partial_match_count,
                SUM(CASE WHEN match_status = '不匹配' THEN 1 ELSE 0 END) as not_match_count,
                AVG(exact_match) as avg_exact_match,
                AVG(partial_match) as avg_partial_match,
                AVG(not_match) as avg_not_match,
                SUM(CASE WHEN correction_source IN ('人工纠正', '人工匹配') THEN 1 ELSE 0 END) as manual_correction_count,
                SUM(CASE WHEN correction_source = '人工纠正' THEN 1 ELSE 0 END) as manual_select_count,
                SUM(CASE WHEN correction_source = '人工匹配' THEN 1 ELSE 0 END) as manual_match_count,
                SUM(CASE WHEN correction_source = '自动匹配' OR correction_source IS NULL THEN 1 ELSE 0 END) as auto_match_count"""

        default_stats = {
            'total_count': 0, 'exact_match_count': 0, 'partial_match_count': 0,
            'not_match_count': 0, 'match_rate': 0, 'exact_match_rate': 0,
            'partial_match_rate': 0, 'not_match_rate': 0,
            'avg_exact_match': 0.0, 'avg_partial_match': 0.0, 'avg_not_match': 0.0,
            'manual_correction_count': 0, 'manual_select_count': 0,
            'manual_match_count': 0, 'auto_match_count': 0, 'manual_correction_rate': 0
        }

        result, total = self._generic_get_statistics(table_name, count_exprs, default_stats)
        if result is None:
            return default_stats

        exact_count = result['exact_match_count'] if result else 0
        partial_count = result['partial_match_count'] if result else 0
        not_count = result['not_match_count'] if result else 0
        manual_count = result['manual_correction_count'] if result else 0
        manual_select_count = result['manual_select_count'] if result else 0
        manual_match_count = result['manual_match_count'] if result else 0
        auto_count = result['auto_match_count'] if result else 0
        return {
            'total_count': total,
            'exact_match_count': exact_count,
            'partial_match_count': partial_count,
            'not_match_count': not_count,
            'match_rate': ((exact_count + partial_count) / total * 100) if total > 0 else 0,
            'exact_match_rate': (exact_count / total * 100) if total > 0 else 0,
            'partial_match_rate': (partial_count / total * 100) if total > 0 else 0,
            'not_match_rate': (not_count / total * 100) if total > 0 else 0,
            'avg_exact_match': float(result['avg_exact_match']) if result and result['avg_exact_match'] else 0.0,
            'avg_partial_match': float(result['avg_partial_match']) if result and result['avg_partial_match'] else 0.0,
            'avg_not_match': float(result['avg_not_match']) if result and result['avg_not_match'] else 0.0,
            'manual_correction_count': manual_count,
            'manual_select_count': manual_select_count,
            'manual_match_count': manual_match_count,
            'auto_match_count': auto_count,
            'manual_correction_rate': (manual_count / total * 100) if total > 0 else 0
        }

    def _build_mgeo_similarity_filter_conditions(self, filters):
        """
        构建MGeo相似度匹配结果的筛选条件

        Args:
            filters: 过滤条件字典

        Returns:
            tuple: (conditions列表, params列表)
        """
        conditions = []
        params = []

        if 'match_status' in filters and filters['match_status']:
            conditions.append("match_status = %s")
            params.append(filters['match_status'])

        if 'min_exact_match' in filters and filters['min_exact_match']:
            conditions.append("exact_match >= %s")
            params.append(filters['min_exact_match'])

        if 'max_exact_match' in filters and filters['max_exact_match'] < 1.0:
            conditions.append("exact_match <= %s")
            params.append(filters['max_exact_match'])

        if 'min_partial_match' in filters and filters['min_partial_match']:
            conditions.append("partial_match >= %s")
            params.append(filters['min_partial_match'])

        if 'max_partial_match' in filters and filters['max_partial_match'] < 1.0:
            conditions.append("partial_match <= %s")
            params.append(filters['max_partial_match'])

        if 'min_not_match' in filters and filters['min_not_match']:
            conditions.append("not_match >= %s")
            params.append(filters['min_not_match'])

        if 'max_not_match' in filters and filters['max_not_match'] < 1.0:
            conditions.append("not_match <= %s")
            params.append(filters['max_not_match'])

        if 'keyword' in filters and filters['keyword']:
            conditions.append("(address_a LIKE %s OR address_b LIKE %s)")
            keyword = f"%{filters['keyword']}%"
            params.extend([keyword, keyword])

        return conditions, params

    def create_mgeo_copy_table(self, source_table, address_a_col, address_b_col,
                                results=None, table_suffix='_mgeo', result_table=None):
        """
        基于原始表创建_mgeo副本表，包含原始数据及exact_match、partial_match、not_match三个匹配字段

        支持两种模式：
            1. 传入 result_table（推荐）：通过结果表 JOIN 更新，支持千万级数据，不占用Python内存
            2. 传入 results 列表：通过 VALUES UPDATE，适用于文件输入场景（数据量较小）

        流程：复制原始表全部数据 → 添加匹配字段 → 批量UPDATE匹配结果

        Args:
            source_table: 原始表名
            address_a_col: 地址A字段名
            address_b_col: 地址B字段名
            results: 匹配结果列表（文件输入场景使用）
            table_suffix: 副本表后缀，默认 '_mgeo'
            result_table: 结果表名（数据库输入场景使用，优先于results）

        Returns:
            str: 创建的副本表名，失败返回 None
        """
        copy_table = f"{source_table}{table_suffix}"
        q_copy = quote_identifier(copy_table)
        q_source = quote_identifier(source_table)
        q_addr_a = quote_identifier(address_a_col)
        q_addr_b = quote_identifier(address_b_col)

        try:
            drop_sql = f"DROP TABLE IF EXISTS {q_copy}"
            self.db.execute(drop_sql)
            self.db.commit()

            # 添加行号列用于精确匹配，避免地址文本重复导致错误更新
            create_sql = f"""
                CREATE TABLE {q_copy} AS
                SELECT ROW_NUMBER() OVER () AS __row_id, *
                FROM {q_source}
            """
            self.db.execute(create_sql)
            self.db.commit()

            alter_sqls = [
                f"ALTER TABLE {q_copy} ADD COLUMN IF NOT EXISTS exact_match FLOAT DEFAULT 0.0",
                f"ALTER TABLE {q_copy} ADD COLUMN IF NOT EXISTS partial_match FLOAT DEFAULT 0.0",
                f"ALTER TABLE {q_copy} ADD COLUMN IF NOT EXISTS not_match FLOAT DEFAULT 0.0",
                f"ALTER TABLE {q_copy} ADD COLUMN IF NOT EXISTS match_status VARCHAR(20) DEFAULT '不匹配'"
            ]
            for alter_sql in alter_sqls:
                self.db.execute(alter_sql)
            self.db.commit()

            # 模式1：通过结果表 JOIN 更新（推荐，支持千万级数据）
            if result_table:
                q_result = quote_identifier(result_table)
                # 先给结果表添加行号列（按address_a, address_b排序与源表行号对齐）
                # 使用源表的行号来关联，确保一一对应
                update_sql = f"""
                    UPDATE {q_copy} AS c SET
                        exact_match = r.exact_match,
                        partial_match = r.partial_match,
                        not_match = r.not_match,
                        match_status = r.match_status
                    FROM {q_result} AS r
                    WHERE c.{q_addr_a} = r.address_a AND c.{q_addr_b} = r.address_b
                """
                self.db.execute(update_sql)
                self.db.commit()
                logger.info(f"MGeo copy table {copy_table} updated from result table {result_table}")

            # 模式2：通过 results 列表 VALUES UPDATE（文件输入场景）
            elif results:
                update_sql = f"""
                    UPDATE {q_copy} AS c SET
                        exact_match = v.exact_match,
                        partial_match = v.partial_match,
                        not_match = v.not_match,
                        match_status = v.match_status
                    FROM (VALUES %s) AS v(addr_a, addr_b, exact_match, partial_match, not_match, match_status)
                    WHERE c.{q_addr_a} = v.addr_a AND c.{q_addr_b} = v.addr_b
                """
                values = [
                    (r['address_a'], r['address_b'],
                     float(r.get('exact_match', 0.0)),
                     float(r.get('partial_match', 0.0)),
                     float(r.get('not_match', 0.0)),
                     r['match_status'])
                    for r in results
                ]
                cursor = self.db.get_cursor()
                if not cursor:
                    raise Exception("获取数据库游标失败")
                try:
                    psycopg2.extras.execute_values(
                        cursor, update_sql, values, template=None, page_size=5000
                    )
                finally:
                    cursor.close()
                self.db.commit()
                logger.info(f"MGeo copy table {copy_table} batch-updated with {len(results)} results")

            logger.info(f"MGeo copy table {copy_table} created successfully")
            return copy_table

        except Exception as e:
            logger.error(f"Failed to create MGeo copy table: {str(e)}")
            import traceback
            logger.error(f"详细堆栈: {traceback.format_exc()}")
            self.db.rollback()
            return None

    def export_match_results_batch(self, table_name=None, filters=None, batch_size=5000):
        """
        批量加载匹配结果用于导出（避免一次性加载导致内存溢出）

        Args:
            table_name: 表名，默认使用 Config.RESULT_TABLE
            filters: 过滤条件字典
            batch_size: 每批加载的记录数

        Yields:
            DataFrame: 每批匹配结果数据帧
        """
        table_name = table_name or Config.RESULT_TABLE
        self.create_result_table(table_name)

        yield from self._generic_export_batch(
            table_name, filters, self._build_filter_conditions,
            self.get_match_results_count,
            self.get_match_results_paginated,
            batch_size=batch_size
        )
