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
    
    def _detect_vector_index_type(self, table_name):
        """
        检测表中向量索引的类型（hnsw / ivfflat / none）

        通过查询 pg_indexes 的 indexdef 字段判断索引类型。

        Args:
            table_name: 表名

        Returns:
            str: 'hnsw'、'ivfflat' 或 'none'
        """
        try:
            idx_sql = """
                SELECT indexdef
                FROM pg_indexes
                WHERE schemaname = %s AND tablename = %s
            """
            cursor = self.db.execute(idx_sql, (self.db.schema, table_name))
            if cursor:
                for row in cursor.fetchall():
                    idx_def = row['indexdef'].lower()
                    if 'hnsw' in idx_def:
                        return 'hnsw'
                    if 'ivfflat' in idx_def:
                        return 'ivfflat'
        except Exception as e:
            logger.warning(f"检测索引类型失败 {table_name}: {e}")
        return 'none'

    def _set_index_search_param(self, table_name, top_n):
        """
        根据表的向量索引类型，设置对应的查询参数以确保召回数量充足

        HNSW 索引：设置 hnsw.ef_search >= top_n（默认值128，当 top_n > 128 时必须调大）
        IVFFlat 索引：设置 ivfflat.probes（默认值1，建议设为 sqrt(lists) 以提高召回率）
        无索引：不设置

        Args:
            table_name: 表名
            top_n: 期望召回的数量
        """
        index_type = self._detect_vector_index_type(table_name)

        if index_type == 'hnsw':
            ef_search = max(top_n, 128)
            self.db.execute(f"SET hnsw.ef_search = {ef_search}")
            logger.info(f"SET hnsw.ef_search = {ef_search} (top_n={top_n})")
        elif index_type == 'ivfflat':
            try:
                idx_sql = """
                    SELECT indexdef
                    FROM pg_indexes
                    WHERE schemaname = %s AND tablename = %s AND indexdef ILIKE '%%ivfflat%%'
                """
                cursor = self.db.execute(idx_sql, (self.db.schema, table_name))
                if cursor:
                    row = cursor.fetchone()
                    if row:
                        import re
                        match = re.search(r'lists\s*=\s*(\d+)', row['indexdef'], re.IGNORECASE)
                        if match:
                            lists = int(match.group(1))
                            probes = max(1, int(lists ** 0.5))
                            self.db.execute(f"SET ivfflat.probes = {probes}")
                            logger.info(f"SET ivfflat.probes = {probes} (lists={lists})")
                        else:
                            self.db.execute("SET ivfflat.probes = 10")
                            logger.info("SET ivfflat.probes = 10 (lists未知，使用默认值)")
            except Exception as e:
                logger.warning(f"设置 ivfflat.probes 失败: {e}")
                self.db.execute("SET ivfflat.probes = 10")
                logger.info("SET ivfflat.probes = 10 (回退默认值)")
        else:
            logger.info(f"表 {table_name} 无向量索引，使用顺序扫描")

    def check_index_exists(self, table_name, index_name):
        """
        检查索引是否已存在

        Args:
            table_name: 表名
            index_name: 索引名

        Returns:
            bool: 存在返回 True
        """
        check_sql = """
            SELECT 1 FROM pg_indexes
            WHERE schemaname = %s
            AND tablename = %s
            AND indexname = %s
        """
        cursor = self.db.execute(check_sql, (self.db.schema, table_name, index_name))
        if cursor and cursor.fetchone():
            return True
        return False

    def drop_vector_index(self, index_name):
        """
        删除向量索引

        Args:
            index_name: 索引名

        Returns:
            bool: 删除成功返回 True
        """
        sql = f"DROP INDEX IF EXISTS {index_name}"
        cursor = self.db.execute(sql)
        if cursor:
            self.db.commit()
            logger.info(f"Vector index {index_name} dropped successfully")
            return True
        return False

    def create_vector_index(self, table_name=None, index_name=None,
                            index_type='ivfflat', lists=None, m=None,
                            ef_construction=None, maintenance_work_mem=None):
        """
        创建向量索引（支持 ivfflat 和 hnsw 两种类型）

        Args:
            table_name: 表名，默认使用 Config.VECTOR_TABLE
            index_name: 索引名，默认使用 Config.INDEX_NAME
            index_type: 索引类型，'ivfflat' 或 'hnsw'
            lists: ivfflat 的 lists 参数，None 时自动计算
            m: hnsw 的 m 参数，None 时默认 16
            ef_construction: hnsw 的 ef_construction 参数，None 时默认 200
            maintenance_work_mem: 维护操作内存，如 '1GB'，None 时不修改

        Returns:
            bool: 创建成功返回 True
        """
        table_name = table_name or self.table_name
        index_name = index_name or self.index_name

        if self.check_index_exists(table_name, index_name):
            logger.info(f"Index {index_name} already exists, skipping creation")
            return True

        # 获取向量表数据量用于自动计算参数
        row_count = self.get_vector_count(table_name)

        # 自动计算 ivfflat lists 参数
        if index_type == 'ivfflat' and lists is None:
            if row_count <= 1_000_000:
                lists = max(100, min(4000, row_count // 1000))
            else:
                lists = max(100, min(4000, int(row_count ** 0.5)))
            logger.info(f"Auto-calculated ivfflat lists={lists} for {row_count} rows")

        # 自动计算 hnsw 参数
        if index_type == 'hnsw':
            if m is None:
                m = 16
            if ef_construction is None:
                ef_construction = 200
            logger.info(f"Using hnsw parameters: m={m}, ef_construction={ef_construction}")

        # 设置 maintenance_work_mem
        original_work_mem = None
        if maintenance_work_mem:
            try:
                cursor = self.db.execute("SHOW maintenance_work_mem")
                if cursor:
                    row = cursor.fetchone()
                    original_work_mem = row[0] if row else None
                self.db.execute(f"SET maintenance_work_mem = '{maintenance_work_mem}'")
                logger.info(f"Set maintenance_work_mem to {maintenance_work_mem} (original: {original_work_mem})")
            except Exception as e:
                logger.warning(f"Failed to set maintenance_work_mem: {e}")

        try:
            # 构建创建索引 SQL
            if index_type == 'ivfflat':
                sql = f"""
                    CREATE INDEX {index_name}
                    ON {table_name}
                    USING ivfflat (vector vector_l2_ops)
                    WITH (lists = {lists})
                """
            elif index_type == 'hnsw':
                sql = f"""
                    CREATE INDEX {index_name}
                    ON {table_name}
                    USING hnsw (vector vector_l2_ops)
                    WITH (m = {m}, ef_construction = {ef_construction})
                """
            else:
                logger.error(f"Unsupported index type: {index_type}")
                return False

            cursor = self.db.execute(sql)
            if cursor:
                self.db.commit()
                logger.info(f"Vector index {index_name} ({index_type}) created successfully on {table_name}")
                return True
            return False
        except Exception as e:
            logger.error(f"Failed to create vector index {index_name}: {e}")
            self.db.rollback()
            return False
        finally:
            # 恢复 maintenance_work_mem 为原始值
            if original_work_mem:
                try:
                    self.db.execute(f"SET maintenance_work_mem = '{original_work_mem}'")
                    logger.info(f"Restored maintenance_work_mem to {original_work_mem}")
                except Exception as e:
                    logger.warning(f"Failed to restore maintenance_work_mem: {e}")
    
    @staticmethod
    def _vector_to_pg_string(vec):
        arr = np.asarray(vec, dtype=np.float32).ravel()
        return np.array2string(arr, separator=',', max_line_width=np.inf,
                               threshold=np.inf, floatmode='fixed',
                               formatter={'float_kind': lambda x: f'{x:.8f}'})

    @staticmethod
    def _vectors_to_pg_strings(vectors):
        arr = np.asarray(vectors, dtype=np.float32)
        if arr.ndim == 1:
            return [VectorStore._vector_to_pg_string(arr)]
        n = arr.shape[0]
        results = [None] * n
        for i in range(n):
            results[i] = np.array2string(
                arr[i], separator=',', max_line_width=np.inf,
                threshold=np.inf, floatmode='fixed',
                formatter={'float_kind': lambda x: f'{x:.8f}'}
            )
        return results

    def insert_vectors(self, vectors, source_ids, addresses, table_name=None,
                       extra_data=None, table_type='enterprise',
                       insert_chunk_size=5000, commit_every_n_chunks=10):
        """
        批量插入向量数据（高性能版）。

        优化点：
        - 向量字符串转换使用 numpy vectorized 操作（比逐元素 repr() 快 10-20x）
        - 临时关闭 autocommit，批量事务提交（默认每 10 chunk/5万条 commit 一次）
        - finally 块确保 autocommit 一定恢复

        Args:
            vectors: 向量数组，形状为 (n, dim)
            source_ids: 源数据ID列表
            addresses: 地址文本列表
            table_name: 目标表名
            extra_data: 额外数据列表
            table_type: 表类型，'enterprise' 或 'standard'
            insert_chunk_size: 每次 execute_values 的向量数量
            commit_every_n_chunks: 每 N 个 chunk 提交一次事务

        Returns:
            int: 成功插入的记录数
        """
        table_name = table_name or self.table_name
        if len(vectors) == 0:
            return 0

        source_ids = [str(sid) for sid in source_ids]

        actual_dim = vectors.shape[1] if len(vectors.shape) > 1 else len(vectors[0])
        total = len(vectors)
        logger.debug(f"Inserting {total} vectors with dimension {actual_dim} into {table_name}")

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

        # ---- 事务控制：临时关闭 autocommit 进行批量提交 ----
        was_autocommit = self.db.conn.autocommit
        self.db.conn.autocommit = False
        inserted_count = 0
        total_chunks = (total + insert_chunk_size - 1) // insert_chunk_size

        try:
            for chunk_idx, chunk_start in enumerate(range(0, total, insert_chunk_size)):
                chunk_end = min(chunk_start + insert_chunk_size, total)
                chunk_vectors = vectors[chunk_start:chunk_end]
                vec_strs = self._vectors_to_pg_strings(chunk_vectors)

                values = []
                for i, idx in enumerate(range(chunk_start, chunk_end)):
                    if table_type == 'enterprise':
                        enterprise_name = extra_data[idx] if extra_data else ''
                        values.append((source_ids[idx], enterprise_name, addresses[idx], vec_strs[i]))
                    else:
                        room_no = extra_data[idx] if extra_data else ''
                        values.append((source_ids[idx], addresses[idx], room_no, vec_strs[i]))

                psycopg2.extras.execute_values(
                    self.db.cursor, sql, values, template=template, page_size=1000
                )
                inserted_count += len(values)

                if (chunk_idx + 1) % commit_every_n_chunks == 0 or chunk_idx == total_chunks - 1:
                    self.db.conn.commit()
                    logger.debug(f"Committed after chunk {chunk_idx + 1}/{total_chunks}")

                logger.info(f"已插入 {inserted_count}/{total} 条向量到 {table_name}...")

            logger.info(f"✅ 成功插入 {inserted_count} 条向量到 {table_name}")

            sample_norm = np.linalg.norm(vectors[0])
            logger.info(f"样本向量L2范数（应≈1.0）：{sample_norm:.8f}")

            self._verify_inserted_vectors(table_name, source_ids[:3] if len(source_ids) >= 3 else source_ids)

            return inserted_count
        except Exception as e:
            logger.error(f"❌ 插入向量失败：{str(e)}")
            try:
                self.db.conn.rollback()
            except Exception:
                pass
            return 0
        finally:
            # 恢复 autocommit 前必须先结束当前事务，否则 psycopg2 报错
            try:
                self.db.conn.commit()
            except Exception:
                try:
                    self.db.conn.rollback()
                except Exception:
                    pass
            self.db.conn.autocommit = was_autocommit

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
                    SELECT source_id, address, 1 - ((vector <-> vector)^2 / 2.0) as self_inner_product
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
        
        使用 pgvector 的 L2 距离操作符（<->）进行近似最近邻搜索。
        向量已归一化，L2 距离排序与余弦相似度排序等价，
        通过公式 1 - (L2_distance^2 / 2) 将 L2 距离转换为余弦相似度。
        
        Args:
            query_vector: 查询向量
            top_n: 返回前N个最相似的结果
            table_name: 目标表名
        
        Returns:
            list: 包含 source_id, address, similarity 的字典列表
        """
        table_name = table_name or self.table_name
        query_vector = np.array(query_vector)
        
        self._set_index_search_param(table_name, top_n)

        sql = f"""
            SELECT source_id, address, 1 - ((vector <-> %s) ^ 2) / 2.0 as similarity
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
        使用 L2 距离（欧氏距离）排序召回，通过公式转换为余弦相似度：
        similarity = 1 - (L2_distance^2 / 2)，归一化向量 L2 距离范围为 [0, 2]，
        对应余弦相似度范围为 [0, 1]。
        
        Args:
            enterprise_table: 企业向量表名
            standard_table: 标准地址向量表名
            top_n: 每个企业召回的候选数量
            similarity_threshold: 相似度阈值（0-1），低于此阈值的候选将被过滤，None表示不过滤
        
        Returns:
            list: 召回结果列表，每个元素包含企业信息和候选地址列表
        """
        logger.info(f"Starting batch recall from {enterprise_table} to {standard_table}, top_n={top_n}, threshold={similarity_threshold}")
        
        self._set_index_search_param(standard_table, top_n)

        threshold_condition = ""
        if similarity_threshold is not None:
            threshold_condition = f"WHERE 1 - ((c.vector <-> a.vector) ^ 2) / 2.0 >= {float(similarity_threshold)}"

        sql = f"""
            SELECT
                c.source_id AS enterprise_id,
                c.enterprise_name,
                c.address AS enterprise_address,
                a.source_id AS standard_id,
                a.address AS standard_address,
                a.room_no,
                1 - ((c.vector <-> a.vector) ^ 2) / 2.0 AS similarity
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
        获取所有向量表名（表名包含 'vector'），按创建时间倒序排列（最新创建的排最前）

        Returns:
            list: 向量表名列表
        """
        sql = """
            SELECT c.relname AS table_name
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = %s
            AND c.relname LIKE '%%vector%%'
            AND c.relkind = 'r'
            ORDER BY c.oid DESC
        """
        cursor = self.db.execute(sql, (self.db.schema,))
        if cursor:
            return [row['table_name'] for row in cursor.fetchall()]
        return []

    def rename_vector_table(self, old_name, new_name):
        """
        重命名向量表

        Args:
            old_name: 原表名
            new_name: 新表名

        Returns:
            bool: 重命名成功返回 True
        """
        sql = f"ALTER TABLE {old_name} RENAME TO {new_name}"
        cursor = self.db.execute(sql)
        if cursor:
            self.db.commit()
            logger.info(f"Vector table renamed from {old_name} to {new_name}")
            return True
        return False

    def check_table_exists(self, table_name):
        """
        检查表是否存在

        Args:
            table_name: 表名

        Returns:
            bool: 存在返回 True
        """
        sql = """
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = %s AND table_name = %s
        """
        cursor = self.db.execute(sql, (self.db.schema, table_name))
        if cursor and cursor.fetchone():
            return True
        return False
    
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

    def get_vector_table_detail(self, table_name):
        """
        获取向量表的详细信息

        Args:
            table_name: 表名

        Returns:
            dict: 包含表详细信息的字典，失败返回 None
                - table_name: 表名
                - row_count: 数据行数
                - vector_dim: 向量维度
                - columns: 字段列表 [(字段名, 数据类型), ...]
                - indexes: 索引列表 [(索引名, 索引类型), ...]
                - table_size: 表大小（可读格式）
                - created_at: 最早创建时间
        """
        try:
            # 数据行数
            row_count = self.get_vector_count(table_name)

            # 向量维度
            vector_dim = self.check_vector_table_dimension(table_name)

            # 字段信息
            col_sql = """
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_schema = %s AND table_name = %s
                ORDER BY ordinal_position
            """
            cursor = self.db.execute(col_sql, (self.db.schema, table_name))
            columns = [(row['column_name'], row['data_type']) for row in cursor.fetchall()] if cursor else []

            # 索引信息
            idx_sql = """
                SELECT indexname, indexdef
                FROM pg_indexes
                WHERE schemaname = %s AND tablename = %s
            """
            cursor = self.db.execute(idx_sql, (self.db.schema, table_name))
            indexes = []
            if cursor:
                for row in cursor.fetchall():
                    idx_name = row['indexname']
                    idx_def = row['indexdef']
                    # 从 indexdef 中提取索引类型
                    idx_type = 'btree'
                    if 'ivfflat' in idx_def.lower():
                        idx_type = 'ivfflat'
                    elif 'hnsw' in idx_def.lower():
                        idx_type = 'hnsw'
                    elif 'gin' in idx_def.lower():
                        idx_type = 'gin'
                    elif 'gist' in idx_def.lower():
                        idx_type = 'gist'
                    indexes.append((idx_name, idx_type))

            # 表大小
            size_sql = """
                SELECT pg_size_pretty(pg_total_relation_size(%s::regclass)) as size
            """
            cursor = self.db.execute(size_sql, (table_name,))
            table_size = cursor.fetchone()['size'] if cursor else '未知'

            # 最早创建时间
            time_sql = f"""
                SELECT MIN(created_at) as created_at FROM {table_name}
            """
            cursor = self.db.execute(time_sql)
            created_at = cursor.fetchone()['created_at'] if cursor else None

            return {
                'table_name': table_name,
                'row_count': row_count,
                'vector_dim': vector_dim,
                'columns': columns,
                'indexes': indexes,
                'table_size': table_size,
                'created_at': created_at
            }
        except Exception as e:
            logger.error(f"获取向量表详情失败 {table_name}: {e}")
            return None

    def disable_autovacuum(self, table_name):
        """
        批量导入前禁用 autovacuum，防止 autovacuum 与批量 INSERT 争抢 I/O。

        Args:
            table_name: 目标表名

        Returns:
            bool: 成功返回 True
        """
        sql = f"ALTER TABLE {table_name} SET (autovacuum_enabled = false)"
        cursor = self.db.execute(sql)
        if cursor:
            logger.info(f"Autovacuum 已禁用: {table_name}")
            return True
        return False

    def enable_autovacuum(self, table_name):
        """
        批量导入完成后重新启用 autovacuum。

        Args:
            table_name: 目标表名

        Returns:
            bool: 成功返回 True
        """
        sql = f"ALTER TABLE {table_name} SET (autovacuum_enabled = true)"
        cursor = self.db.execute(sql)
        if cursor:
            logger.info(f"Autovacuum 已恢复: {table_name}")
            return True
        return False

    def vacuum_table(self, table_name, analyze=True):
        """
        对表执行 VACUUM（和可选 ANALYZE），回收空间并更新统计信息。
        VACUUM 不能在事务块内执行，因此临时设置 autocommit=True。

        Args:
            table_name: 目标表名
            analyze: 是否同时执行 ANALYZE

        Returns:
            bool: 成功返回 True
        """
        if analyze:
            sql = f"VACUUM ANALYZE {table_name}"
        else:
            sql = f"VACUUM {table_name}"

        was_autocommit = self.db.conn.autocommit
        self.db.conn.autocommit = True
        try:
            cursor = self.db.execute(sql)
            if cursor:
                logger.info(f"VACUUM {'ANALYZE ' if analyze else ''}完成: {table_name}")
                return True
            return False
        except Exception as e:
            logger.error(f"VACUUM 失败: {table_name}: {e}")
            return False
        finally:
            self.db.conn.autocommit = was_autocommit