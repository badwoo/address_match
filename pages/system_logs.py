"""
系统日志页面
===========
实时日志查看、数据库日志查看、向量调试测试。
"""

import streamlit as st
import time
from database.connection import DBConnection
from config import Config
from app_common import _get_cached_db_connection


def show_system_logs():
    st.subheader("系统日志")

    # 显示内存中的日志（实时）
    from utils.logger import get_log_messages, clear_logs, get_db_logs, clear_db_logs

    log_messages = get_log_messages()
    if log_messages:
        memory_logs = []
        for log in log_messages[-500:]:
            time_str = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(log['time']))
            memory_logs.append(f"{time_str} - {log['level']} - {log['message']}")

        memory_content = '\n'.join(memory_logs)
        st.text_area("实时日志（内存）", memory_content, height=300)

        if st.button("清空内存日志"):
            clear_logs()
            st.rerun()
    else:
        st.info("暂无内存日志")

    st.divider()

    # 显示数据库日志
    st.subheader("数据库存储日志")
    if st.session_state.connected:
        db_config = st.session_state.db_config
        db_conn = _get_cached_db_connection(
            host=db_config['host'],
            port=db_config['port'],
            schema=db_config['schema'],
            dbname=db_config['dbname'],
            user=db_config['user'],
            password=db_config['password']
        )
        if db_conn is not None:
            col1, col2 = st.columns([1, 4])
            with col1:
                log_level_filter = st.selectbox("日志级别", ['全部', 'WARNING', 'ERROR'], key='db_log_level')
            with col2:
                st.write("")
                st.write("")
                if st.button("清空数据库日志"):
                    clear_db_logs(db_conn)
                    st.success("数据库日志已清空")
                    st.rerun()

            level = None if log_level_filter == '全部' else log_level_filter
            db_logs = get_db_logs(db_conn, limit=500, level=level)
            if db_logs:
                log_lines = []
                for log in db_logs:
                    t = log['created_at'].strftime('%Y-%m-%d %H:%M:%S') if hasattr(log['created_at'], 'strftime') else str(log['created_at'])
                    log_lines.append(f"{t} - {log['level']} - {log['message']}")
                st.text_area("数据库日志内容", '\n'.join(log_lines), height=300)
            else:
                st.info("暂无数据库日志")
            # 注：db_conn 走缓存，不在此关闭
    else:
        st.info("请先连接数据库以查看数据库日志")

    st.divider()

    st.subheader("向量调试测试")
    if st.button("运行向量相似度测试"):
        run_vector_debug_test()


def run_vector_debug_test():
    import numpy as np
    from sklearn.metrics.pairwise import cosine_similarity
    from model.embedding import AddressEmbedder
    import psycopg2
    import pgvector.psycopg2

    test_addr = "广州市浦东新区178弄23广场"
    results = []

    def add_result(title, status, details):
        results.append({"title": title, "status": status, "details": details})

    # 测试1：Python端向量化
    st.subheader("【测试1】Python端向量化")
    try:
        from model.embedding import AddressEmbedder
        from app_common import get_cached_embedder
        import torch
        test_device = st.session_state.get('selected_device', 'cpu')
        if test_device == 'cuda' and not torch.cuda.is_available():
            test_device = 'cpu'
        # 使用缓存的模型实例，避免每次调试都重新加载
        embedder = get_cached_embedder(test_device)

        vec1 = embedder.get_embedding(test_addr)
        vec2 = embedder.get_embedding(test_addr)

        similarity = cosine_similarity([vec1], [vec2])[0][0]

        st.write(f"测试地址: {test_addr}")
        st.write(f"向量维度: {vec1.shape}")
        st.write(f"向量1 L2范数: {np.linalg.norm(vec1):.8f}")
        st.write(f"向量2 L2范数: {np.linalg.norm(vec2):.8f}")
        st.write(f"Python端余弦相似度: {similarity:.8f}")
        device_label = "🖥️ GPU模式运行" if test_device == 'cuda' else "💻 CPU模式运行"
        st.caption(f"当前运行模式: {device_label}")

        if similarity > 0.99:
            st.success("✅ Python端向量化正确！")
            add_result("Python端向量化", "✅ 通过", f"相似度={similarity:.8f}")
        else:
            st.error("❌ Python端向量化有问题！")
            add_result("Python端向量化", "❌ 失败", f"相似度={similarity:.8f}")

    except Exception as e:
        st.error(f"测试失败: {str(e)}")
        add_result("Python端向量化", "❌ 失败", str(e))

    # 测试2：数据库表结构检查
    st.subheader("【测试2】数据库表结构检查")
    try:
        conn = psycopg2.connect(
            host=Config.DB_HOST,
            port=Config.DB_PORT,
            dbname=Config.DB_NAME,
            user=Config.DB_USER,
            password=Config.DB_PASSWORD
        )
        pgvector.psycopg2.register_vector(conn)
        cur = conn.cursor()

        st.write("--- 企业向量表结构 ---")
        cur.execute(f"""
            SELECT attname, format_type(atttypid, atttypmod)
            FROM pg_attribute
            WHERE attrelid = '{Config.ENTERPRISE_VECTOR_TABLE}'::regclass
            AND attnum > 0
        """)
        for row in cur.fetchall():
            st.write(f"  {row[0]}: {row[1]}")

        st.write("--- 标准地址向量表结构 ---")
        cur.execute(f"""
            SELECT attname, format_type(atttypid, atttypmod)
            FROM pg_attribute
            WHERE attrelid = '{Config.STANDARD_VECTOR_TABLE}'::regclass
            AND attnum > 0
        """)
        for row in cur.fetchall():
            st.write(f"  {row[0]}: {row[1]}")

        conn.close()
        st.success("✅ 表结构检查完成")
        add_result("数据库表结构", "✅ 通过", "表结构正确")

    except Exception as e:
        st.error(f"测试失败: {str(e)}")
        add_result("数据库表结构", "❌ 失败", str(e))

    # 测试3：数据库向量数据检查
    st.subheader("【测试3】数据库向量数据检查")
    try:
        conn = psycopg2.connect(
            host=Config.DB_HOST,
            port=Config.DB_PORT,
            dbname=Config.DB_NAME,
            user=Config.DB_USER,
            password=Config.DB_PASSWORD
        )
        pgvector.psycopg2.register_vector(conn)
        cur = conn.cursor()

        st.write("--- 企业向量表数据 ---")
        cur.execute(f"SELECT source_id, address, vector FROM {Config.ENTERPRISE_VECTOR_TABLE} LIMIT 2")
        rows = cur.fetchall()
        for row in rows:
            source_id, address, vec = row
            vec_array = np.array(vec)
            st.write(f"ID: {source_id}")
            st.write(f"地址: {address}")
            st.write(f"向量长度: {len(vec_array)}")
            st.write(f"向量范数: {np.linalg.norm(vec_array):.8f}")
            st.write("")

        st.write("--- 标准地址向量表数据 ---")
        cur.execute(f"SELECT source_id, address, vector FROM {Config.STANDARD_VECTOR_TABLE} LIMIT 2")
        rows = cur.fetchall()
        for row in rows:
            source_id, address, vec = row
            vec_array = np.array(vec)
            st.write(f"ID: {source_id}")
            st.write(f"地址: {address}")
            st.write(f"向量长度: {len(vec_array)}")
            st.write(f"向量范数: {np.linalg.norm(vec_array):.8f}")
            st.write("")

        st.write("--- 相同地址相似度测试 ---")
        cur.execute(f"""
            SELECT c1.source_id, c1.address, 1 - ((c1.vector <-> c2.vector)^2 / 2.0) as similarity
            FROM {Config.ENTERPRISE_VECTOR_TABLE} c1
            JOIN {Config.STANDARD_VECTOR_TABLE} c2 ON c1.address = c2.address
            LIMIT 2
        """)
        rows = cur.fetchall()
        for row in rows:
            source_id, address, similarity = row
            st.write(f"ID: {source_id}")
            st.write(f"地址: {address}")
            st.write(f"相似度: {similarity:.8f}")
            if similarity > 0.99:
                st.success("✅ 相似度正确")
                add_result("数据库相似度", "✅ 通过", f"相似度={similarity:.8f}")
            else:
                st.error("❌ 相似度有问题")
                add_result("数据库相似度", "❌ 失败", f"相似度={similarity:.8f}")
            st.write("")

        conn.close()

    except Exception as e:
        st.error(f"测试失败: {str(e)}")
        add_result("数据库向量数据", "❌ 失败", str(e))

    # 测试4：向量插入测试
    st.subheader("【测试4】向量插入测试")
    try:
        from model.embedding import AddressEmbedder
        from app_common import get_cached_embedder
        import torch
        test_device = st.session_state.get('selected_device', 'cpu')
        if test_device == 'cuda' and not torch.cuda.is_available():
            test_device = 'cpu'
        # 使用缓存的模型实例，避免每次调试都重新加载
        embedder = get_cached_embedder(test_device)
        test_addr_local = "测试地址123"
        vec = embedder.get_embedding(test_addr_local)

        st.write(f"原始向量范数: {np.linalg.norm(vec):.8f}")
        device_label = "🖥️ GPU模式运行" if test_device == 'cuda' else "💻 CPU模式运行"
        st.caption(f"当前运行模式: {device_label}")

        conn = psycopg2.connect(
            host=Config.DB_HOST,
            port=Config.DB_PORT,
            dbname=Config.DB_NAME,
            user=Config.DB_USER,
            password=Config.DB_PASSWORD
        )
        pgvector.psycopg2.register_vector(conn)
        cur = conn.cursor()

        cur.execute(f"DELETE FROM {Config.ENTERPRISE_VECTOR_TABLE} WHERE source_id = 'test_insert'")
        cur.execute(f"""
            INSERT INTO {Config.ENTERPRISE_VECTOR_TABLE} (source_id, enterprise_name, address, vector)
            VALUES (%s, %s, %s, %s)
        """, ('test_insert', '测试企业', test_addr_local, vec))
        conn.commit()

        cur.execute(f"SELECT vector FROM {Config.ENTERPRISE_VECTOR_TABLE} WHERE source_id = 'test_insert'")
        row = cur.fetchone()
        stored_vec = np.array(row[0])

        st.write(f"存储后向量范数: {np.linalg.norm(stored_vec):.8f}")
        sim = np.dot(vec, stored_vec) / (np.linalg.norm(vec) * np.linalg.norm(stored_vec))
        st.write(f"原始与存储向量相似度: {sim:.8f}")

        cur.execute(f"DELETE FROM {Config.ENTERPRISE_VECTOR_TABLE} WHERE source_id = 'test_insert'")
        conn.commit()
        conn.close()

        if sim > 0.99:
            st.success("✅ 向量插入测试完成")
            add_result("向量插入", "✅ 通过", f"存储相似度={sim:.8f}")
        else:
            st.error("❌ 向量插入有问题")
            add_result("向量插入", "❌ 失败", f"存储相似度={sim:.8f}")

    except Exception as e:
        st.error(f"测试失败: {str(e)}")
        import traceback
        st.write(f"详细错误: {traceback.format_exc()}")
        add_result("向量插入", "❌ 失败", str(e))

    # 测试总结
    st.subheader("测试总结")
    for res in results:
        status_color = "green" if res["status"] == "✅ 通过" else "red"
        st.write(f"<span style='color:{status_color}; font-weight:bold;'>{res['status']}</span> {res['title']}: {res['details']}", unsafe_allow_html=True)
