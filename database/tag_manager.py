"""
标签管理模块
===========

管理匹配标签的持久化存储，基于 match_tags 配置表。

核心功能：
    1. 创建 match_tags 配置表
    2. 新建标签（同时创建关联的 recall/match 数据表）
    3. 列出已有标签
    4. 删除标签（同时删除关联的数据表）

表结构：
    match_tags:
        id: 主键
        tag_name: 标签显示名（原始输入，如"福田"）
        prefix: 表名前缀（拼音/英文，如"futian"）
        recall_table: 召回结果表名
        match_table: 匹配结果表名
        created_at: 创建时间
"""

from utils.pinyin_utils import tag_to_prefix, get_tag_tables
from utils.logger import logger
from database.data_loader import DataLoader


class TagManager:
    """
    标签管理器

    负责标签的持久化存储和关联数据表的管理。
    """

    def __init__(self, db_conn):
        self.db = db_conn
        self._ensure_config_table()

    def _ensure_config_table(self):
        """确保 match_tags 配置表存在"""
        sql = """
            CREATE TABLE IF NOT EXISTS match_tags (
                id SERIAL PRIMARY KEY,
                tag_name VARCHAR(255) NOT NULL,
                prefix VARCHAR(100) NOT NULL UNIQUE,
                recall_table VARCHAR(255) NOT NULL,
                match_table VARCHAR(255) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """
        self.db.execute(sql)
        self.db.commit()

    def create_tag(self, tag_name):
        """
        创建新标签，同时创建关联的 recall 和 match 数据表

        Args:
            tag_name: 标签显示名

        Returns:
            dict: {'tag_name', 'prefix', 'recall_table', 'match_table'} 或 None（失败时）
        """
        prefix = tag_to_prefix(tag_name)
        recall_table, match_table = get_tag_tables(prefix)

        # 检查 prefix 是否已存在
        existing = self.get_tag_by_prefix(prefix)
        if existing:
            logger.warning(f"标签前缀 '{prefix}' 已存在，返回已有标签")
            return existing

        if not tag_name.strip():
            return None

        # 插入配置记录
        sql = """
            INSERT INTO match_tags (tag_name, prefix, recall_table, match_table)
            VALUES (%s, %s, %s, %s)
        """
        cursor = self.db.execute(sql, (tag_name.strip(), prefix, recall_table, match_table))
        if not cursor:
            return None
        self.db.commit()

        # 创建关联数据表
        data_loader = DataLoader(self.db)
        data_loader.create_recall_table(recall_table)
        data_loader.create_result_table(match_table)

        logger.warning(f"标签已创建: {tag_name} → prefix={prefix}")
        return {
            'tag_name': tag_name.strip(),
            'prefix': prefix,
            'recall_table': recall_table,
            'match_table': match_table
        }

    def get_all_tags(self):
        """
        获取所有已有标签

        Returns:
            list: 标签字典列表，每个包含 tag_name, prefix, recall_table, match_table
        """
        sql = "SELECT id, tag_name, prefix, recall_table, match_table, created_at FROM match_tags ORDER BY id"
        cursor = self.db.execute(sql)
        if cursor:
            return [dict(row) for row in cursor.fetchall()]
        return []

    def get_tag_by_prefix(self, prefix):
        """
        根据前缀查询标签

        Args:
            prefix: 表名前缀

        Returns:
            dict 或 None
        """
        sql = "SELECT id, tag_name, prefix, recall_table, match_table FROM match_tags WHERE prefix = %s"
        cursor = self.db.execute(sql, (prefix,))
        if cursor:
            row = cursor.fetchone()
            return dict(row) if row else None
        return None

    def delete_tag(self, prefix):
        """
        删除标签及其关联的数据表

        Args:
            prefix: 表名前缀

        Returns:
            bool: 删除成功返回 True
        """
        tag = self.get_tag_by_prefix(prefix)
        if not tag:
            return False

        # 删除关联数据表
        try:
            self.db.drop_table(tag['recall_table'])
        except Exception as e:
            logger.warning(f"删除召回表失败: {tag['recall_table']}: {e}")

        try:
            self.db.drop_table(tag['match_table'])
        except Exception as e:
            logger.warning(f"删除匹配表失败: {tag['match_table']}: {e}")

        # 删除配置记录
        sql = "DELETE FROM match_tags WHERE prefix = %s"
        self.db.execute(sql, (prefix,))
        self.db.commit()

        logger.warning(f"标签已删除: {tag['tag_name']} (prefix={prefix})")
        return True
