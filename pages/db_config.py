"""
数据库配置页面
=============
配置PostgreSQL连接参数并测试连接。
"""

import streamlit as st
import pandas as pd
from database.connection import DBConnection
from utils.logger import logger, setup_db_logging
from app_common import _get_cached_db_connection


def show_db_config():
    """数据库配置页面：配置PostgreSQL连接参数并测试连接"""
    st.subheader("数据库配置")

    with st.form("db_config_form"):
        # 第一行：数据库主机 + 端口
        col1, col2 = st.columns(2)
        with col1:
            st.session_state.db_config['host'] = st.text_input("数据库主机", st.session_state.db_config['host'])
        with col2:
            st.session_state.db_config['port'] = st.number_input("端口", value=st.session_state.db_config['port'], min_value=1, max_value=65535)

        # 第二行：数据库名 + 模式
        col3, col4 = st.columns(2)
        with col3:
            st.session_state.db_config['dbname'] = st.text_input("数据库名", st.session_state.db_config['dbname'])
        with col4:
            st.session_state.db_config['schema'] = st.text_input("模式", st.session_state.db_config['schema'])

        # 第三行：用户名 + 密码
        col5, col6 = st.columns(2)
        with col5:
            st.session_state.db_config['user'] = st.text_input("用户名", st.session_state.db_config['user'])
        with col6:
            st.session_state.db_config['password'] = st.text_input("密码", st.session_state.db_config['password'], type='password')

        submitted = st.form_submit_button("测试连接")
        if submitted:
            # 测试连接用临时连接（不保持），验证参数是否正确
            test_conn = DBConnection(
                host=st.session_state.db_config['host'],
                port=st.session_state.db_config['port'],
                schema=st.session_state.db_config['schema'],
                dbname=st.session_state.db_config['dbname'],
                user=st.session_state.db_config['user'],
                password=st.session_state.db_config['password']
            )

            if test_conn.test_connection():
                st.success("数据库连接成功！")
                st.session_state.connected = True
                # 清除旧的缓存连接，确保下次获取的是新参数的连接
                st.cache_resource.clear()
                # 获取缓存连接用于日志记录
                cached_conn = _get_cached_db_connection(
                    host=st.session_state.db_config['host'],
                    port=st.session_state.db_config['port'],
                    schema=st.session_state.db_config['schema'],
                    dbname=st.session_state.db_config['dbname'],
                    user=st.session_state.db_config['user'],
                    password=st.session_state.db_config['password']
                )
                if cached_conn is not None:
                    setup_db_logging(cached_conn)
                logger.warning("Database connection established")
            else:
                st.error("数据库连接失败，请检查配置")

    # 连接成功后显示数据库表信息
    if st.session_state.get('connected'):
        st.success("数据库已连接")
        try:
            # 使用缓存连接显示表信息
            db_conn = _get_cached_db_connection(
                host=st.session_state.db_config['host'],
                port=st.session_state.db_config['port'],
                schema=st.session_state.db_config['schema'],
                dbname=st.session_state.db_config['dbname'],
                user=st.session_state.db_config['user'],
                password=st.session_state.db_config['password']
            )
            if db_conn is None:
                st.error("数据库连接已失效，请重新测试连接")
                return
            tables = db_conn.get_tables()
            st.write(f"数据库中共有 {len(tables)} 个数据表")

            selected_table = st.selectbox("查看表结构", tables)
            if selected_table:
                columns = db_conn.get_columns(selected_table)
                df = pd.DataFrame(columns, columns=["字段名", "数据类型"])
                st.dataframe(df)
        except Exception as e:
            st.error(f"获取表信息失败: {str(e)}")
