"""
数据导出工具模块
===============

提供数据导出功能，支持将匹配结果导出为 Excel 或 CSV 格式。

核心功能：
    1. 导出 DataFrame 到 Excel 文件
    2. 导出 DataFrame 到 CSV 文件
    3. 导出统计信息到 Excel 文件
"""

import pandas as pd

def export_to_excel(df, file_path):
    try:
        df.to_excel(file_path, index=False, engine='openpyxl')
        return True, f"Successfully exported to {file_path}"
    except Exception as e:
        return False, str(e)

def export_to_csv(df, file_path):
    try:
        df.to_csv(file_path, index=False, encoding='utf-8-sig')
        return True, f"Successfully exported to {file_path}"
    except Exception as e:
        return False, str(e)

def export_statistics(statistics, file_path):
    try:
        df = pd.DataFrame([statistics])
        df.to_excel(file_path, index=False, engine='openpyxl')
        return True, f"Successfully exported statistics to {file_path}"
    except Exception as e:
        return False, str(e)
