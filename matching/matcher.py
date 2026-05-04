"""
地址匹配模块
============

实现两阶段地址匹配流程：
    阶段1（粗召回）：通过向量相似度检索每个企业前N条最相似的标准地址候选
    阶段2（精排）：使用MGeo地址相似度匹配模型对召回结果进行精准排序

核心功能：
    1. 批量召回 - 使用SQL向量化查询实现高效召回
    2. MGeo精排 - 使用阿里MGeo地址匹配模型进行精准匹配
    3. 异步执行 - 支持后台异步执行匹配任务
    4. 任务控制 - 支持暂停、恢复、停止匹配任务

技术要点：
    - 使用 PostgreSQL + pgvector 进行向量召回
    - 使用 MGeo 模型进行精排匹配
    - 支持任务状态监控和进度回调
"""

import time
import threading
from config import Config
from database.data_loader import DataLoader
from database.vector_store import VectorStore
from model.embedding import AddressEmbedder
from matching.ranking import RankingEngine, determine_match_status
from utils.logger import logger

class AddressMatcher:
    """
    地址匹配器
    
    实现两阶段地址匹配流程：粗召回 + MGeo精排
    
    Attributes:
        db: 数据库连接对象
        data_loader: 数据加载器
        vector_store: 向量存储管理器
        embedder: 地址向量化器
        ranking_engine: 精排引擎
        threshold: 相似度阈值
        mode: 匹配模式 ('two_stage' 或其他)
        is_running: 是否正在运行
        is_paused: 是否暂停
        processed_count: 已处理数量
        total_count: 总数量
        current_stage: 当前阶段
        progress: 进度(0-1)
        speed: 处理速度(条/秒)
        remaining_time: 预计剩余时间(秒)
        error_message: 错误信息
        matching_thread: 匹配线程
    """
    
    def __init__(self, db_connection, device=None, mode='two_stage'):
        """
        初始化地址匹配器
        
        Args:
            db_connection: DBConnection 对象
            device: 运行设备 ('cuda' 或 'cpu')
            mode: 匹配模式，默认 'two_stage'（两阶段匹配）
        """
        device = device or Config.DEVICE
        self.db = db_connection
        self.data_loader = DataLoader(db_connection)
        self.vector_store = VectorStore(db_connection)
        self.embedder = AddressEmbedder(device=device)
        self.ranking_engine = RankingEngine(device=device)
        self.threshold = Config.SIMILARITY_THRESHOLD
        self.mode = mode
        self.is_running = False
        self.is_paused = False
        self.processed_count = 0
        self.total_count = 0
        self.start_time = None
        self.current_stage = ''
        self.progress = 0.0
        self.speed = 0.0
        self.remaining_time = 0.0
        self.status_message = ''
        self.error_message = ''
        self.matching_thread = None
    
    def set_threshold(self, threshold):
        """
        设置相似度阈值
        
        Args:
            threshold: 相似度阈值 (0-1)
        """
        self.threshold = threshold
        self.ranking_engine.threshold = threshold
    
    def get_status(self):
        """
        获取当前匹配状态
        
        Returns:
            dict: 状态信息字典
        """
        return {
            'is_running': self.is_running,
            'is_paused': self.is_paused,
            'processed_count': self.processed_count,
            'total_count': self.total_count,
            'current_stage': self.current_stage,
            'progress': self.progress,
            'speed': self.speed,
            'remaining_time': self.remaining_time,
            'status_message': self.status_message,
            'error_message': self.error_message
        }
    
    def run_full_pipeline(self, enterprise_table, enterprise_id_col, enterprise_name_col, 
                          enterprise_address_col, standard_table, standard_id_col, 
                          standard_address_col, result_table=None, progress_callback=None):
        """
        运行完整的匹配流程
        
        Args:
            enterprise_table: 企业向量表名
            enterprise_id_col: 企业标识字段名
            enterprise_name_col: 企业名字段名
            enterprise_address_col: 企业地址字段名
            standard_table: 标准地址向量表名
            standard_id_col: 标准地址编码字段名
            standard_address_col: 标准地址字段名
            result_table: 结果表名（可选）
            progress_callback: 进度回调函数（可选）
        """
        self.is_running = True
        self.is_paused = False
        self.processed_count = 0
        self.start_time = time.time()
        self.error_message = ''
        
        try:
            self.total_count = self.vector_store.get_vector_count(enterprise_table)
            logger.info(f"Starting full matching pipeline. Total enterprises: {self.total_count}")
            
            # 确保结果表存在
            self.data_loader.create_result_table(result_table)
            
            # 根据模式选择不同的匹配策略
            if self.mode == 'two_stage':
                # 两阶段匹配：粗召回 + MGeo精排
                self.run_two_stage_pipeline(
                    enterprise_table, enterprise_id_col, enterprise_name_col, enterprise_address_col,
                    standard_table, standard_id_col, standard_address_col,
                    result_table, progress_callback
                )
            else:
                # 单阶段匹配：直接对每条记录进行匹配
                for df in self.data_loader.load_enterprise_data(
                    enterprise_table, enterprise_id_col, enterprise_name_col, enterprise_address_col
                ):
                    # 处理暂停状态
                    while self.is_paused and self.is_running:
                        time.sleep(1)
                    
                    # 检查是否被停止
                    if not self.is_running:
                        logger.info("Matching pipeline stopped by user")
                        break
                    
                    # 批量匹配
                    results = self.match_batch(df)
                    self.data_loader.insert_match_results(results, result_table)
                    
                    # 更新进度
                    self.processed_count += len(df)
                    
                    if progress_callback:
                        elapsed_time = time.time() - self.start_time
                        self.speed = self.processed_count / elapsed_time if elapsed_time > 0 else 0
                        self.progress = self.processed_count / self.total_count
                        self.remaining_time = (self.total_count - self.processed_count) / self.speed if self.speed > 0 else 0
                        
                        progress_callback({
                            'stage': 'matching',
                            'processed': self.processed_count,
                            'total': self.total_count,
                            'progress': self.progress,
                            'speed': self.speed,
                            'remaining_time': self.remaining_time
                        })
            
            logger.info(f"Matching pipeline completed. Processed: {self.processed_count}")
            
        except Exception as e:
            logger.error(f"Matching pipeline failed: {str(e)}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            self.error_message = str(e)
            raise
        finally:
            self.is_running = False
    
    def run_two_stage_pipeline(self, enterprise_table, enterprise_id_col, enterprise_name_col, 
                               enterprise_address_col, standard_table, standard_id_col, 
                               standard_address_col, result_table=None, progress_callback=None):
        """
        两阶段匹配流程（核心方法）
        
        阶段1：粗召回 - 使用向量相似度检索每个企业前N条最相似的标准地址候选
        阶段2：精排 - 使用MGeo模型对召回结果进行精准排序，选出最优匹配
        
        Args:
            enterprise_table: 企业向量表名
            enterprise_id_col: 企业标识字段名
            enterprise_name_col: 企业名字段名
            enterprise_address_col: 企业地址字段名
            standard_table: 标准地址向量表名
            standard_id_col: 标准地址编码字段名
            standard_address_col: 标准地址字段名
            result_table: 结果表名（可选）
            progress_callback: 进度回调函数（可选）
        """
        logger.info("Starting two-stage matching pipeline...")
        start_time = time.time()
        
        # ========== 阶段1：粗召回 ==========
        self.current_stage = 'Stage 1: 粗召回'
        self.status_message = '正在执行粗召回...'
        logger.info("Stage 1: SQL-based batch recall...")
        
        stage1_start = time.time()
        
        # 确保召回表存在并清空
        self.data_loader.create_recall_table()
        self.data_loader.truncate_recall_table()
        
        # 执行批量召回：为每个企业找到最相似的标准地址候选
        logger.info(f"Calling batch_recall with enterprise_table={enterprise_table}, standard_table={standard_table}")
        recall_results = self.vector_store.batch_recall(
            enterprise_table,
            standard_table,
            top_n=Config.RECALL_TOP_N,
            similarity_threshold=self.threshold
        )
        logger.info(f"batch_recall returned {len(recall_results)} results")
        
        recall_count = len(recall_results)
        candidate_count = sum(len(item['candidates']) for item in recall_results)
        
        # 保存召回结果到数据库
        logger.info(f"Inserting {len(recall_results)} recall results with {candidate_count} candidates")
        inserted = self.data_loader.insert_recall_results(recall_results)
        logger.info(f"Inserted {inserted} recall results")
        
        stage1_end = time.time()
        stage1_time = stage1_end - stage1_start
        
        # 更新进度（粗召回占40%）
        self.progress = 0.4
        self.processed_count = recall_count
        
        if progress_callback:
            progress_callback({
                'stage': '粗召回完成',
                'processed': recall_count,
                'total': self.total_count,
                'progress': 0.4,
                'speed': recall_count / stage1_time if stage1_time > 0 else 0,
                'remaining_time': 0
            })
        
        logger.info(f"Stage 1 completed. Recalled {candidate_count} candidates for {recall_count} enterprises in {stage1_time:.2f}s")
        
        if recall_count == 0:
            logger.warning("No enterprises found for matching")
            return
        
        # ========== 阶段2：MGeo精排 ==========
        self.current_stage = 'Stage 2: MGeo精排'
        self.status_message = '正在执行MGeo精排...'
        logger.info("Stage 2: MGeo model re-ranking...")
        
        # 清空结果表
        self.data_loader.truncate_result_table(result_table)
        
        # 使用优化的批量精排方法（一次性批量预测所有候选）
        logger.info(f"Using optimized batch ranking for {len(recall_results)} enterprises, threshold={self.threshold}")
        final_results = self.ranking_engine.batch_rank_optimized(recall_results, similarity_threshold=self.threshold)
        processed_count = len(final_results)
        
        # 批量写入数据库（每1000条）
        for i in range(0, len(final_results), 1000):
            batch = final_results[i:i+1000]
            inserted = self.data_loader.insert_match_results(batch, result_table)
            logger.info(f"Inserted {inserted} match results")
        
        stage2_end = time.time()
        stage2_time = stage2_end - stage1_end
        
        total_time = stage2_end - start_time
        
        logger.info(f"Stage 2 completed in {stage2_time:.2f}s")
        logger.info(f"Two-stage matching completed. Total time: {total_time:.2f}s")
        
        self.status_message = '匹配完成'
    
    def match_batch(self, df):
        """
        批量匹配（单阶段模式使用）
        
        Args:
            df: 包含 id, name, address 列的 DataFrame
        
        Returns:
            list: 匹配结果列表
        """
        results = []
        
        addresses = df['address'].tolist()
        enterprise_ids = df['id'].tolist()
        enterprise_names = df['name'].tolist()
        
        # 为每个地址获取候选标准地址
        candidates_list = []
        for addr in addresses:
            vector = self.embedder.get_embedding(addr)
            candidates = self.vector_store.search_vectors(vector, top_n=Config.RECALL_TOP_N)
            candidates_list.append({'address': addr, 'candidates': candidates})
        
        # 使用精排引擎进行排序
        ranked_results = self.ranking_engine.batch_rank(addresses, candidates_list)
        
        # 整理结果
        for i, result in enumerate(ranked_results):
            results.append({
                'enterprise_id': enterprise_ids[i],
                'enterprise_name': enterprise_names[i],
                'enterprise_address': addresses[i],
                'address_id': result['address_id'],
                'standard_address': result['standard_address'],
                'room_no': '',
                'exact_match': result.get('exact_match', 0.0),
                'partial_match': result.get('partial_match', 0.0),
                'not_match': result.get('not_match', 1.0),
                'match_status': result['match_status']
            })
        
        return results
    
    def build_enterprise_vectors(self, enterprise_table, enterprise_id_col, enterprise_name_col, enterprise_address_col, 
                                  progress_callback=None):
        """
        构建企业向量（向量化企业表）
        
        Args:
            enterprise_table: 企业表名
            enterprise_id_col: 企业标识字段
            enterprise_name_col: 企业名字段
            enterprise_address_col: 企业地址字段
            progress_callback: 进度回调函数
        
        Returns:
            int: 已处理记录数
        """
        total_count = self.data_loader.get_valid_address_count(enterprise_table, enterprise_address_col)
        processed_count = 0
        
        logger.info(f"Building enterprise vectors. Total: {total_count}")
        
        # 创建向量表
        self.vector_store.create_vector_table(Config.ENTERPRISE_VECTOR_TABLE, table_type='enterprise')
        
        # 批量加载数据并向量化
        for df in self.data_loader.load_enterprise_data(
            enterprise_table, enterprise_id_col, enterprise_name_col, enterprise_address_col
        ):
            if not self.is_running:
                break
            
            addresses = df['address'].tolist()
            source_ids = df['id'].tolist()
            names = df['name'].tolist()
            
            # 向量化
            vectors = self.embedder.encode(addresses)
            # 插入向量表
            self.vector_store.insert_vectors(vectors, source_ids, addresses, Config.ENTERPRISE_VECTOR_TABLE, names, table_type='enterprise')
            
            processed_count += len(addresses)
            
            if progress_callback:
                progress = processed_count / total_count
                progress_callback({
                    'stage': 'enterprise_vectorization',
                    'processed': processed_count,
                    'total': total_count,
                    'progress': progress
                })
        
        # 创建向量索引
        self.vector_store.create_vector_index(
            Config.ENTERPRISE_VECTOR_TABLE, 
            'idx_enterprise_vector'
        )
        
        logger.info(f"Enterprise vectors built. Total: {processed_count}")
        return processed_count
    
    def build_standard_vectors(self, standard_table, standard_id_col, standard_address_col, 
                               room_col=None, progress_callback=None):
        """
        构建标准地址向量（向量化标准地址表）
        
        Args:
            standard_table: 标准地址表名
            standard_id_col: 地址编码字段
            standard_address_col: 标准地址字段
            room_col: 房号字段（可选）
            progress_callback: 进度回调函数
        
        Returns:
            int: 已处理记录数
        """
        total_count = self.data_loader.get_valid_address_count(standard_table, standard_address_col)
        processed_count = 0
        
        logger.info(f"Building standard address vectors. Total: {total_count}")
        
        # 创建向量表
        self.vector_store.create_vector_table(Config.STANDARD_VECTOR_TABLE, table_type='standard')
        
        # 批量加载数据并向量化
        for df in self.data_loader.load_standard_addresses(
            standard_table, standard_id_col, standard_address_col, room_col
        ):
            if not self.is_running:
                break
            
            addresses = df['address'].tolist()
            source_ids = df['id'].tolist()
            room_nos = df.get('room_no', [''] * len(addresses)).tolist()
            
            # 向量化
            vectors = self.embedder.encode(addresses)
            # 插入向量表
            self.vector_store.insert_vectors(vectors, source_ids, addresses, Config.STANDARD_VECTOR_TABLE, room_nos, table_type='standard')
            
            processed_count += len(addresses)
            
            if progress_callback:
                progress = processed_count / total_count
                progress_callback({
                    'stage': 'standard_vectorization',
                    'processed': processed_count,
                    'total': total_count,
                    'progress': progress
                })
        
        # 创建向量索引
        self.vector_store.create_vector_index(
            Config.STANDARD_VECTOR_TABLE, 
            'idx_standard_vector'
        )
        
        logger.info(f"Standard address vectors built. Total: {processed_count}")
        return processed_count
    
    def pause(self):
        """暂停匹配任务"""
        self.is_paused = True
        logger.info("Matching paused")
    
    def resume(self):
        """恢复匹配任务"""
        self.is_paused = False
        logger.info("Matching resumed")
    
    def stop(self):
        """停止匹配任务"""
        self.is_running = False
        self.is_paused = False
        logger.info("Matching stopped")
    
    def start_async(self, enterprise_table, enterprise_id_col, enterprise_name_col, 
                    enterprise_address_col, standard_table, standard_id_col, 
                    standard_address_col, result_table=None, progress_callback=None):
        """
        异步启动匹配任务
        
        Args:
            enterprise_table: 企业向量表名
            enterprise_id_col: 企业标识字段名
            enterprise_name_col: 企业名字段名
            enterprise_address_col: 企业地址字段名
            standard_table: 标准地址向量表名
            standard_id_col: 标准地址编码字段名
            standard_address_col: 标准地址字段名
            result_table: 结果表名（可选）
            progress_callback: 进度回调函数（可选）
        """
        if self.matching_thread and self.matching_thread.is_alive():
            logger.warning("Matching thread is already running")
            return
        
        # 启动后台线程执行匹配
        self.matching_thread = threading.Thread(
            target=self.run_full_pipeline,
            args=(enterprise_table, enterprise_id_col, enterprise_name_col, 
                  enterprise_address_col, standard_table, standard_id_col, 
                  standard_address_col, result_table, progress_callback),
            daemon=True
        )
        self.matching_thread.start()
    
    def start_recall_async(self, enterprise_table, standard_table, top_n=50, 
                          progress_callback=None, completed_callback=None):
        """
        异步启动粗召回任务（分步执行模式）
        
        Args:
            enterprise_table: 企业向量表名
            standard_table: 标准地址向量表名
            top_n: 召回数量
            progress_callback: 进度回调函数
            completed_callback: 完成回调函数
        """
        if self.matching_thread and self.matching_thread.is_alive():
            logger.warning("Matching thread is already running")
            return
        
        def recall_task():
            """粗召回任务"""
            try:
                self.is_running = True
                self.is_paused = False
                self.current_stage = '数据粗召回'
                self.status_message = '正在执行粗召回...'
                
                stage1_start = time.time()
                
                # 确保召回表存在并清空
                self.data_loader.create_recall_table()
                self.data_loader.truncate_recall_table()
                
                # 执行批量召回
                logger.info(f"Starting batch recall: {enterprise_table} -> {standard_table}")
                recall_results = self.vector_store.batch_recall(
                    enterprise_table,
                    standard_table,
                    top_n=top_n,
                    similarity_threshold=self.threshold
                )
                
                recall_count = len(recall_results)
                candidate_count = sum(len(item['candidates']) for item in recall_results)
                
                logger.info(f"[粗召回] 共召回 {recall_count} 家企业，候选地址 {candidate_count} 条")
                
                # 保存召回结果到数据库
                logger.info("[粗召回] 开始写入recall_results表...")
                inserted = self.data_loader.insert_recall_results(recall_results)
                logger.info(f"[粗召回] 数据写入成功！共插入 {inserted} 条记录到recall_results表")
                
                stage1_time = time.time() - stage1_start
                
                # 更新进度
                self.progress = 1.0
                self.processed_count = recall_count
                self.speed = recall_count / stage1_time if stage1_time > 0 else 0
                
                if progress_callback:
                    progress_callback({
                        'stage': '数据粗召回完成',
                        'processed': recall_count,
                        'total': recall_count,
                        'progress': 1.0,
                        'speed': self.speed,
                        'remaining_time': 0
                    })
                
                logger.info(f"Recall completed: {candidate_count} candidates for {recall_count} enterprises")
                
                # 设置明确的完成状态
                self.current_stage = '数据粗召回完成'
                self.status_message = '粗召回完成'
                
                # 调用完成回调
                if completed_callback:
                    completed_callback(recall_results)
                
            except Exception as e:
                logger.error(f"Recall failed: {str(e)}")
                self.error_message = str(e)
                raise
            finally:
                self.is_running = False
        
        # 启动后台线程
        self.matching_thread = threading.Thread(target=recall_task, daemon=True)
        self.matching_thread.start()
    
    def start_ranking_async(self, progress_callback=None, completed_callback=None):
        """
        异步启动MGeo精排任务（基于recall_results表）
        
        Args:
            progress_callback: 进度回调函数
            completed_callback: 完成回调函数
        """
        if self.matching_thread and self.matching_thread.is_alive():
            logger.warning("Matching thread is already running")
            return
        
        def ranking_task():
            """精排任务"""
            try:
                self.is_running = True
                self.is_paused = False
                self.current_stage = 'MGeo精确匹配'
                self.status_message = '正在执行MGeo精排...'
                
                start_time = time.time()
                
                # 从recall_results表加载召回结果
                recall_results = self.data_loader.load_recall_results()
                total = len(recall_results)
                self.total_count = total
                
                if total == 0:
                    logger.warning("No recall results found")
                    if completed_callback:
                        completed_callback(0)
                    return
                
                logger.info(f"Starting MGeo ranking for {total} enterprises")
                
                # 确保结果表存在并清空
                self.data_loader.create_result_table()
                self.data_loader.truncate_result_table()
                
                # 使用优化的批量精排方法（一次性批量预测所有候选）
                logger.info(f"Using optimized batch ranking for {total} enterprises, threshold={self.threshold}")
                final_results = self.ranking_engine.batch_rank_optimized(recall_results, similarity_threshold=self.threshold)
                match_count = len(final_results)
                
                # 批量写入数据库（每1000条）
                for i in range(0, len(final_results), 1000):
                    batch = final_results[i:i+1000]
                    inserted = self.data_loader.insert_match_results(batch)
                    logger.info(f"Inserted {inserted} match results")
                
                total_time = time.time() - start_time
                
                logger.info(f"MGeo ranking completed. Total time: {total_time:.2f}s, Matches: {match_count}")
                
                # 调用完成回调
                if completed_callback:
                    completed_callback(match_count)
                
                self.status_message = 'MGeo精确匹配完成'
                self.progress = 1.0
                self.processed_count = match_count
                
            except Exception as e:
                logger.error(f"Ranking failed: {str(e)}")
                self.error_message = str(e)
                raise
            finally:
                self.is_running = False
        
        # 启动后台线程
        self.matching_thread = threading.Thread(target=ranking_task, daemon=True)
        self.matching_thread.start()