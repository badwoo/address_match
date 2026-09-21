# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# 中文地址语义匹配系统

本项目是基于 MGeo 模型 + PostgreSQL/pgvector 的中文地址语义匹配 Web 应用，使用 Streamlit 构建界面。核心任务是将企业地址与标准地址进行两阶段匹配：向量粗召回 → MGeo 精排。

## 常用命令

### 启动开发环境

项目依赖 `venv` 虚拟环境，Python 要求 3.10+：

```bash
# 激活虚拟环境（Windows）
venv\Scripts\activate

# 启动 Streamlit 应用
streamlit run app.py
```

启动后访问 http://localhost:8501。也可使用一键启动器：

```bash
python launcher.py
```

### 运行测试

项目使用 pytest，测试文件位于 `tests/`：

```bash
# 运行全部测试
pytest tests/

# 运行单个测试文件
pytest tests/test_vector_store_rename.py

# 运行单个测试用例
pytest tests/test_vector_store_rename.py::TestVectorStoreRename::test_rename
```

测试多围绕数据库 Schema/表名/向量表映射等回归问题，修改 `database/`、`matching/`、`model/` 后建议运行相关测试验证。

### 依赖与模型

依赖安装：

```bash
pip install -r requirements.txt
```

> 注意：`requirements.txt` 中 `torch` 指向本地 wheel 文件（`torch-2.11.0+cu130-cp312-cp312-win_amd64.whl`）。若该文件缺失或环境不匹配，需手动安装合适版本的 PyTorch。

模型加载优先级（无需改动代码即可离线部署）：

1. `models/iic/mgeo_backbone_chinese_base/`（粗召回/向量化）
2. `models/iic/mgeo_geographic_entity_alignment_chinese_base/`（精排）
3. `~/.cache/modelscope/hub/models/iic/...` 或 `MODELSCOPE_CACHE` 指定目录
4. HuggingFace 缓存目录
5. 在线下载（modelscope → transformers，需 `trust_remote_code=True`）

### 数据库准备

需要 PostgreSQL 14+ 并已安装 pgvector 扩展：

```sql
CREATE DATABASE postgres;
\c postgres
CREATE EXTENSION vector;
-- 如需非 public schema
CREATE SCHEMA ai;
```

数据库连接参数可通过项目根目录 `.env` 文件预填（参考 `.env.example`）：

```env
DB_HOST=localhost
DB_PORT=5432
DB_NAME=postgres
DB_USER=postgres
DB_PASSWORD=your_password_here
DB_SCHEMA=public
```

## 架构总览

```
Streamlit UI (app.py + pages/)
        │
        ▼
app_common.py（session_state 初始化、公共 UI 组件、编码检测、DB 连接缓存）
        │
        ├── config.py（全局配置、GPU 检测、模型路径发现）
        │
        ├── database/（PostgreSQL 操作层）
        │   ├── connection.py   DBConnection：连接管理、自动重连、search_path 设置
        │   ├── data_loader.py  DataLoader：表创建/读写/导出、召回与匹配结果持久化
        │   ├── vector_store.py VectorStore：pgvector 向量插入与相似度召回
        │   └── tag_manager.py  TagManager：标签及关联隔离表管理
        │
        ├── model/（模型加载与推理）
        │   ├── base_model_loader.py  统一本地/在线、modelscope/transformers 加载
        │   ├── embedding.py          AddressEmbedder：地址 → 768 维向量
        │   ├── mgeo_model.py         MGeoModel：精排分类（exact/partial/not_match）
        │   └── address_tagging_model.py 地址 NER 结构化解析
        │
        ├── matching/（匹配引擎）
        │   ├── matcher.py        AddressMatcher：两阶段匹配主流程 + 异步任务控制
        │   ├── ranking.py        RankingEngine：精排排序与匹配状态判定
        │   ├── mgeo_similarity.py 两地址直接相似度计算
        │   └── address_tagging.py 地址结构化解析业务封装
        │
        └── utils/（日志、导出、拼音、进度条）
```

## 关键设计

### 两阶段匹配流程

`AddressMatcher.run_two_stage_pipeline()` 实现核心流程：

1. **粗召回**：`VectorStore.batch_recall()` 使用 SQL JOIN LATERAL + pgvector 余弦相似度，为每个企业地址召回 Top-K 标准地址候选，按 `similarity_threshold` 在 SQL 层过滤。
2. **精排**：`RankingEngine.batch_rank_optimized()` 使用 MGeo 精排模型对所有候选做批量推理，输出 `exact_match` / `partial_match` / `not_match` 三概率；排序规则为 exact_match 降序、partial_match 降序、not_match 升序；匹配状态取三概率最大者。
3. 精排后再次按相似度阈值 Python 层过滤（双重过滤）。

### Schema 与标签隔离

- **Schema 隔离**：`DBConnection` 连接后自动执行 `SET search_path TO "schema", public`，所有未加 schema 前缀的表操作都在用户指定 Schema 下执行，同时保留 public 以使用 pgvector 等扩展。
- **标签隔离**：`TagManager` 为每个标签创建独立的 `{prefix}_recall_results` 和 `{prefix}_match_results` 表，prefix 由中文标签名自动转拼音生成。删除标签会级联删除关联表。

### 模型加载

`BaseModelLoader` 统一处理：

- 本地优先加载（`local_files_only=True`）
- modelscope 优先，失败回退到 transformers
- checkpoint 键名映射修复（`bert.text_encoder.*` → `bert.*`）
- 子类只需实现 `_get_model_classes()` 和 `_get_model_label()`，可选 `_get_extra_load_kwargs()`

### Session State 管理

`app_common.init_session_state()` 集中初始化所有页面共享状态，包括 GPU 信息、数据库配置、向量化/匹配配置、任务运行状态、标签状态、人工纠正状态等。新增页面状态时建议在此统一初始化。

### 数据库连接缓存

`app_common._get_cached_db_connection()` 使用 `@st.cache_resource(ttl=60)` 缓存 `DBConnection` 实例，避免 Streamlit 每次 rerun 重建 TCP 连接。

## 修改建议

- 调整默认阈值、表名、向量维度等全局参数优先改 `config.py`。
- 涉及表结构变更需同步更新 `database/data_loader.py` 中的建表逻辑，并考虑旧表迁移（参考 `DataLoader` 中 `correction_source` 字段迁移实现）。
- 修改匹配流程核心逻辑时，同步检查 `tests/` 中相关回归测试。
- 新增 Streamlit 页面需在 `app.py` 侧边栏菜单和路由中注册，并在 `app_common.py` 中初始化必要的 session state。
