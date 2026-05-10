# 中文地址语义匹配系统 - 架构设计文档

## 一、系统架构概览

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              用户界面层 (Streamlit)                          │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐      │
│  │ 数据库配置 │  │ 向量预处理 │  │ 地址匹配  │  │ 结果管理  │  │ 系统日志  │      │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘  └──────────┘      │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                              应用核心层 (app.py)                             │
│  - 页面路由与状态管理                                                          │
│  - 用户交互处理                                                               │
│  - 各功能模块协调                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌──────────────┬──────────────┬──────────────┬──────────────┬─────────────────┐
│   配置模块    │  数据库连接层  │  向量存储层   │   匹配引擎层  │    模型层        │
│  (config.py) │ (connection) │(vector_store)│  (matcher)   │   (model)       │
├──────────────┼──────────────┼──────────────┼──────────────┼─────────────────┤
│ 系统配置参数  │ DBConnection │ VectorStore  │AddressMatcher│ AddressEmbedder │
│ 数据库配置   │ DataLoader   │              │RankingEngine │   MGeoModel     │
│ 模型配置    │              │              │MGeoSimilarity│                 │
└──────────────┴──────────────┴──────────────┴──────────────┴─────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                              数据持久化层                                     │
│                    PostgreSQL + pgvector 扩展                                │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐      │
│  │ 企业向量表 │  │标准地址向量表│  │ 召回结果表 │  │ 匹配结果表 │  │ 相似度结果表 │      │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘  └──────────┘      │
│  ┌──────────┐  ┌──────────┐                                                  │
│  │ 标签配置表 │  │ 系统日志表 │                                                  │
│  └──────────┘  └──────────┘                                                  │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                              模型层                                          │
│  ┌──────────────────────────────┐  ┌──────────────────────────────────────┐  │
│  │   粗召回模型                    │  │          精排模型                     │  │
│  │ mgeo_backbone_chinese_base    │  │ mgeo_geographic_entity_alignment_   │  │
│  │   (地址编码器)                  │  │        chinese_base                 │  │
│  │   - 生成地址向量                │  │   (地址匹配分类器)                     │  │
│  │   - 支持CPU/GPU               │  │   - 精确匹配/部分匹配/不匹配分类        │  │
│  └──────────────────────────────┘  └──────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
```

## 二、模块职责

### 2.1 用户界面层 (app.py)

基于 Streamlit 构建的 Web 界面，提供五个核心功能模块：

| 模块 | 功能描述 |
|------|---------|
| 数据库配置 | PostgreSQL连接配置，支持自定义Schema |
| 向量预处理 | 企业地址/标准地址的向量生成与存储 |
| 地址匹配 | 库表输入/文件输入两种模式的地址匹配 |
| 结果管理 | 匹配结果查看、筛选、导出、人工纠正 |
| 系统日志 | 实时日志、数据库存储日志、向量调试测试 |

### 2.2 配置模块 (config.py)

集中管理所有系统配置参数：
- 数据库连接参数（支持自定义Schema）
- 模型配置（模型名称、设备选择、批处理大小）
- 向量维度、表名配置
- 日志配置

### 2.3 数据库连接层 (database/connection.py)

`DBConnection` 类封装 PostgreSQL 数据库操作：
- 连接管理与自动重连
- SQL 执行与参数化查询
- 事务管理（commit/rollback）
- 表结构查询（支持中文表名）
- 自动设置 `search_path` 到用户指定的 Schema

### 2.4 数据加载层 (database/data_loader.py)

`DataLoader` 类提供数据读写操作：
- 向量表创建与数据插入（支持中文表名）
- 召回结果/匹配结果的增删改查
- 分页查询与统计
- 批量导出（CSV/Excel）
- 旧表自动迁移（添加 `correction_source` 字段）

### 2.5 向量存储层 (database/vector_store.py)

`VectorStore` 类封装 pgvector 向量检索：
- 向量相似度查询（余弦相似度）
- Top-K 召回
- 相似度阈值过滤

### 2.6 匹配引擎层 (matching/)

| 类 | 文件 | 职责 |
|----|------|------|
| `AddressMatcher` | matcher.py | 地址匹配主流程：粗召回 + 精排 |
| `RankingEngine` | ranking.py | MGeo精排：候选排序与匹配状态判断 |
| `MGeoSimilarity` | mgeo_similarity.py | 两地址直接相似度计算 |

**精排排序逻辑**：
1. 主排序：`exact_match` 降序（精确匹配概率最高）
2. 次排序：`not_match` 升序（不匹配概率最低）

**匹配状态判断**：取三个概率中的最大值
- `exact_match` 最大 → 精确匹配
- `partial_match` 最大 → 部分匹配
- `not_match` 最大 → 不匹配

**相似度阈值双重过滤**：
- 粗召回阶段：SQL WHERE 条件过滤
- 精排阶段：Python 代码过滤

### 2.7 模型层 (model/)

| 类 | 文件 | 职责 |
|----|------|------|
| `AddressEmbedder` | embedding.py | 地址向量化（粗召回模型） |
| `MGeoModel` | mgeo_model.py | 地址匹配分类（精排模型） |

**模型加载策略**（优先级从高到低）：
1. 项目目录 `models/` 文件夹
2. ModelScope 缓存目录
3. 环境变量 `MODELSCOPE_CACHE` 指定目录
4. HuggingFace 缓存目录
5. 在线下载（modelscope → transformers）

**加载库优先级**：modelscope → transformers（需 `trust_remote_code=True`）

### 2.8 标签管理层 (database/tag_manager.py)

`TagManager` 类管理匹配标签：
- 创建标签（自动生成拼音前缀）
- 删除标签（级联删除关联数据表）
- 查询标签列表
- 每个标签有独立的召回表和匹配表

### 2.9 工具层 (utils/)

| 模块 | 文件 | 职责 |
|------|------|------|
| 日志 | logger.py | 内存日志 + 数据库持久化日志 |
| 导出 | export.py | CSV/Excel 导出辅助 |
| 拼音 | pinyin_utils.py | 中文转拼音（标签前缀生成） |

## 三、数据流

### 3.1 向量预处理流程

```
用户上传/选择数据
    │
    ▼
┌─────────────────┐
│  读取地址数据    │ ← 库表输入 / 文件输入
└─────────────────┘
    │
    ▼
┌─────────────────┐
│  地址文本清洗    │ ← 去除空格、标准化
└─────────────────┘
    │
    ▼
┌─────────────────┐
│  MGeo编码器推理  │ ← AddressEmbedder
│  (batch处理)     │
└─────────────────┘
    │
    ▼
┌─────────────────┐
│  向量存储到DB    │ ← pgvector vector类型
└─────────────────┘
```

### 3.2 地址匹配流程

```
用户配置匹配参数
    │
    ▼
┌─────────────────┐
│  读取企业地址    │ ← 库表输入 / 文件输入
└─────────────────┘
    │
    ▼
┌─────────────────┐
│  粗召回 (Top-K)  │ ← 向量相似度查询
│  相似度阈值过滤  │ ← SQL WHERE 条件
└─────────────────┘
    │
    ▼
┌─────────────────┐
│  MGeo精排模型推理 │ ← 企业地址 + 标准地址
│  (batch处理)     │
└─────────────────┘
    │
    ▼
┌─────────────────┐
│  候选排序与过滤  │ ← exact_match降序 + not_match升序
│  相似度阈值过滤  │ ← Python代码过滤
└─────────────────┘
    │
    ▼
┌─────────────────┐
│  匹配状态判断    │ ← 三概率取最大
└─────────────────┘
    │
    ▼
┌─────────────────┐
│  结果存储/导出   │ ← 数据库 / CSV / Excel
└─────────────────┘
```

### 3.3 MGeo地址相似度流程

```
用户上传/选择两列地址数据
    │
    ▼
┌─────────────────┐
│  读取地址对      │ ← 地址A + 地址B
└─────────────────┘
    │
    ▼
┌─────────────────┐
│  MGeo精排模型推理 │ ← 地址A + 地址B
│  (batch处理)     │
└─────────────────┘
    │
    ▼
┌─────────────────┐
│  匹配状态判断    │ ← 三概率取最大
└─────────────────┘
    │
    ▼
┌─────────────────┐
│  结果存储/导出   │ ← 数据库 / CSV / Excel
└─────────────────┘
```

## 四、数据库表结构

### 4.1 向量表

**企业向量表** (`enterprise_address_vectors`)
| 字段 | 类型 | 说明 |
|------|------|------|
| id | SERIAL | 主键 |
| source_id | VARCHAR(255) | 企业标识 |
| enterprise_name | TEXT | 企业名称 |
| address | TEXT | 企业地址 |
| vector | vector(768) | 地址向量（768维） |
| created_at | TIMESTAMP | 创建时间 |

**标准地址向量表** (`standard_address_vectors`)
| 字段 | 类型 | 说明 |
|------|------|------|
| id | SERIAL | 主键 |
| source_id | VARCHAR(255) | 标准地址编码 |
| address | TEXT | 标准地址 |
| room_no | VARCHAR(100) | 房屋编码 |
| vector | vector(768) | 地址向量（768维） |
| created_at | TIMESTAMP | 创建时间 |

### 4.2 结果表

**粗召回结果表** (`recall_results`)
| 字段 | 类型 | 说明 |
|------|------|------|
| id | SERIAL | 主键 |
| enterprise_id | VARCHAR(255) | 企业标识 |
| enterprise_name | TEXT | 企业名称 |
| enterprise_address | TEXT | 企业地址 |
| standard_id | VARCHAR(255) | 标准地址编码 |
| standard_address | TEXT | 标准地址 |
| room_no | VARCHAR(100) | 房屋编码 |
| similarity | DOUBLE PRECISION | 向量相似度 |
| created_at | TIMESTAMP | 创建时间 |

**精排匹配结果表** (`match_results`)
| 字段 | 类型 | 说明 |
|------|------|------|
| id | SERIAL | 主键 |
| enterprise_id | VARCHAR(255) | 企业标识 |
| enterprise_name | TEXT | 企业名称 |
| enterprise_address | TEXT | 企业地址 |
| address_id | VARCHAR(255) | 匹配的标准地址编码 |
| standard_address | TEXT | 匹配的标准地址 |
| room_no | VARCHAR(100) | 房屋编码 |
| exact_match | DOUBLE PRECISION | 精确匹配概率 |
| partial_match | DOUBLE PRECISION | 部分匹配概率 |
| not_match | DOUBLE PRECISION | 不匹配概率 |
| match_status | VARCHAR(20) | 匹配状态 |
| correction_source | VARCHAR(20) | 纠正来源（自动匹配/人工纠正） |
| created_at | TIMESTAMP | 创建时间 |

**MGeo相似度结果表** (`mgeo_similarity_results`)
| 字段 | 类型 | 说明 |
|------|------|------|
| id | SERIAL | 主键 |
| address_a | TEXT | 地址A |
| address_b | TEXT | 地址B |
| exact_match | FLOAT | 精确匹配概率 |
| partial_match | FLOAT | 部分匹配概率 |
| not_match | FLOAT | 不匹配概率 |
| match_status | VARCHAR(20) | 匹配状态 |
| created_at | TIMESTAMP | 创建时间 |

### 4.3 配置表

**标签配置表** (`match_tags`)
| 字段 | 类型 | 说明 |
|------|------|------|
| id | SERIAL | 主键 |
| tag_name | VARCHAR(255) | 标签显示名 |
| prefix | VARCHAR(100) | 表名前缀（唯一） |
| recall_table | VARCHAR(255) | 关联召回结果表名 |
| match_table | VARCHAR(255) | 关联匹配结果表名 |
| created_at | TIMESTAMP | 创建时间 |

**系统日志表** (`system_logs`)
| 字段 | 类型 | 说明 |
|------|------|------|
| id | SERIAL | 主键 |
| level | VARCHAR(20) | 日志级别 |
| message | TEXT | 日志内容 |
| created_at | TIMESTAMP | 创建时间 |

> **注意**: 以上表名为默认名称，实际表名由 `Config` 类中的配置决定。
> `DataLoader` 的方法支持 `table_name` 参数覆盖默认表名。
> 标签功能会为每个标签创建独立的 `{prefix}_recall_results` 和 `{prefix}_match_results` 表。

## 五、关键技术点

### 5.1 向量检索

使用 pgvector 扩展实现高效的向量相似度查询：
- 向量类型：`vector(768)`
- 相似度计算：余弦相似度（1 - 余弦距离）
- 索引：支持 ivfflat/hnsw 索引（可后续优化）

### 5.2 批处理策略

- **向量生成**：默认 batch_size=1000，根据GPU显存调整
- **模型推理**：默认 batch_size=32，根据GPU显存调整
- **数据库读取**：默认 batch_size=1000
- **结果导出**：每5000条一个工作表（Excel）

### 5.3 设备选择

系统自动检测 GPU 可用性：
- 检测到 NVIDIA 显卡且 CUDA 可用 → GPU 模式
- 否则 → CPU 模式
- 用户可在界面中手动选择设备

### 5.4 Schema 隔离

支持非 public Schema：
- 连接数据库时自动设置 `search_path`
- 所有表操作在指定 Schema 下执行
- 保留 `public` 模式以访问 pgvector 等扩展
- 支持中文表名（自动双引号引用）

### 5.5 标签隔离

- 每个标签有独立的召回表和匹配表
- 标签前缀由中文自动转拼音生成
- 删除标签级联删除关联数据表
- 结果管理支持按标签筛选

## 六、扩展性设计

### 6.1 模型替换

`AddressEmbedder` 和 `MGeoModel` 封装了模型加载和推理逻辑，替换模型只需修改对应类：
- 修改模型名称或路径
- 调整向量维度（需同步修改数据库表结构）

### 6.2 数据库迁移

`DataLoader` 内置旧表迁移逻辑：
- 自动检测缺失字段
- 执行 ALTER TABLE 添加字段
- 旧数据默认值处理

### 6.3 新增匹配模式

在 `AddressMatcher` 中可扩展新的匹配策略：
- 修改候选排序逻辑
- 添加新的过滤条件
- 集成其他模型

## 七、文件结构

```
address_match/
├── app.py                          # 主应用（Streamlit界面）
├── config.py                       # 系统配置
├── requirements.txt                # Python依赖
├── ARCHITECTURE.md                 # 架构设计文档（本文档）
├── DEPLOYMENT.md                   # 部署文档
├── OPERATION_MANUAL.md             # 使用说明文档
├── .gitignore                      # Git忽略配置
│
├── database/                       # 数据库模块
│   ├── __init__.py
│   ├── connection.py               # 数据库连接
│   ├── data_loader.py              # 数据加载器
│   ├── vector_store.py             # 向量存储
│   └── tag_manager.py              # 标签管理
│
├── matching/                       # 匹配引擎
│   ├── __init__.py
│   ├── matcher.py                  # 地址匹配器
│   ├── ranking.py                  # 排序引擎
│   └── mgeo_similarity.py          # MGeo相似度
│
├── model/                          # 模型层
│   ├── __init__.py
│   ├── embedding.py                # 地址编码器
│   └── mgeo_model.py               # MGeo分类模型
│
├── utils/                          # 工具模块
│   ├── __init__.py
│   ├── logger.py                   # 日志系统
│   ├── export.py                   # 导出工具
│   └── pinyin_utils.py             # 拼音转换
│
├── models/                         # 本地模型目录（可选）
│   └── iic/
│       ├── mgeo_backbone_chinese_base/
│       └── mgeo_geographic_entity_alignment_chinese_base/
│
└── app.log                         # 应用日志文件
```
