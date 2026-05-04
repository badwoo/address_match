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

import pandas as pd
import psycopg2
from config import Config
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
            batch_size: 每页大小，默认使用 Config.BATCH_SIZE_DB
        
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
                    SELECT {id_col}, {name_col}, {address_col}
                    FROM {table_name}
                    WHERE {address_col} IS NOT NULL AND {address_col} != ''
                    ORDER BY {id_col}
                    LIMIT %s
                """
                cursor = self.db.execute(sql, (batch_size,))
            else:
                sql = f"""
                    SELECT {id_col}, {name_col}, {address_col}
                    FROM {table_name}
                    WHERE {address_col} IS NOT NULL AND {address_col} != ''
                    AND {id_col} > %s
                    ORDER BY {id_col}
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
            
            last_id = rows[-1][id_col]
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
            batch_size: 每页大小，默认使用 Config.BATCH_SIZE_DB
        
        Yields:
            DataFrame: 包含 id, address, [room_no] 列的数据帧
        """
        batch_size = batch_size or Config.BATCH_SIZE_DB
        
        last_id = None
        
        while True:
            if room_col:
                if last_id is None:
                    sql = f"""
                        SELECT {id_col}, {address_col}, {room_col}
                        FROM {table_name}
                        WHERE {address_col} IS NOT NULL AND {address_col} != ''
                        ORDER BY {id_col}
                        LIMIT %s
                    """
                    cursor = self.db.execute(sql, (batch_size,))
                else:
                    sql = f"""
                        SELECT {id_col}, {address_col}, {room_col}
                        FROM {table_name}
                        WHERE {address_col} IS NOT NULL AND {address_col} != ''
                        AND {id_col} > %s
                        ORDER BY {id_col}
                        LIMIT %s
                    """
                    cursor = self.db.execute(sql, (last_id, batch_size))
            else:
                if last_id is None:
                    sql = f"""
                        SELECT {id_col}, {address_col}
                        FROM {table_name}
                        WHERE {address_col} IS NOT NULL AND {address_col} != ''
                        ORDER BY {id_col}
                        LIMIT %s
                    """
                    cursor = self.db.execute(sql, (batch_size,))
                else:
                    sql = f"""
                        SELECT {id_col}, {address_col}
                        FROM {table_name}
                        WHERE {address_col} IS NOT NULL AND {address_col} != ''
                        AND {id_col} > %s
                        ORDER BY {id_col}
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
            
            last_id = rows[-1][id_col]
            yield df
    
    def get_total_count(self, table_name):
        """
        获取表的总记录数
        
        Args:
            table_name: 表名
        
        Returns:
            int: 记录数
        """
        sql = f"SELECT COUNT(*) as count FROM {table_name}"
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
        sql = f"SELECT COUNT(*) as count FROM {table_name} WHERE {address_col} IS NOT NULL AND {address_col} != ''"
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
            CREATE TABLE IF NOT EXISTS {table_name} (
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
        批量插入粗召回结果
        
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
            INSERT INTO {table_name} 
            (enterprise_id, enterprise_name, enterprise_address, standard_id, standard_address, room_no, similarity)
            VALUES %s
        """
        
        try:
            values = []
            for item in results:
                enterprise_id = item['enterprise_id']
                enterprise_name = item.get('enterprise_name', '')
                enterprise_address = item['enterprise_address']
                for candidate in item['candidates']:
                    values.append((
                        enterprise_id,
                        enterprise_name,
                        enterprise_address,
                        candidate['source_id'],
                        candidate['address'],
                        candidate.get('room_no', ''),
                        float(candidate['similarity'])
                    ))
            
            # 使用 execute_values 进行高效批量插入
            psycopg2.extras.execute_values(
                self.db.cursor, sql, values, template=None, page_size=1000
            )
            self.db.commit()
            logger.info(f"Inserted {len(values)} recall results")
            return len(values)
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
        sql = f"SELECT * FROM {table_name} ORDER BY enterprise_id, similarity DESC LIMIT %s OFFSET %s"
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

        sql = f"SELECT COUNT(*) as count FROM {table_name}"
        params = None

        if filters:
            conditions, params = self._build_recall_filter_conditions(filters)
            if conditions:
                sql += " WHERE " + " AND ".join(conditions)

        try:
            cursor = self.db.execute(sql, params)
            if cursor:
                result = cursor.fetchone()
                return result['count'] if result else 0
        except Exception as e:
            logger.error(f"Failed to get recall results count: {str(e)}")
        return 0

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

        sql = f"SELECT * FROM {table_name}"
        params = []

        if filters:
            conditions, params = self._build_recall_filter_conditions(filters)
            if conditions:
                sql += " WHERE " + " AND ".join(conditions)

        sql += " ORDER BY enterprise_id, similarity DESC"

        offset = (page - 1) * page_size
        sql += f" LIMIT {page_size} OFFSET {offset}"

        try:
            cursor = self.db.execute(sql, params if params else None)
            if cursor:
                rows = cursor.fetchall()
                return pd.DataFrame(rows)
        except Exception as e:
            logger.error(f"Failed to get paginated recall results: {str(e)}")
        return pd.DataFrame()
    
    def truncate_recall_table(self, table_name=None):
        """
        清空粗召回结果表
        
        Args:
            table_name: 表名，默认使用 Config.RECALL_RESULTS_TABLE
        
        Returns:
            bool: 清空成功返回 True
        """
        table_name = table_name or Config.RECALL_RESULTS_TABLE
        sql = f"TRUNCATE TABLE {table_name}"
        cursor = self.db.execute(sql)
        if cursor:
            self.db.commit()
            logger.info(f"Recall table {table_name} truncated successfully")
            return True
        return False
    
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
            FROM {table_name}
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
            partial_match: 部分匹配概率
            exact_match: 精确匹配概率
            not_match: 不匹配概率
            match_status: 匹配状态（精确匹配/部分匹配/不匹配）
            correction_source: 纠正来源（自动匹配/人工纠正）
            created_at: 创建时间
        
        Args:
            table_name: 表名，默认使用 Config.RESULT_TABLE
        
        Returns:
            bool: 创建成功返回 True
        """
        table_name = table_name or Config.RESULT_TABLE
        
        sql = f"""
            CREATE TABLE IF NOT EXISTS {table_name} (
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
            INSERT INTO {table_name} 
            (enterprise_id, enterprise_name, enterprise_address, address_id, standard_address, room_no, 
             partial_match, exact_match, not_match, match_status)
            VALUES %s
        """
        
        try:
            values = [
                (
                    r['enterprise_id'],
                    r['enterprise_name'],
                    r['enterprise_address'],
                    r['address_id'],
                    r['standard_address'],
                    r.get('room_no', ''),
                    float(r.get('partial_match', 0.0)),
                    float(r.get('exact_match', 0.0)),
                    float(r.get('not_match', 0.0)),
                    r['match_status']
                )
                for r in results
            ]
            
            psycopg2.extras.execute_values(
                self.db.cursor, sql, values, template=None, page_size=1000
            )
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
        sql = f"SELECT * FROM {table_name}"
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
        
        sql = f"SELECT COUNT(*) as count FROM {table_name}"
        params = None
        
        if filters:
            conditions, params = self._build_filter_conditions(filters)
            if conditions:
                sql += " WHERE " + " AND ".join(conditions)
        
        try:
            cursor = self.db.execute(sql, params)
            if cursor:
                result = cursor.fetchone()
                return result['count'] if result else 0
        except Exception as e:
            logger.error(f"Failed to get match results count: {str(e)}")
        return 0
    
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
        
        sql = f"SELECT * FROM {table_name}"
        params = []
        
        if filters:
            conditions, params = self._build_filter_conditions(filters)
            if conditions:
                sql += " WHERE " + " AND ".join(conditions)
        
        sql += " ORDER BY exact_match DESC, partial_match DESC"
        
        offset = (page - 1) * page_size
        sql += f" LIMIT {page_size} OFFSET {offset}"
        
        try:
            cursor = self.db.execute(sql, params if params else None)
            if cursor:
                rows = cursor.fetchall()
                return pd.DataFrame(rows)
        except Exception as e:
            logger.error(f"Failed to get paginated match results: {str(e)}")
        return pd.DataFrame()
    
    def get_result_count(self, table_name=None):
        """
        获取匹配结果表记录数
        
        Args:
            table_name: 表名，默认使用 Config.RESULT_TABLE
        
        Returns:
            int: 记录数
        """
        table_name = table_name or Config.RESULT_TABLE
        sql = f"SELECT COUNT(*) as count FROM {table_name}"
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
                    alter_sql = f"ALTER TABLE {table_name} ADD COLUMN correction_source VARCHAR(20) DEFAULT '自动匹配'"
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
                    alter_sql = f"ALTER TABLE {table_name} ALTER COLUMN {col} TYPE DOUBLE PRECISION"
                    self.db.execute(alter_sql)
                    logger.info(f"Migrated {table_name}.{col} from FLOAT to DOUBLE PRECISION")
                except Exception as e:
                    logger.warning(f"Failed to migrate {table_name}.{col}: {e}")
            try:
                self.db.commit()
            except Exception:
                pass

    def truncate_result_table(self, table_name=None):
        """
        清空匹配结果表
        
        Args:
            table_name: 表名，默认使用 Config.RESULT_TABLE
        
        Returns:
            bool: 清空成功返回 True
        """
        table_name = table_name or Config.RESULT_TABLE
        sql = f"TRUNCATE TABLE {table_name}"
        cursor = self.db.execute(sql)
        if cursor:
            self.db.commit()
            logger.info(f"Result table {table_name} truncated successfully")
            return True
        return False
    
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
        count_sql = f"SELECT COUNT(*) as count FROM {table_name}"
        count_cursor = self.db.execute(count_sql)
        total = count_cursor.fetchone()['count'] if count_cursor else 0
        
        if total == 0:
            return
        
        offset = 0
        while offset < total:
            sql = f"SELECT * FROM {table_name} ORDER BY id LIMIT {batch_size} OFFSET {offset}"
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
            CREATE TABLE IF NOT EXISTS {table_name} (
                id SERIAL PRIMARY KEY,
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
        
        return True

    def insert_mgeo_similarity_results(self, results, table_name=None):
        """
        批量插入MGeo地址相似度匹配结果

        Args:
            results: 匹配结果列表，每个元素包含 address_a, address_b,
                     exact_match, partial_match, not_match, match_status
            table_name: 表名，默认使用 Config.MGEO_SIMILARITY_RESULTS_TABLE

        Returns:
            int: 成功插入的记录数
        """
        table_name = table_name or Config.MGEO_SIMILARITY_RESULTS_TABLE
        if not results:
            return 0

        sql = f"""
            INSERT INTO {table_name}
            (address_a, address_b, exact_match, partial_match, not_match, match_status)
            VALUES %s
        """

        try:
            values = [
                (
                    r['address_a'],
                    r['address_b'],
                    float(r.get('exact_match', 0.0)),
                    float(r.get('partial_match', 0.0)),
                    float(r.get('not_match', 0.0)),
                    r['match_status']
                )
                for r in results
            ]

            psycopg2.extras.execute_values(
                self.db.cursor, sql, values, template=None, page_size=1000
            )
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
        sql = f"TRUNCATE TABLE {table_name}"
        cursor = self.db.execute(sql)
        if cursor:
            self.db.commit()
            logger.info(f"MGeo similarity table {table_name} truncated successfully")
            return True
        return False

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

        sql = f"SELECT COUNT(*) as count FROM {table_name}"
        params = None

        if filters:
            conditions, params = self._build_mgeo_similarity_filter_conditions(filters)
            if conditions:
                sql += " WHERE " + " AND ".join(conditions)

        try:
            cursor = self.db.execute(sql, params)
            if cursor:
                result = cursor.fetchone()
                return result['count'] if result else 0
        except Exception as e:
            logger.error(f"Failed to get MGeo similarity results count: {str(e)}")
        return 0

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

        sql = f"SELECT * FROM {table_name}"
        params = []

        if filters:
            conditions, params = self._build_mgeo_similarity_filter_conditions(filters)
            if conditions:
                sql += " WHERE " + " AND ".join(conditions)

        sql += " ORDER BY exact_match DESC, partial_match DESC"

        offset = (page - 1) * page_size
        sql += f" LIMIT {page_size} OFFSET {offset}"

        try:
            cursor = self.db.execute(sql, params if params else None)
            if cursor:
                rows = cursor.fetchall()
                return pd.DataFrame(rows)
        except Exception as e:
            logger.error(f"Failed to get paginated MGeo similarity results: {str(e)}")
        return pd.DataFrame()

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

        sql = f"""
            SELECT
                COUNT(*) as total_count,
                SUM(CASE WHEN match_status = '精确匹配' THEN 1 ELSE 0 END) as exact_match_count,
                SUM(CASE WHEN match_status = '部分匹配' THEN 1 ELSE 0 END) as partial_match_count,
                SUM(CASE WHEN match_status = '不匹配' THEN 1 ELSE 0 END) as not_match_count,
                AVG(exact_match) as avg_exact_match,
                AVG(partial_match) as avg_partial_match,
                AVG(not_match) as avg_not_match
            FROM {table_name}
        """

        try:
            cursor = self.db.execute(sql)
            if cursor:
                result = cursor.fetchone()
                total = result['total_count'] if result else 0
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
        except Exception as e:
            logger.error(f"Failed to get MGeo similarity statistics: {str(e)}")
        return {
            'total_count': 0,
            'exact_match_count': 0,
            'partial_match_count': 0,
            'not_match_count': 0,
            'match_rate': 0,
            'exact_match_rate': 0,
            'partial_match_rate': 0,
            'not_match_rate': 0,
            'avg_exact_match': 0.0,
            'avg_partial_match': 0.0,
            'avg_not_match': 0.0
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

        total = self.get_mgeo_similarity_results_count(table_name, filters)
        if total == 0:
            return

        offset = 0
        while offset < total:
            results = self.get_mgeo_similarity_results_paginated(
                table_name=table_name,
                filters=filters,
                page=(offset // batch_size) + 1,
                page_size=batch_size
            )
            if not results.empty:
                yield results
            offset += batch_size

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

        placeholders = ','.join(['%s'] * len(enterprise_ids))
        sql = f"""
            SELECT * FROM {table_name}
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
            UPDATE {table_name}
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
            cursor = self.db.execute(sql, (standard_id, standard_address, room_no, enterprise_id))
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

        sql = f"""
            SELECT 
                COUNT(*) as total_count,
                SUM(CASE WHEN match_status = '精确匹配' THEN 1 ELSE 0 END) as exact_match_count,
                SUM(CASE WHEN match_status = '部分匹配' THEN 1 ELSE 0 END) as partial_match_count,
                SUM(CASE WHEN match_status = '不匹配' THEN 1 ELSE 0 END) as not_match_count,
                AVG(exact_match) as avg_exact_match,
                AVG(partial_match) as avg_partial_match,
                AVG(not_match) as avg_not_match,
                SUM(CASE WHEN correction_source = '人工纠正' THEN 1 ELSE 0 END) as manual_correction_count,
                SUM(CASE WHEN correction_source = '自动匹配' OR correction_source IS NULL THEN 1 ELSE 0 END) as auto_match_count
            FROM {table_name}
        """

        try:
            cursor = self.db.execute(sql)
            if cursor:
                result = cursor.fetchone()
                total = result['total_count'] if result else 0
                exact_count = result['exact_match_count'] if result else 0
                partial_count = result['partial_match_count'] if result else 0
                not_count = result['not_match_count'] if result else 0
                manual_count = result['manual_correction_count'] if result else 0
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
                    'auto_match_count': auto_count,
                    'manual_correction_rate': (manual_count / total * 100) if total > 0 else 0
                }
        except Exception as e:
            logger.error(f"Failed to get match statistics: {str(e)}")
        return {
            'total_count': 0,
            'exact_match_count': 0,
            'partial_match_count': 0,
            'not_match_count': 0,
            'match_rate': 0,
            'exact_match_rate': 0,
            'partial_match_rate': 0,
            'not_match_rate': 0,
            'avg_exact_match': 0.0,
            'avg_partial_match': 0.0,
            'avg_not_match': 0.0,
            'manual_correction_count': 0,
            'auto_match_count': 0,
            'manual_correction_rate': 0
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

    def create_mgeo_copy_table(self, source_table, address_a_col, address_b_col, results, table_suffix='_mgeo'):
        """
        基于原始表创建_mgeo副本表，包含原始数据及exact_match、partial_match、not_match三个匹配字段

        流程：复制原始表全部数据 → 添加匹配字段 → 逐行更新匹配结果

        Args:
            source_table: 原始表名
            address_a_col: 地址A字段名
            address_b_col: 地址B字段名
            results: 匹配结果列表，每个元素包含 address_a, address_b, exact_match, partial_match, not_match, match_status
            table_suffix: 副本表后缀，默认 '_mgeo'

        Returns:
            str: 创建的副本表名，失败返回 None
        """
        copy_table = f"{source_table}{table_suffix}"

        try:
            drop_sql = f"DROP TABLE IF EXISTS {copy_table}"
            self.db.execute(drop_sql)
            self.db.commit()

            create_sql = f"CREATE TABLE {copy_table} AS SELECT * FROM {source_table}"
            self.db.execute(create_sql)
            self.db.commit()

            alter_sqls = [
                f"ALTER TABLE {copy_table} ADD COLUMN IF NOT EXISTS exact_match FLOAT DEFAULT 0.0",
                f"ALTER TABLE {copy_table} ADD COLUMN IF NOT EXISTS partial_match FLOAT DEFAULT 0.0",
                f"ALTER TABLE {copy_table} ADD COLUMN IF NOT EXISTS not_match FLOAT DEFAULT 0.0",
                f"ALTER TABLE {copy_table} ADD COLUMN IF NOT EXISTS match_status VARCHAR(20) DEFAULT '不匹配'"
            ]
            for alter_sql in alter_sqls:
                self.db.execute(alter_sql)
            self.db.commit()

            if results:
                update_sql = f"""
                    UPDATE {copy_table}
                    SET exact_match = %s, partial_match = %s, not_match = %s, match_status = %s
                    WHERE {address_a_col} = %s AND {address_b_col} = %s
                """
                batch_size = 500
                for i in range(0, len(results), batch_size):
                    batch = results[i:i + batch_size]
                    for r in batch:
                        self.db.execute(update_sql, (
                            float(r.get('exact_match', 0.0)),
                            float(r.get('partial_match', 0.0)),
                            float(r.get('not_match', 0.0)),
                            r['match_status'],
                            r['address_a'],
                            r['address_b']
                        ))
                    self.db.commit()
                    logger.info(f"MGeo copy table update progress: {min(i + batch_size, len(results))}/{len(results)}")

            logger.info(f"MGeo copy table {copy_table} created successfully with {len(results)} match results")
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
        
        total = self.get_match_results_count(table_name, filters)
        if total == 0:
            return
        
        offset = 0
        while offset < total:
            results = self.get_match_results_paginated(
                table_name=table_name,
                filters=filters,
                page=(offset // batch_size) + 1,
                page_size=batch_size
            )
            if not results.empty:
                yield results
            offset += batch_size
