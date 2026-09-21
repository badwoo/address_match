# 中文地址语义匹配系统（address_match）

基于 **MGeo 预训练模型 + PostgreSQL/pgvector** 的中文地址语义匹配平台，Streamlit 构建可视化界面。

**核心目标**：将 150 万企业地址与 1300 万标准地址做语义匹配，为每个企业地址匹配到标准地址并获取其**房号**信息。

---

## 核心能力

| 功能模块 | 说明 |
| --- | --- |
| 数据库配置 | 连接 PostgreSQL，配置主机/库名/Schema，测试连通性 |
| 地址结构化解析 | 地址 NER 解析，支持 12 级 / 17 级结构化字段抽取 |
| 向量预处理 | 批量地址向量化（768 维），建立 pgvector 向量索引 |
| 地址匹配 | **两阶段匹配**：向量粗召回 → MGeo 精排，支持流式处理大表 |
| 地址相似度匹配 | 独立功能，对地址 A/B 逐行直接计算 MGeo 相似度 |
| 结果管理 | 匹配结果浏览、筛选、导出（Excel/CSV）与人工纠正 |
| 房号提取 | 纯 SQL 存储过程实现，PG 内直接批量回写房号字段 |
| 系统日志 | 运行日志查看与向量检索调试 |

---

## 匹配原理

### 两阶段流程

```
企业地址 ──┐
           ├─→ AddressEmbedder ──→ 768 维向量 ──→ enterprise_vectors
标准地址 ──┘                                    standard_address_vectors
                                                         │
        ┌────────── 阶段 1：粗召回 ──────────┐            │
        │ VectorStore.batch_recall()        │◀───────────┘
        │ pgvector 余弦相似度 + JOIN LATERAL │
        │ 每个企业地址召回 Top-K 候选        │
        └───────────────┬───────────────────┘
                        ▼
        ┌────────── 阶段 2：精排 ────────────┐
        │ RankingEngine.batch_rank_optimized │
        │ MGeo 精排模型 → exact / partial /   │
        │ not_match 三分类概率                │
        └───────────────┬───────────────────┘
                        ▼
              匹配结果（含房号）+ 人工纠正
```

**精排排序规则**：`exact_match` 降序 → `partial_match` 降序 → `not_match` 升序；匹配状态取三者概率最大值对应的类别。

**双重阈值过滤**：粗召回在 SQL 层按相似度阈值过滤，精排后再次在 Python 层过滤。

**大表支持**：企业数 ≥ 10 万时自动切换流式管线（分批处理，控制内存占用）。

---

## 技术栈

- **界面**：Streamlit 1.38
- **数据库**：PostgreSQL 14+ / pgvector 0.4
- **模型**：阿里 MGeo（ModelScope）
  - 粗召回：`iic/mgeo_backbone_chinese_base`（768 维向量）
  - 精排：`iic/mgeo_geographic_entity_alignment_chinese_base`（三分类）
  - 地址解析：`iic/mgeo_geographic_ner_chinese_base`
- **推理框架**：PyTorch（支持 CUDA，自动检测 GPU 并回退 CPU）
- **其他**：pandas、psycopg2、openpyxl、pypinyin

---

## 目录结构

```
address_match/
├── app.py                       # Streamlit 主入口与侧边栏路由
├── app_common.py                # session_state 初始化、公共 UI 组件、DB 连接缓存
├── config.py                    # 全局配置（DB / 模型 / 阈值 / 批大小）
├── ui_theme.py                  # UI 设计令牌（颜色 / 排版 / 间距）
├── launcher.py                  # 一键启动器（进程管理）
├── 地址匹配系统启动.bat           # Windows 双击启动脚本
├── pages/                       # 各功能页面
│   ├── db_config.py             # 数据库配置
│   ├── address_tagging.py       # 地址结构化解析
│   ├── vector_preprocess.py     # 向量预处理
│   ├── address_matching.py      # 两阶段地址匹配
│   ├── mgeo_similarity.py       # MGeo 地址相似度匹配
│   ├── result_management.py     # 结果管理与人工纠正
│   └── system_logs.py           # 系统日志
├── database/                    # 数据库层
│   ├── connection.py            # 连接管理、自动重连、search_path
│   ├── data_loader.py           # 建表 / 读写 / 导出 / 结果持久化
│   ├── vector_store.py          # pgvector 向量写入与相似度召回
│   └── tag_manager.py           # 标签隔离表管理
├── model/                       # 模型层
│   ├── base_model_loader.py     # 统一本地/在线模型加载
│   ├── embedding.py             # 地址 → 768 维向量
│   ├── mgeo_model.py            # MGeo 精排三分类
│   └── address_tagging_model.py # 地址 NER 结构化解析
├── matching/                    # 匹配层
│   ├── matcher.py               # 两阶段流程编排 + 异步任务控制
│   ├── ranking.py               # 精排排序与匹配状态判定
│   ├── mgeo_similarity.py       # 地址对直接相似度
│   └── address_tagging_rules.py # 结构化解析规则
├── sql/                         # 房号提取存储过程与说明
├── utils/                       # 日志 / 导出 / 拼音 / 进度
├── tests/                       # pytest 测试用例
└── docs/                        # 补充资料
```

---

## 快速开始

### 1. 环境要求

- Python 3.10+（开发环境 3.12）
- PostgreSQL 14+ 并安装 pgvector 扩展
- 可选：NVIDIA GPU + CUDA 版 PyTorch（CPU 亦可运行，速度较慢）

### 2. 安装依赖

```bash
python -m venv venv
venv\Scripts\activate          # Windows

# 推荐使用国内镜像加速
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

> `requirements.txt` 中 `torch` 指向本地 wheel 文件（`torch-2.11.0+cu130-cp312-cp312-win_amd64.whl`）。
> 该文件缺失或环境不匹配时，请自行安装对应版本的 PyTorch：
> ```bash
> pip install torch --index-url https://download.pytorch.org/whl/cu130
> ```

### 3. 准备模型

模型无需改动代码即可离线部署，加载优先级：

1. `models/iic/mgeo_backbone_chinese_base/`（粗召回）
2. `models/iic/mgeo_geographic_entity_alignment_chinese_base/`（精排）
3. `~/.cache/modelscope/hub/models/iic/...`（可用 `MODELSCOPE_CACHE` 指定）
4. HuggingFace 缓存目录
5. 在线下载（ModelScope → 自动回退 transformers）

### 4. 准备数据库

```sql
CREATE DATABASE your_db;
\c prj_sj_db
CREATE EXTENSION IF NOT EXISTS vector;
CREATE SCHEMA IF NOT EXISTS ai;
```

### 5. 配置连接参数

复制 `.env.example` 为 `.env` 并按实际环境填写：

```env
DB_HOST=localhost
DB_PORT=5432
DB_NAME=
DB_USER=
DB_PASSWORD=your_password_here
DB_SCHEMA=
```

### 6. 启动

```bash
streamlit run app.py
```

或使用一键启动器（自动托管进程、关闭窗口即清理子进程）：

```bash
python launcher.py
```

访问 http://localhost:8501

---

## 使用流程

```
数据库配置 → 向量预处理 → 地址匹配 → 结果管理 → 人工纠正
```

1. **数据库配置**：填写连接参数并测试连接，确认数据表可见
2. **向量预处理**：选择企业表与标准地址表，批量向量化并建立索引
3. **地址匹配**：设置相似度阈值与召回数量，执行两阶段匹配
4. **结果管理**：浏览、筛选匹配结果，导出 Excel/CSV
5. **人工纠正**：对偏差结果手工修正，修正记录单独留存

---

## 关键设计

- **Schema 隔离**：连接后自动执行 `SET search_path TO "schema", public`，业务表落在指定 Schema，同时保留 `public` 以使用 pgvector 扩展
- **标签隔离**：`TagManager` 为每个标签自动生成独立的召回/匹配结果表（中文标签名转拼音作前缀），删除标签级联删除关联表
- **模型加载**：本地优先（`local_files_only`），ModelScope 优先、失败回退 transformers，并修复 checkpoint 键名映射（`bert.text_encoder.*` → `bert.*`）
- **连接缓存**：`st.cache_resource(ttl=60)` 缓存 DB 连接，避免 Streamlit 每次 rerun 重建 TCP 连接
- **实时进度**：基于 `st.fragment` 局部刷新，避免整页 rerun

---

## 主要数据表

| 表名 | 用途 |
| --- | --- |
| `enterprise_vectors` | 企业地址向量（768 维） |
| `standard_address_vectors` | 标准地址向量（768 维） |
| `recall_results` | 粗召回候选结果 |
| `match_results` | 精排匹配最终结果 |
| `mgeo_similarity_results` | MGeo 相似度匹配结果 |
| `address_tagging_results` / `_17_` / `_17_2_` | 地址 12 级 / 17 级结构化解析结果 |

表结构详见 [ARCHITECTURE.md](ARCHITECTURE.md) 第四节。

---

## 测试

```bash
pytest tests/                                     # 全部测试
pytest tests/test_vector_store_rename.py           # 单个文件
pytest tests/test_vector_store_rename.py::TestVectorStoreRename::test_rename   # 单个用例
```

测试主要覆盖数据库 Schema/表名映射、向量表切换、房号提取、流式管线等回归场景。
修改 `database/`、`matching/`、`model/` 后建议运行相关测试验证。

---

## 房号提取存储过程

`sql/extract_house_number.sql` 将项目中的房号解析逻辑下沉到 PostgreSQL，可直接在大表上批量执行：

- `extract_house_number(text)`：房号提取核心函数
- `batch_update_house_number(...)`：批量更新存储过程，支持传入表名、地址字段、房号字段与额外过滤条件

采用 `ctid` keyset pagination 分批处理，避免大表更新时越跑越慢。
详细说明与规则分析见 [sql/提取房号解析存储过程.md](sql/提取房号解析存储过程.md)。

---

## 文档索引

| 文档 | 内容 |
| --- | --- |
| [CODE_WIKI.md](CODE_WIKI.md) | 模块级代码详解与依赖关系 |
| [ARCHITECTURE.md](ARCHITECTURE.md) | 架构设计、数据流、表结构 |
| [DEPLOYMENT.md](DEPLOYMENT.md) | 部署说明 |
| [OPERATION_MANUAL.md](OPERATION_MANUAL.md) | 操作手册 |
| [CLAUDE.md](CLAUDE.md) | 面向 AI 辅助开发的工程约定 |

---

## 注意事项

- 数据库连接参数可通过 `.env` 管理
- 模型权重（`models/`）、虚拟环境（`venv/`）已在 `.gitignore` 中排除，需各自本地准备
- 默认相似度阈值 `0.8`、召回数量 `50`，可在 `config.py` 或界面中调整
- 无 GPU 时自动以 CPU 模式运行，界面上方会显示当前运行设备
