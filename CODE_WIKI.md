# 中文地址语义匹配系统 — Code Wiki

## 1. 项目概述

**项目名称**：中文地址语义匹配系统（address_match）

**项目目标**：实现 150 万企业表数据与 1300 万标准地址数据通过地址语义匹配，获取标准地址的房号信息。

**核心架构**：采用 **"粗召回 + 精排"** 两阶段匹配流程：
| 阶段 | 名称 | 技术 | 说明 |
| --- | --- | --- | --- |
| 阶段1 | 粗召回 | MGeo Backbone 向量化 + pgvector LATERAL JOIN | 将地址编码为 768 维向量，通过向量相似度检索每个企业 Top-N 候选标准地址 |
| 阶段2 | 精排 | MGeo Geographic Entity Alignment 模型 | 对召回的地址对进行两两比较，输出三分类概率，选出最优匹配 |

**技术栈**：

- **前端**：Streamlit（Python Web UI 框架）
- **数据库**：PostgreSQL + pgvector 扩展（向量存储与检索）
- **AI 模型**：阿里 MGeo 预训练模型（ModelScope / HuggingFace）
- **后端**：Python（业务逻辑、数据处理）

---

## 2. 项目目录结构

```
address_match/
├── app.py                  # Streamlit 主应用入口（UI 层）
├── config.py               # 全局配置（数据库、模型、阈值等）
├── ui_theme.py             # UI 设计令牌系统（颜色、间距、排版）
├── requirements.txt        # Python 依赖清单
├── database/               # 数据库层
│   ├── __init__.py         # 导出 DBConnection, VectorStore, DataLoader
│   ├── connection.py       # PostgreSQL 连接管理
│   ├── vector_store.py     # 向量存储与检索（pgvector）
│   ├── data_loader.py      # 数据批量加载与结果管理
│   └── tag_manager.py      # 标签管理（多任务隔离）
├── model/                  # 模型层
│   ├── __init__.py         # 导出 MGeoModel, AddressEmbedder
│   ├── embedding.py        # 地址向量化（粗召回阶段）
│   └── mgeo_model.py       # MGeo 精排模型（精排阶段）
├── matching/               # 匹配层
│   ├── __init__.py         # 导出 RankingEngine, AddressMatcher
│   ├── matcher.py          # 两阶段匹配流程编排
│   ├── ranking.py          # 精排引擎（候选排序与状态判断）
│   └── mgeo_similarity.py  # MGeo 地址相似度匹配（独立功能）
├── utils/                  # 工具层
│   ├── __init__.py
│   ├── logger.py           # 日志系统（内存缓存 + 数据库持久化）
│   ├── pinyin_utils.py     # 中文转拼音工具（标签命名）
│   ├── export.py           # 数据导出（Excel/CSV）
│   └── progress.py         # 进度跟踪器
├── tests/                  # 测试
│   ├── run_tests.py        # 测试运行入口
│   ├── test_*.py           # 各类测试用例
├── generate_eval_data.py   # 评估数据生成
├── generate_sz_eval_data.py # 深圳评估数据生成
└── generate_flowchart.py   # 流程图生成





```

---

## 3. 系统架构

### 3.1 整体架构图

```
┌─────────────────────────────────────────────────────────────┐
│                    Streamlit UI (app.py)                      │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────┐ ┌─────┐ │
│  │数据库配置 │ │向量预处理 │ │地址匹配   │ │结果管理 │ │日志  │ │
│  └──────────┘ └──────────┘ └──────────┘ └────────┘ └─────┘ │
└─────────────────────────┬───────────────────────────────────┘
                          │
┌─────────────────────────▼───────────────────────────────────┐
│                   匹配层 (matching/)                          │
│  ┌──────────────────────┐  ┌──────────────────────────────┐ │
│  │   AddressMatcher     │  │    MGeoSimilarityMatcher     │ │
│  │  (两阶段匹配编排)     │  │  (独立地址相似度匹配)         │ │
│  └──────────┬───────────┘  └──────────────────────────────┘ │
│             │                                                │
│  ┌──────────▼───────────┐                                   │
│  │   RankingEngine      │                                   │
│  │  (精排引擎)           │                                   │
│  └──────────┬───────────┘                                   │
└─────────────┼───────────────────────────────────────────────┘
              │
┌─────────────▼───────────────────────────────────────────────┐
│                    模型层 (model/)                             │
│  ┌──────────────────────┐  ┌──────────────────────────────┐ │
│  │  AddressEmbedder     │  │       MGeoModel              │ │
│  │  (粗召回向量化)       │  │  (精排三分类预测)             │ │
│  │  mgeo_backbone       │  │  mgeo_entity_alignment       │ │
│  │  768维向量输出        │  │  3标签概率输出                │ │
│  └──────────────────────┘  └──────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
              │
┌─────────────▼───────────────────────────────────────────────┐
│                  数据库层 (database/)                          │
│  ┌──────────┐ ┌──────────────┐ ┌────────────┐ ┌──────────┐ │
│  │DBConnection│ │ VectorStore  │ │ DataLoader │ │TagManager│ │
│  │(连接管理)  │ │(向量存储检索) │ │(数据加载)   │ │(标签管理) │ │
│  └──────────┘ └──────────────┘ └────────────┘ └──────────┘ │
└─────────────────────────┬───────────────────────────────────┘
                          │
              ┌───────────▼───────────┐
              │  PostgreSQL + pgvector │
              │  (向量数据库)           │
              └───────────────────────┘





```

### 3.2 两阶段匹配流程

```
企业表 ──→ AddressEmbedder.encode() ──→ 768维向量 ──→ enterprise_vectors 表
                                                                      │
标准地址表 ──→ AddressEmbedder.encode() ──→ 768维向量 ──→ standard_address_vectors 表
                                                                      │
                    ┌─────────── 阶段1：粗召回 ──────────┐              │
                    │ VectorStore.batch_recall()          │              │
                    │ SQL LATERAL JOIN + pgvector         │◄────────────┘
                    │ Top-N 候选 + 阈值过滤               │
                    └──────────────┬──────────────────────┘
                                   │ recall_results 表
                    ┌──────────────▼──────────────────────┐
                    │         阶段2：精排                   │
                    │ RankingEngine.batch_rank_optimized() │
                    │ MGeoModel.predict_optimized()        │
                    │ 三分类概率 + 最优候选选择              │
                    └──────────────┬──────────────────────┘
                                   │ match_results 表
                                   ▼
                            最终匹配结果





```

### 3.3 数据流

1. **向量化阶段**：原始表 → DataLoader 分页加载 → AddressEmbedder 编码 → VectorStore 写入向量表
2. **粗召回阶段**：enterprise_vectors × standard_address_vectors → SQL LATERAL JOIN → recall_results
3. **精排阶段**：recall_results → DataLoader 加载 → MGeoModel 批量预测 → RankingEngine 排序 → match_results

---

## 4. 模块详解

### 4.1 config.py — 全局配置

**职责**：集中管理系统的所有配置参数，包括数据库连接、模型路径、向量参数、匹配阈值等。

**关键类与函数**：
| 名称 | 类型 | 说明 |
| --- | --- | --- |
| `Config` | 类 | 全局配置类，所有参数为类属性 |
| `_detect_gpu_info()` | 函数 | 增强GPU检测，综合 torch.cuda、nvidia-smi、torch.backends 三种方式 |
| `_find_model_local_path(model_name)` | 函数 | 多路径模型搜索：项目目录 → ModelScope缓存 → HuggingFace缓存 |

**核心配置项**：
| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `DB_HOST / DB_PORT / DB_NAME` | localhost:5432/postgres | PostgreSQL 连接参数 |
| `DB_SCHEMA` | public | 数据库模式，支持多Schema隔离 |
| `EMBEDDING_MODEL_NAME` | iic/mgeo_backbone_chinese_base | 粗召回向量化模型 |
| `MODEL_NAME` | iic/mgeo_geographic_entity_alignment_chinese_base | 精排匹配模型 |
| `DEVICE` | 自动检测 | 运行设备（cuda/cpu） |
| `VECTOR_DIM` | 768 | 向量维度 |
| `SIMILARITY_THRESHOLD` | 0.8 | 相似度阈值（粗召回+精排双重过滤） |
| `RECALL_TOP_N` | 50 | 每个企业粗召回候选数量 |
| `BATCH_SIZE_DB` | 1000 | 数据库批量加载大小 |
| `BATCH_SIZE_EMBEDDING` | 32 | 向量化批处理大小 |
| `BATCH_SIZE_MODEL` | 128 | 精排模型批处理大小 |

**模型加载策略**（多路径回退）：

```
1. 项目目录 models/iic/...          ← 最高优先级
2. ModelScope 缓存 ~/.cache/modelscope/hub/models/
3. HuggingFace 缓存 ~/.cache/huggingface/hub/
4. 在线下载（modelscope → transformers） ← 最终回退





```

---

### 4.2 database/ — 数据库层

#### 4.2.1 connection.py — 数据库连接管理

**职责**：管理 PostgreSQL 数据库连接，支持 pgvector 扩展和多 Schema 操作。

**关键类**：
| 类名 | 说明 |
| --- | --- |
| `DBConnection` | PostgreSQL 连接管理器 |

**关键方法**：
| 方法 | 说明 |
| --- | --- |
| `connect()` | 建立连接，自动注册 pgvector、设置 search_path |
| `execute(sql, params)` | 执行SQL，支持自动重连 |
| `get_tables()` | 获取当前Schema下所有表名 |
| `get_columns(table_name)` | 获取表字段信息 |
| `table_exists(table_name)` | 检查表是否存在 |
| `drop_table(table_name)` | 删除表 |

**关键函数**：
| 函数 | 说明 |
| --- | --- |
| `quote_identifier(name)` | 对SQL标识符加双引号，支持中文表名和字段名 |

**技术要点**：

- 连接后自动执行 `SET search_path TO "{schema}", public`，保留 public 以访问 pgvector 扩展
- 使用 `RealDictCursor` 返回字典形式查询结果
- 支持自动重连机制（`_check_connection` + `connect` 回退）

#### 4.2.2 vector_store.py — 向量存储与检索

**职责**：向量数据的存储、索引和检索操作，基于 pgvector 实现。

**关键类**：
| 类名 | 说明 |
| --- | --- |
| `VectorStore` | 向量存储管理器 |

**关键方法**：
| 方法 | 说明 |
| --- | --- |
| `create_vector_table(table_name, table_type)` | 创建向量表（企业/标准两种类型） |
| `create_vector_index(table_name, index_type)` | 创建向量索引（ivfflat/hnsw） |
| `insert_vectors(vectors, source_ids, ...)` | 批量插入向量（高性能版，事务批量提交） |
| `batch_recall(enterprise_table, standard_table, top_n, threshold)` | **核心方法**：批量粗召回，SQL LATERAL JOIN |
| `search_vectors(query_vector, top_n)` | 单向量相似性搜索 |
| `disable_autovacuum / enable_autovacuum` | 批量导入时禁用/启用 autovacuum |
| `vacuum_table(table_name)` | VACUUM ANALYZE 回收空间 |

**粗召回 SQL 核心逻辑**（`batch_recall`）：

```sql
SELECT c.source_id, a.source_id, 1 - (c.vector <=> a.vector) AS similarity
FROM enterprise_vectors c
JOIN LATERAL (
    SELECT source_id, address, room_no, vector
    FROM standard_address_vectors
    ORDER BY c.vector <=> vector
    LIMIT {top_n}
) a ON true
WHERE 1 - (c.vector <=> a.vector) >= {threshold}
ORDER BY c.source_id, similarity DESC





```

**性能优化**：

- `_vector_to_pg_string()`：使用 numpy vectorized 操作构建向量字符串，比逐元素快 10-20x
- 批量插入时临时关闭 autocommit，每 10 chunk 提交一次事务
- 支持禁用 autovacuum 防止批量 INSERT 争抢 I/O

#### 4.2.3 data_loader.py — 数据加载与结果管理

**职责**：数据的批量加载、匹配结果的存储和统计查询。

**关键类**：
| 类名 | 说明 |
| --- | --- |
| `DataLoader` | 数据加载器 |

**关键方法**：
| 方法 | 说明 |
| --- | --- |
| `load_enterprise_data(table, ...)` | 游标分页加载企业数据（避免深度分页性能问题） |
| `load_standard_addresses(table, ...)` | 游标分页加载标准地址数据 |
| `create_recall_table / create_result_table` | 创建召回/匹配结果表 |
| `insert_recall_results / insert_match_results` | 批量插入结果 |
| `load_recall_results(table)` | 加载召回结果供精排使用 |
| `get_match_results_paginated(...)` | 分页获取匹配结果（支持筛选） |
| `get_match_statistics(table)` | 获取匹配统计（含人工纠正统计） |
| `update_match_result_with_correction(...)` | 人工纠正匹配结果 |
| `create_mgeo_copy_table(...)` | 创建带匹配字段的原始表副本 |
| `export_match_results_batch(...)` | 批量导出匹配结果（避免内存溢出） |

**数据库表结构**：

**recall_results（粗召回结果表）**：
| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | SERIAL PK | 主键 |
| enterprise_id | VARCHAR(255) | 企业标识 |
| enterprise_name | TEXT | 企业名称 |
| enterprise_address | TEXT | 企业地址 |
| standard_id | VARCHAR(255) | 标准地址编码 |
| standard_address | TEXT | 标准地址 |
| room_no | VARCHAR(100) | 房屋编码 |
| similarity | DOUBLE PRECISION | 相似度分数 |

**match_results（匹配结果表）**：
| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | SERIAL PK | 主键 |
| enterprise_id | VARCHAR(255) | 企业标识 |
| enterprise_name | TEXT | 企业名称 |
| enterprise_address | TEXT | 企业地址 |
| address_id | VARCHAR(255) | 匹配到的标准地址编码 |
| standard_address | TEXT | 匹配到的标准地址 |
| room_no | VARCHAR(100) | 房屋编码 |
| exact_match | DOUBLE PRECISION | 精确匹配概率 |
| partial_match | DOUBLE PRECISION | 部分匹配概率 |
| not_match | DOUBLE PRECISION | 不匹配概率 |
| match_status | VARCHAR(20) | 匹配状态（精确匹配/部分匹配/不匹配） |
| correction_source | VARCHAR(20) | 纠正来源（自动匹配/人工纠正） |

**技术要点**：

- 游标分页（`id > last_id`）替代 OFFSET 分页，避免深度分页性能问题
- 自动迁移 FLOAT → DOUBLE PRECISION（`_migrate_float_to_double`）
- 自动添加 `correction_source` 字段兼容旧表（`_add_correction_source_column`）

#### 4.2.4 tag_manager.py — 标签管理

**职责**：管理匹配标签的持久化存储，实现多任务数据隔离。

**关键类**：
| 类名 | 说明 |
| --- | --- |
| `TagManager` | 标签管理器 |

**关键方法**：
| 方法 | 说明 |
| --- | --- |
| `create_tag(tag_name)` | 创建标签，同时创建关联的 recall/match 数据表 |
| `get_all_tags()` | 获取所有标签 |
| `delete_tag(prefix)` | 删除标签及其关联数据表 |

**标签机制**：每个标签对应一对数据表（`{prefix}_recall_results`、`{prefix}_match_results`），实现不同批次/区域的匹配数据隔离。

---

### 4.3 model/ — 模型层

#### 4.3.1 embedding.py — 地址向量化（粗召回阶段）

**职责**：使用 MGeo Backbone 模型将地址文本转换为 768 维向量。

**关键类**：
| 类名 | 说明 |
| --- | --- |
| `AddressEmbedder` | 地址向量化器 |

**关键方法**：
| 方法 | 说明 |
| --- | --- |
| `encode(texts, batch_size, max_len)` | 批量向量化，返回 (n, 768) numpy数组 |
| `get_embedding(address)` | 获取单个地址向量 |
| `get_vector_dim()` | 获取向量维度 |

**向量化流程**：

1. Tokenizer 编码文本（truncation=True, max_length=64）
2. 取 `last_hidden_state[:, 0, :]`（[CLS] token）
3. L2 归一化（`torch.nn.functional.normalize`，pgvector 余弦距离依赖归一化向量）

**模型加载策略**：

```
本地 modelscope → 本地 transformers → 在线 modelscope → 在线 transformers





```

#### 4.3.2 mgeo_model.py — MGeo 精排模型（精排阶段）

**职责**：使用 MGeo 实体对齐模型进行地址匹配精排，输出三分类概率。

**关键类**：
| 类名 | 说明 |
| --- | --- |
| `MGeoModel` | MGeo 地址相似度匹配模型 |

**关键方法**：
| 方法 | 说明 |
| --- | --- |
| `predict(address_pairs, batch_size)` | 批量预测，返回完整结果（含地址对和标签） |
| `predict_optimized(address_pairs, batch_size)` | **高性能版**：精简结果，仅保留概率值 |
| `get_similarity(address1, address2)` | 获取两个地址的匹配概率 |
| `batch_predict(addresses1, addresses2)` | 批量预测两组地址 |

**模型输出标签映射**：
| 索引 | 标签名 | 说明 |
| --- | --- | --- |
| 0 | not_match | 不匹配概率 |
| 1 | partial_match | 部分匹配概率 |
| 2 | exact_match | 精确匹配概率 |

**重要约束**：模型加载时必须 `num_labels=3`，否则 AutoModelForSequenceClassification 默认 2 标签会导致 logits 维度不匹配。

**性能优化**：

- GPU 上自动启用 FP16 半精度推理（`model.half()`），速度提升约 2x
- 使用 `torch.inference_mode()` 替代 `torch.no_grad()`
- `predict_optimized()`：预分配结果列表、批量 numpy 切片、精简结果字典

**Checkpoint 键名映射**：ModelScope 原始 checkpoint 中 BERT 编码器键名使用 `bert.text_encoder.*` 前缀，需映射为 `bert.*` 以兼容 HuggingFace 加载（`_fix_checkpoint_key_mapping`）。

---

### 4.4 matching/ — 匹配层

#### 4.4.1 matcher.py — 两阶段匹配流程编排

**职责**：编排完整的两阶段匹配流程，支持同步/异步执行、任务控制。

**关键类**：
| 类名 | 说明 |
| --- | --- |
| `AddressMatcher` | 地址匹配器（核心编排类） |

**关键方法**：
| 方法 | 说明 |
| --- | --- |
| `run_full_pipeline(...)` | 运行完整匹配流程（粗召回+精排） |
| `run_two_stage_pipeline(...)` | 两阶段匹配核心方法 |
| `build_enterprise_vectors(...)` | 构建企业向量 |
| `build_standard_vectors(...)` | 构建标准地址向量 |
| `start_async(...)` | 异步启动完整匹配 |
| `start_recall_async(...)` | 异步启动粗召回（分步模式） |
| `start_ranking_async(...)` | 异步启动精排（分步模式） |
| `pause() / resume() / stop()` | 任务控制 |

**两阶段流程**：

1. **粗召回**（占进度 40%）：`VectorStore.batch_recall()` → `DataLoader.insert_recall_results()`
2. **精排**（占进度 60%）：`RankingEngine.batch_rank_optimized()` → `DataLoader.insert_match_results()`

**分步执行模式**：支持先执行粗召回，再执行精排，中间可查看召回结果。

#### 4.4.2 ranking.py — 精排引擎

**职责**：使用 MGeo 模型对召回候选进行精准排序，选出最优匹配。

**关键类与函数**：
| 名称 | 类型 | 说明 |
| --- | --- | --- |
| `RankingEngine` | 类 | 精排引擎 |
| `determine_match_status(exact, partial, not)` | 函数 | 根据三分类概率判断匹配状态 |

**候选排序逻辑**：

1. 先按相似度阈值过滤低分候选
2. 主排序：`exact_match` 降序（越高越好）
3. 次排序：`not_match` 升序（越低越好）

**匹配状态判断**（`determine_match_status`）：

- `exact_match` 最大 → **精确匹配**
- `partial_match` 最大 → **部分匹配**
- `not_match` 最大 → **不匹配**
- 无候选 → **不匹配**

**关键方法**：
| 方法 | 说明 |
| --- | --- |
| `rank(query_address, candidates)` | 单条地址精排 |
| `batch_rank(query_addresses, candidates_list)` | 批量精排 |
| `batch_rank_optimized(recall_results, ...)` | **优化版批量精排**：分块处理避免 OOM |

**`batch_rank_optimized`**** 分块策略**：

- 每次处理 `chunk_size`（默认 5000）个企业
- 收集该块内所有地址对，一次性送入模型预测
- 预测完成后立即释放内存，再处理下一块
- 避免一次性加载所有地址对（150万企业 × 50候选 = 7500万对）导致 OOM

#### 4.4.3 mgeo_similarity.py — MGeo 地址相似度匹配（独立功能）

**职责**：独立于粗召回+精排流程的地址相似度匹配功能，直接对地址对进行匹配。

**关键类与函数**：
| 名称 | 类型 | 说明 |
| --- | --- | --- |
| `MGeoSimilarityMatcher` | 类 | MGeo 地址相似度匹配器 |
| `determine_similarity_status(exact, partial, not)` | 函数 | 匹配状态判断 |
| `run_mgeo_similarity_async(...)` | 函数 | 异步执行匹配任务 |

**关键方法**：
| 方法 | 说明 |
| --- | --- |
| `match_from_dataframe(df, col_a, col_b)` | 从 DataFrame 匹配 |
| `match_from_file(file_path, col_a, col_b)` | 从文件匹配（Excel/CSV） |
| `match_from_db_table(db_conn, table, col_a, col_b)` | 从数据库表匹配 |

**与两阶段匹配的区别**：此模块不依赖向量召回，直接对用户提供的地址对进行匹配，适用于已有地址对需要判断是否匹配的场景。

---

### 4.5 utils/ — 工具层

#### 4.5.1 logger.py — 日志系统

**职责**：提供统一的日志记录，支持内存缓存和数据库双重输出。

**关键组件**：
| 名称 | 类型 | 说明 |
| --- | --- | --- |
| `logger` | Logger | 全局日志器（`address_matcher`） |
| `StreamHandler` | 类 | 内存缓存日志处理器，最多 10000 条，供 UI 展示 |
| `DBLogHandler` | 类 | 数据库日志处理器，WARNING 及以上写入 `app_log` 表 |
| `setup_db_logging(db_conn)` | 函数 | 初始化数据库日志 |
| `get_log_messages()` | 函数 | 获取内存日志列表 |
| `get_db_logs(db_conn)` | 函数 | 从数据库获取日志 |

**日志级别**：默认 `WARNING`，精简日志输出。

#### 4.5.2 pinyin_utils.py — 中文转拼音工具

**职责**：将中文标签转为拼音前缀，用于生成数据库表名。

**关键函数**：
| 函数 | 说明 |
| --- | --- |
| `tag_to_prefix(tag)` | 中文→拼音，英文→小写清理 |
| `get_tag_tables(prefix)` | 生成 `{prefix}_recall_results` 和 `{prefix}_match_results` 表名 |
| `get_existing_tags(db_conn)` | 从数据库检索已有标签前缀 |

**拼音映射**：内置常用汉字拼音映射表（覆盖地名、行政区划、企业类型等常见用字），未收录汉字使用 Unicode 码点作为后备。

#### 4.5.3 export.py — 数据导出

**关键函数**：
| 函数 | 说明 |
| --- | --- |
| `export_to_excel(df, file_path)` | 导出 DataFrame 到 Excel |
| `export_to_csv(df, file_path)` | 导出 DataFrame 到 CSV（UTF-8 BOM） |
| `export_statistics(statistics, file_path)` | 导出统计信息到 Excel |

#### 4.5.4 progress.py — 进度跟踪

**关键类**：
| 类名 | 说明 |
| --- | --- |
| `ProgressTracker` | 进度跟踪器，支持回调函数管理 |

---

### 4.6 app.py — Streamlit 主应用

**职责**：提供 Web UI 界面，是系统的用户交互入口。

**页面结构**：
| 页面 | 函数 | 说明 |
| --- | --- | --- |
| 数据库配置 | `show_db_config()` | 配置 PostgreSQL 连接参数 |
| 向量预处理 | `show_vector_preprocess()` | 配置字段映射，执行向量化 |
| 地址匹配 | `show_address_matching()` | 执行两阶段匹配（粗召回+精排） |
| 结果管理 | `show_result_management()` | 查看匹配结果、统计、人工纠正、导出 |
| 系统日志 | `show_system_logs()` | 查看内存日志和数据库日志 |

**关键辅助函数**：
| 函数 | 说明 |
| --- | --- |
| `init_session_state()` | 初始化 Streamlit 会话状态 |
| `format_time(seconds)` | 格式化时间显示 |
| `detect_csv_encoding(file_bytes)` | 自动检测 CSV 编码 |
| `_render_device_selector(key)` | 渲染 GPU/CPU 设备选择器 |
| `_goto_page / _prev_page / _next_page` | 翻页回调函数 |

**会话状态管理**：使用 `st.session_state` 管理全局状态，包括数据库配置、向量化配置、匹配任务状态、标签状态、人工纠正状态等。

---

### 4.7 ui_theme.py — UI 设计令牌系统

**职责**：为系统提供统一的设计令牌，包括颜色、间距、排版和组件样式。

**关键类**：
| 类名 | 说明 |
| --- | --- |
| `Colors` | 语义化颜色令牌（主色调、状态色、中性色、分区色） |
| `Spacing` | 8px 基准间距系统 |
| `Typography` | 排版令牌（字体、字号、字重） |
| `Radius` | 圆角令牌 |
| `Shadow` | 阴影令牌 |
| `Icons` | 语义标签（Unicode 实体替代 emoji） |

**关键函数**：
| 函数 | 说明 |
| --- | --- |
| `card_style(bg_color, border_color)` | 生成卡片容器 CSS |
| `status_container_style(status_type)` | 生成语义状态容器样式 |
| `inject_global_styles()` | 注入全局 Streamlit 自定义样式 |

---

## 5. 依赖关系

### 5.1 模块间依赖关系图

```
app.py
 ├── config.py
 ├── database/
 │   ├── connection.py ←── config.py, logger.py
 │   ├── vector_store.py ←── config.py, connection.py, logger.py
 │   ├── data_loader.py ←── config.py, connection.py, logger.py
 │   └── tag_manager.py ←── pinyin_utils.py, data_loader.py
 ├── model/
 │   ├── embedding.py ←── config.py, logger.py
 │   └── mgeo_model.py ←── config.py, logger.py
 ├── matching/
 │   ├── matcher.py ←── config.py, data_loader, vector_store, embedding, ranking, logger.py
 │   ├── ranking.py ←── config.py, mgeo_model, logger.py
 │   └── mgeo_similarity.py ←── config.py, mgeo_model, logger.py
 ├── utils/
 │   ├── logger.py
 │   ├── pinyin_utils.py
 │   ├── export.py
 │   └── progress.py
 └── ui_theme.py





```

### 5.2 外部依赖
| 依赖 | 版本 | 用途 |
| --- | --- | --- |
| streamlit | 1.38.0 | Web UI 框架 |
| psycopg2-binary | 2.9.11 | PostgreSQL 驱动 |
| pgvector | 0.4.2 | 向量数据库扩展 |
| modelscope | 1.35.4 | ModelScope 模型库（优先加载） |
| transformers | 5.5.3 | HuggingFace 模型库（回退加载） |
| sentence-transformers | 5.4.0 | 句向量模型 |
| torch | — | PyTorch 深度学习框架 |
| numpy | 2.4.4 | 数值计算 |
| pandas | 2.3.3 | 数据处理 |
| scikit-learn | 1.8.0 | 机器学习工具 |
| openpyxl | 3.1.5 | Excel 文件读写 |
| tqdm | 4.67.3 | 进度条 |

---

## 6. 项目运行方式

### 6.1 环境准备

```bash
# 1. 安装 Python 依赖
pip install -r requirements.txt

# 2. 确保 PostgreSQL 已安装并启动
# 3. 确保 pgvector 扩展已安装
#    CREATE EXTENSION IF NOT EXISTS vector;





```

### 6.2 模型准备

系统启动时会自动搜索本地模型或在线下载。推荐提前下载模型到项目目录：

```
address_match/
└── models/
    └── iic/
        ├── mgeo_backbone_chinese_base/          # 粗召回模型
        └── mgeo_geographic_entity_alignment_chinese_base/  # 精排模型





```

### 6.3 启动应用

```bash
# 启动 Streamlit 应用
streamlit run app.py





```

### 6.4 使用流程

1. **数据库配置**：配置 PostgreSQL 连接参数，测试连接
2. 选择企业表，配置标识/名称/地址字段映射
3. 选择标准地址表，配置编码/地址/房号字段映射
4. 执行向量化（企业表和标准地址表分别向量化）
5. 创建向量索引（ivfflat 或 hnsw）
6. 创建向量索引（ivfflat 或 hnsw）
7. 选择企业向量表和标准地址向量表
8. 配置相似度阈值和召回数量
9. 执行粗召回 → 查看召回结果 → 执行精排
10. 执行粗召回 → 查看召回结果 → 执行精排
11. 查看匹配结果和统计信息
12. 人工纠正错误匹配
13. 导出结果（Excel/CSV）
14. 导出结果（Excel/CSV）

### 6.5 运行测试

```bash
# 运行全部测试
python tests/run_tests.py

# 运行单个测试
python tests/test_recall_filter.py
python tests/test_vector_index.py





```

---

## 7. 关键设计决策

### 7.1 相似度阈值双重过滤

`Config.SIMILARITY_THRESHOLD`（默认 0.8）在两个阶段均生效：

- **粗召回阶段**：SQL `WHERE similarity >= threshold` 在数据库层面过滤
- **精排阶段**：Python 代码中再次过滤，防止粗召回阶段漏过滤的候选进入精排

### 7.2 人工纠正机制

- `match_results` 表有 `correction_source` 字段（默认 `'自动匹配'`）
- 人工纠正后更新为 `'人工纠正'`，同时设置 `match_status='精确匹配'`、`exact_match=1.0`
- 系统启动时自动检测旧表并迁移添加该字段

### 7.3 多 Schema 支持

- 连接后自动执行 `SET search_path TO "{schema}", public`
- 保留 `public` 模式以访问 pgvector 扩展
- `quote_identifier()` 对 SQL 标识符加双引号，支持中文表名和字段名

### 7.4 标签隔离机制

- 每个标签对应独立的 recall/match 数据表（`{prefix}_recall_results`、`{prefix}_match_results`）
- 标签名自动转拼音作为表名前缀
- 支持不同批次/区域的匹配数据隔离

### 7.5 GPU 检测与回退

- 综合三种方式检测 GPU：`torch.cuda.is_available()`、`nvidia-smi`、`torch.backends.cuda.is_built()`
- 检测到 NVIDIA 显卡但 PyTorch 为 CPU 版本时给出明确警告
- GPU 上自动启用 FP16 半精度推理

### 7.6 翻页回调机制

结果管理页面分页使用 Streamlit 的 `on_click` 回调函数（`_goto_page`、`_prev_page`、`_next_page`），解决 `st.session_state` 绑定 widget 后无法直接修改的问题。

---

## 8. 数据库表总览
| 表名 | 说明 | 创建位置 |
| --- | --- | --- |
| `enterprise_vectors` | 企业地址向量表 | VectorStore |
| `standard_address_vectors` | 标准地址向量表 | VectorStore |
| `recall_results` | 粗召回结果表 | DataLoader |
| `match_results` | 匹配结果表 | DataLoader |
| `mgeo_similarity_results` | MGeo 相似度匹配结果表 | DataLoader |
| `{prefix}_recall_results` | 标签特定的召回结果表 | TagManager + DataLoader |
| `{prefix}_match_results` | 标签特定的匹配结果表 | TagManager + DataLoader |
| `{source_table}_mgeo` | 原始表的 MGeo 匹配副本 | DataLoader |
| `match_tags` | 标签配置表 | TagManager |
| `app_log` | 应用日志表 | DBLogHandler |

---

## 9. 测试用例说明
| 测试文件 | 测试内容 |
| --- | --- |
| `test_recall_filter.py` | 粗召回阈值过滤逻辑 |
| `test_vector_index.py` | 向量索引创建与检索 |
| `test_vector_index_fix.py` | 向量索引修复 |
| `test_threshold_fix.py` | 阈值修复 |
| `test_performance_fix.py` | 性能优化修复 |
| `test_schema_and_table_fix.py` | Schema 和表名修复 |
| `test_gpu_detection.py` | GPU 检测逻辑 |
| `test_manual_correction.py` | 人工纠正功能 |
| `test_model_loading_fix.py` | 模型加载修复 |
