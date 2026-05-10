# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

中文地址语义匹配系统。将企业地址与标准地址库进行匹配，获取房号信息。采用"粗召回 + 精排"两阶段架构，基于阿里 MGeo 模型。

## 常用命令

```bash
# 启动 Streamlit 应用
streamlit run app.py

# 运行测试（使用 Python 内置 assert，无 pytest 配置）
python tests/run_tests.py
python tests/test_recall_filter.py
python tests/test_vector_index.py

# 安装依赖
pip install -r requirements.txt
```

## 架构总览

### 两阶段匹配流程

**阶段1 - 粗召回（Coarse Recall）**：`model/embedding.py` 使用 `iic/mgeo_backbone_chinese_base` 将地址编码为 768 维向量，`database/vector_store.py` 通过 pgvector 的 LATERAL JOIN 检索每个企业最相似的标准地址候选（Top-N），SQL WHERE 条件按 `SIMILARITY_THRESHOLD` 过滤低相似度候选。

**阶段2 - 精排（Fine Ranking）**：`model/mgeo_model.py` 使用 `iic/mgeo_geographic_entity_alignment_chinese_base` 对召回的地址对进行两两比较，`matching/ranking.py` 中的 `RankingEngine` 输出三个概率值，再由 `determine_match_status()` 取最大值决定匹配状态。

精排候选排序逻辑：
1. 主排序：`exact_match` 降序（越高越好）
2. 次排序：`not_match` 升序（越低越好）

模型输出标签映射：
- index 0 → `exact_match`（精确匹配概率）
- index 1 → `not_match`（不匹配概率）
- index 2 → `partial_match`（部分匹配概率）

**重要**：模型加载时必须指定 `num_labels=3`（见 `model/mgeo_model.py`），否则 AutoModelForSequenceClassification 默认 2 标签会导致 logits 维度不匹配。

### 模型加载策略（多路径回退）

`config.py` 中的 `_find_model_local_path()` 按以下优先级搜索模型：
1. 项目目录 `models/iic/...`
2. ModelScope 缓存目录（含 `MODELSCOPE_CACHE` 环境变量）
3. HuggingFace 缓存目录（含 `HF_HOME` 环境变量）
4. 在线下载（modelscope → transformers）

加载库优先级：modelscope（原生支持）→ transformers（需 `trust_remote_code=True`）。checkpoint 中 BERT 编码器键名需要从 `bert.text_encoder.*` 映射为 `bert.*` 以兼容 HuggingFace 加载。

### 多 Schema 支持

`database/connection.py` 中的 `DBConnection` 连接后自动执行 `SET search_path TO "{schema}", public`，同时保留 `public` 模式以访问 pgvector 扩展。`quote_identifier()` 对 SQL 标识符加双引号，支持中文表名和字段名。

### 相似度阈值双重过滤

`Config.SIMILARITY_THRESHOLD`（默认 0.8）在两个阶段均生效：
- **粗召回阶段**：SQL `WHERE similarity >= threshold` 在数据库层面过滤
- **精排阶段**：Python 代码中再次过滤，防止粗召回阶段漏过滤的候选进入精排

### 人工纠正机制

`match_results` 表有 `correction_source` 字段（默认 `'自动匹配'`），人工纠正后更新为 `'人工纠正'`，同时设置 `match_status='精确匹配'`、`exact_match=1.0`。系统启动时自动检测旧表并迁移添加该字段。`DataLoader` 的方法支持 `table_name` 参数覆盖默认表名。

### 翻页回调机制

结果管理页面分页使用 Streamlit 的 `on_click` 回调函数（`_goto_page`、`_prev_page`、`_next_page`），解决 `st.session_state` 绑定 widget 后无法直接修改的问题。

## 开发规范（来自 .trae/rules）

1. **Bug 修复必须编写测试用例**，确保测试通过才算解决。
2. **Bug 修复要全面考虑**，不要引入其他 Bug。
3. **项目思考推理请用中文**。
4. **增加新功能前**，先理解整个项目代码和架构设计后再实现。
