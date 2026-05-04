"""
向量存储模块
============

负责向量数据的存储、索引和检索操作，基于 PostgreSQL + pgvector 扩展实现。

核心功能：
    1. 创建向量表（支持企业表和标准地址表两种类型）
    2. 创建向量索引（使用 ivfflat 索引加速相似性搜索）
    3. 插入向量数据
    4. 批量召回（基于向量相似度检索候选地址）
    5. 向量表管理（查询、清空、删除）

技术要点：
    - 使用 pgvector 扩展存储和查询向量
    - 使用 ivfflat 索引加速 ANN（近似最近邻）搜索
    - 向量维度由模型配置决定（默认768维）
"""

import numpy as np
import psycopg2
import psycopg2.extras
import pgvector.psycopg2
from config import Config
from utils.logger import logger

class VectorStore:
    """
    向量存储管理器
    
    负责向量数据的存储、索引和检索操作。
    
    Attributes:
        db: 数据库连接对象
        vector_dim: 向量维度（默认768）
        table_name: 默认向量表名
        index_name: 默认索引名
    """
    
    def __init__(self, db_connection):
        """
        初始化向量存储管理器
        
        Args:
            db_connection: DBConnection 对象
        """
        self.db = db_connection
        self.vector_dim = Config.VECTOR_DIM
        self.table_name = Config.VECTOR_TABLE
        self.index_name = Config.INDEX_NAME
    
    def create_vector_table(self, table_name=None, table_type='enterprise'):
        """
        创建向量表（使用默认维度）
        
        Args:
            table_name: 表名，默认使用 Config.VECTOR_TABLE
            table_type: 表类型，'enterprise' 或 'standard'
        
        Returns:
            bool: 创建成功返回 True
        """
        table_name = table_name or self.table_name
        
        if table_type == 'enterprise':
            sql = f"""
                CREATE TABLE IF NOT EXISTS {table_name} (
                    id SERIAL PRIMARY KEY,
                    source_id VARCHAR(255) NOT NULL,
                    enterprise_name TEXT,
                    address TEXT NOT NULL,
                    vector vector({self.vector_dim}) NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """
        else:
            sql = f"""
                CREATE TABLE IF NOT EXISTS {table_name} (
                    id SERIAL PRIMARY KEY,
                    source_id VARCHAR(255) NOT NULL,
                    address TEXT NOT NULL,
                    room_no VARCHAR(100),
                    vector vector({self.vector_dim}) NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """
        
        cursor = self.db.execute(sql)
        if cursor:
            self.db.commit()
            logger.info(f"Vector table {table_name} created successfully (type: {table_type}, dim: {self.vector_dim})")
            return True
        return False
    
    def create_vector_table_with_dim(self, table_name, vector_dim, table_type='enterprise'):
        """
        创建向量表（指定维度）
        
        Args:
            table_name: 表名
            vector_dim: 向量维度
            table_type: 表类型，'enterprise' 或 'standard'
        
        Returns:
            bool: 创建成功返回 True
        """
        if table_type == 'enterprise':
            sql = f"""
                CREATE TABLE IF NOT EXISTS {table_name} (
                    id SERIAL PRIMARY KEY,
                    source_id VARCHAR(255) NOT NULL,
                    enterprise_name TEXT,
                    address TEXT NOT NULL,
                    vector vector({vector_dim}) NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """
        else:
            sql = f"""
                CREATE TABLE IF NOT EXISTS {table_name} (
                    id SERIAL PRIMARY KEY,
                    source_id VARCHAR(255) NOT NULL,
                    address TEXT NOT NULL,
                    room_no VARCHAR(100),
                    vector vector({vector_dim}) NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """
        
        cursor = self.db.execute(sql)
        if cursor:
            self.db.commit()
            logger.info(f"Vector table {table_name} created successfully (type: {table_type}, dim: {vector_dim})")
            return True
        return False
    
    def create_vector_index(self, table_name=None, index_name=None):
        """
        创建向量索引（ivfflat）
        
        使用 ivfflat 索引加速向量相似性搜索，适合大规模数据。
        
        Args:
            table_name: 表名，默认使用 Config.VECTOR_TABLE
            index_name: 索引名，默认使用 Config.INDEX_NAME
        
        Returns:
            bool: 创建成功返回 True
        """
        table_name = table_name or self.table_name
        index_name = index_name or self.index_name
        
        # 检查索引是否已存在
        check_sql = f"""
            SELECT 1 FROM pg_indexes 
            WHERE schemaname = %s 
            AND tablename = %s 
            AND indexname = %s
        """
        cursor = self.db.execute(check_sql, (self.db.schema, table_name, index_name))
        if cursor and cursor.fetchone():
            logger.info(f"Index {index_name} already exists, skipping creation")
            return True
        
        # 创建 ivfflat 索引，使用余弦距离
        sql = f"""
            CREATE INDEX {index_name} 
            ON {table_name} 
            USING ivfflat (vector vector_cosine_ops) 
            WITH (lists = 1000)
        """
        cursor = self.db.execute(sql)
        if cursor:
            self.db.commit()
            logger.info(f"Vector index {index_name} created successfully")
            return True
        return False
    
    def insert_vectors(self, vectors, source_ids, addresses, table_name=None, extra_data=None, table_type='enterprise', insert_chunk_size=5000):
        """
        批量插入向量数据（使用 execute_values 高效批量插入）
        
        分块构建向量字符串并批量插入，避免一次性将所有向量的字符串表示加载到内存。
        
        Args:
            vectors: 向量数组，形状为 (n, dim)
            source_ids: 源数据ID列表
            addresses: 地址文本列表
            table_name: 目标表名
            extra_data: 额外数据列表（企业表为企业名，标准地址表为房号）
            table_type: 表类型，'enterprise' 或 'standard'，决定插入的字段结构
            insert_chunk_size: 每次插入的向量数量，控制内存占用
        
        Returns:
            int: 成功插入的记录数
        """
        table_name = table_name or self.table_name
        if len(vectors) == 0:
            return 0
        
        actual_dim = vectors.shape[1] if len(vectors.shape) > 1 else len(vectors[0])
        total = len(vectors)
        logger.debug(f"Inserting {total} vectors with dimension {actual_dim} into {table_name}")
        
        try:
            first_vector = vectors[0] if isinstance(vectors[0], np.ndarray) else np.array(vectors[0])
            first_norm = np.linalg.norm(first_vector)
            logger.info(f"待插入向量样本 - 维度: {len(first_vector)}, L2范数: {first_norm:.8f}")
            
            if abs(first_norm - 1.0) > 0.1:
                logger.warning(f"向量可能未正确归一化，范数={first_norm:.8f}")
            
            if table_type == 'enterprise':
                sql = f"""
                    INSERT INTO {table_name} (source_id, enterprise_name, address, vector)
                    VALUES %s
                """
                template = f"(%s, %s, %s, %s::vector({actual_dim}))"
            else:
                sql = f"""
                    INSERT INTO {table_name} (source_id, address, room_no, vector)
                    VALUES %s
                """
                template = f"(%s, %s, %s, %s::vector({actual_dim}))"
            
            inserted_count = 0
            
            for chunk_start in range(0, total, insert_chunk_size):
                chunk_end = min(chunk_start + insert_chunk_size, total)
                values = []
                
                for i in range(chunk_start, chunk_end):
                    source_id = source_ids[i]
                    address = addresses[i]
                    vector = vectors[i]
                    
                    vec_data = vector if isinstance(vector, np.ndarray) else np.array(vector)
                    vec_data = vec_data.astype(np.float32)
                    vec_str = '[' + ','.join(repr(float(x)) for x in vec_data.tolist()) + ']'
                    
                    if table_type == 'enterprise':
                        enterprise_name = extra_data[i] if extra_data else ''
                        values.append((source_id, enterprise_name, address, vec_str))
                    else:
                        room_no = extra_data[i] if extra_data else ''
                        values.append((source_id, address, room_no, vec_str))
                
                psycopg2.extras.execute_values(
                    self.db.cursor, sql, values, template=template, page_size=1000
                )
                self.db.commit()
                inserted_count += len(values)
                logger.info(f"已插入 {inserted_count}/{total} 条向量到 {table_name}...")
            
            logger.info(f"✅ 成功插入 {inserted_count} 条向量到 {table_name}")
            
            sample_norm = np.linalg.norm(vectors[0])
            logger.info(f"样本向量L2范数（应≈1.0）：{sample_norm:.8f}")
            
            self._verify_inserted_vectors(table_name, source_ids[:3] if len(source_ids) >= 3 else source_ids)
            
            return inserted_count
        except Exception as e:
            logger.error(f"❌ 插入向量失败：{str(e)}")
            self.db.rollback()
            return 0
    
    def _verify_inserted_vectors(self, table_name, sample_ids):
        """
        验证已插入的向量是否正确归一化
        
        Args:
            table_name: 表名
            sample_ids: 样本ID列表
        """
        try:
            for source_id in sample_ids:
                sql = f"""
                    SELECT source_id, address, vector <#> vector as self_inner_product
                    FROM {table_name}
                    WHERE source_id = %s
                """
                cursor = self.db.execute(sql, (source_id,))
                if cursor:
                    row = cursor.fetchone()
                    if row:
                        sid = row['source_id']
                        addr = row['address']
                        self_ip = row['self_inner_product']
                        # 自身内积应该接近1.0（如果向量已归一化）
                        if self_ip is not None:
                            if abs(self_ip - 1.0) < 0.1:
                                logger.info(f"✓ 向量验证通过 - ID:{sid}, 自身内积:{self_ip:.8f}")
                            else:
                                logger.warning(f"✗ 向量验证失败 - ID:{sid}, 自身内积:{self_ip:.8f}, 期望≈1.0")
                        else:
                            logger.warning(f"✗ 向量验证失败 - ID:{sid}, 自身内积为NULL")
        except Exception as e:
            logger.error(f"向量验证出错: {e}")
    
    def search_vectors(self, query_vector, top_n=10, table_name=None):
        """
        向量相似性搜索
        
        使用 pgvector 的L2距离操作符进行近似最近邻搜索。
        
        Args:
            query_vector: 查询向量
            top_n: 返回前N个最相似的结果
            table_name: 目标表名
        
        Returns:
            list: 包含 source_id, address, similarity 的字典列表
        """
        table_name = table_name or self.table_name
        query_vector = np.array(query_vector)
        
        sql = f"""
            SELECT source_id, address, 1 - (vector <-> %s) as similarity
            FROM {table_name}
            ORDER BY vector <-> %s
            LIMIT %s
        """
        
        cursor = self.db.execute(sql, (query_vector, query_vector, top_n))
        if cursor:
            results = cursor.fetchall()
            return [
                {
                    'source_id': row['source_id'],
                    'address': row['address'],
                    'similarity': row['similarity']
                }
                for row in results
            ]
        return []
    
    def batch_recall(self, enterprise_table, standard_table, top_n=10, similarity_threshold=None):
        """
        批量召回 - 为每个企业检索最相似的标准地址候选
        
        阶段1（粗召回）的核心方法，使用 SQL JOIN LATERAL 实现高效的批量向量相似性检索。
        
        Args:
            enterprise_table: 企业向量表名
            standard_table: 标准地址向量表名
            top_n: 每个企业召回的候选数量
            similarity_threshold: 相似度阈值（0-1），低于此阈值的候选将被过滤，None表示不过滤
        
        Returns:
            list: 召回结果列表，每个元素包含企业信息和候选地址列表
        """
        logger.info(f"Starting batch recall from {enterprise_table} to {standard_table}, top_n={top_n}, threshold={similarity_threshold}")
        
        threshold_condition = ""
        if similarity_threshold is not None:
            threshold_condition = f"WHERE 1 - (c.vector <-> a.vector) >= {float(similarity_threshold)}"
        
        sql = f"""
            SELECT 
                c.source_id AS enterprise_id,
                c.enterprise_name,
                c.address AS enterprise_address,
                a.source_id AS standard_id,
                a.address AS standard_address,
                a.room_no,
                1 - (c.vector <-> a.vector) AS similarity
            FROM {enterprise_table} c
            JOIN LATERAL (
                SELECT 
                    source_id,
                    address,
                    room_no,
                    vector
                FROM {standard_table}
                ORDER BY c.vector <-> vector
                LIMIT {top_n}
            ) a ON true
            {threshold_condition}
            ORDER BY c.source_id, similarity DESC
        """
        
        cursor = self.db.execute(sql)
        if not cursor:
            logger.error(f"Failed to execute batch recall")
            return []
        
        results = cursor.fetchall()
        logger.info(f"Batch recall returned {len(results)} raw results")
        
        if not results:
            return []
        
        # 按企业ID分组，将候选地址整理到对应的企业下
        grouped_results = {}
        for row in results:
            enterprise_id = row['enterprise_id']
            if enterprise_id not in grouped_results:
                grouped_results[enterprise_id] = {
                    'enterprise_id': enterprise_id,
                    'enterprise_name': row['enterprise_name'],
                    'enterprise_address': row['enterprise_address'],
                    'candidates': []
                }
            
            grouped_results[enterprise_id]['candidates'].append({
                'source_id': row['standard_id'],
                'address': row['standard_address'],
                'room_no': row['room_no'],
                'similarity': row['similarity']
            })
        
        logger.info(f"✅ 批量召回完成，为 {len(grouped_results)} 家企业找到候选地址")
        return list(grouped_results.values())
    
    def get_vector_count(self, table_name=None):
        """
        获取向量表记录数
        
        Args:
            table_name: 表名
        
        Returns:
            int: 记录数
        """
        table_name = table_name or self.table_name
        sql = f"SELECT COUNT(*) as count FROM {table_name}"
        cursor = self.db.execute(sql)
        if cursor:
            result = cursor.fetchone()
            return result['count'] if result else 0
        return 0
    
    def drop_vector_table(self, table_name=None):
        """
        删除向量表
        
        Args:
            table_name: 表名
        
        Returns:
            bool: 删除成功返回 True
        """
        table_name = table_name or self.table_name
        sql = f"DROP TABLE IF EXISTS {table_name}"
        cursor = self.db.execute(sql)
        if cursor:
            self.db.commit()
            logger.info(f"Vector table {table_name} dropped successfully")
            return True
        return False
    
    def truncate_vector_table(self, table_name=None):
        """
        清空向量表
        
        Args:
            table_name: 表名
        
        Returns:
            bool: 清空成功返回 True
        """
        table_name = table_name or self.table_name
        sql = f"TRUNCATE TABLE {table_name}"
        cursor = self.db.execute(sql)
        if cursor:
            self.db.commit()
            logger.info(f"Vector table {table_name} truncated successfully")
            return True
        return False
    
    def get_vector_tables(self):
        """
        获取所有向量表名（表名包含 'vector'）
        
        Returns:
            list: 向量表名列表
        """
        sql = """
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = %s 
            AND table_name LIKE '%%vector%%'
        """
        cursor = self.db.execute(sql, (self.db.schema,))
        if cursor:
            return [row['table_name'] for row in cursor.fetchall()]
        return []
    
    def check_vector_table_dimension(self, table_name):
        """
        检查向量表的向量维度
        
        Args:
            table_name: 表名
        
        Returns:
            int: 向量维度，如果表不存在或无向量字段返回 None
        """
        sql = """
            SELECT atttypmod 
            FROM pg_attribute 
            WHERE attrelid = %s::regclass 
            AND attname = 'vector'
        """
        cursor = self.db.execute(sql, (table_name,))
        if cursor:
            result = cursor.fetchone()
            if result and result['atttypmod']:
                return result['atttypmod']
        return None