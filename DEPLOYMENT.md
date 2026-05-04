# 中文地址语义匹配系统 - 部署文档

## 一、系统环境要求

### 硬件要求
- **CPU模式**: 4核以上CPU，16GB以上内存
- **GPU模式**: NVIDIA GPU (支持CUDA)，8GB以上显存，16GB以上内存

### 软件要求
- Python 3.10+
- PostgreSQL 14+
- pgvector 0.5+

## 二、环境部署步骤

### 2.1 安装 PostgreSQL 与 pgvector

#### Windows 系统
1. 下载 PostgreSQL 安装包: https://www.postgresql.org/download/windows/
2. 运行安装程序，按提示完成安装
3. 安装 pgvector 扩展:
   ```powershell
   psql -U postgres -d postgres -c "CREATE EXTENSION vector;"
   ```

#### Linux 系统 (Ubuntu/Debian)
```bash
sudo apt update
sudo apt install postgresql postgresql-client
sudo apt install postgresql-14-pgvector
psql -U postgres -d postgres -c "CREATE EXTENSION vector;"
```

### 2.2 创建数据库

```sql
psql -U postgres
CREATE DATABASE postgres;
\c postgres
CREATE EXTENSION vector;
```

> 如需使用非public模式（Schema），请提前创建：
> ```sql
> CREATE SCHEMA ai;
> ```

### 2.3 安装 Python 依赖

1. 创建虚拟环境:
```bash
python -m venv venv
```

2. 激活虚拟环境:
- Windows: `venv\Scripts\activate`
- Linux/macOS: `source venv/bin/activate`

3. 安装依赖:
```bash
pip install -r requirements.txt
```

> **GPU用户**: 如需使用GPU加速，请安装CUDA版PyTorch:
> ```bash
> pip install torch --index-url https://download.pytorch.org/whl/cu118
> ```
> 系统会自动检测GPU并选择运行模式，无需手动配置。

### 2.4 下载 MGeo 模型

系统使用两个 MGeo 模型，支持多种方式部署模型文件：

#### 方式1：项目目录部署（推荐，适合离线部署）

将模型文件放置在项目目录的 `models/` 文件夹下：

```
address_match/
├── models/
│   └── iic/
│       ├── mgeo_backbone_chinese_base/          ← 粗召回模型
│       │   ├── config.json
│       │   ├── pytorch_model.bin
│       │   ├── tokenizer.json
│       │   └── ...
│       └── mgeo_geographic_entity_alignment_chinese_base/  ← 精排模型
│           ├── config.json
│           ├── pytorch_model.bin
│           ├── tokenizer.json
│           └── ...
```

模型下载地址：
- 粗召回模型: https://www.modelscope.cn/models/iic/mgeo_backbone_chinese_base
- 精排模型: https://www.modelscope.cn/models/iic/mgeo_geographic_entity_alignment_chinese_base

#### 方式2：ModelScope 缓存目录

首次运行时系统会自动从网络下载模型到缓存目录：

```
~/.cache/modelscope/hub/models/iic/mgeo_backbone_chinese_base/
~/.cache/modelscope/hub/models/iic/mgeo_geographic_entity_alignment_chinese_base/
```

也可通过环境变量指定缓存目录：
```bash
# Windows
set MODELSCOPE_CACHE=D:\modelscope_cache

# Linux/macOS
export MODELSCOPE_CACHE=/data/modelscope_cache
```

#### 方式3：在线下载

如果网络可以访问 ModelScope 或 HuggingFace，系统会自动在线下载模型（约1.5GB）。

> **模型加载策略**: 系统按以下优先级搜索和加载模型：
> 1. 项目目录 `models/` 文件夹
> 2. ModelScope 缓存目录
> 3. 环境变量 `MODELSCOPE_CACHE` 指定的目录
> 4. HuggingFace 缓存目录
> 5. 在线下载（modelscope → transformers）
>
> 加载库优先级：modelscope → transformers（需 `trust_remote_code=True`）

### 2.5 配置数据库连接

在系统界面中配置数据库连接信息，包括：
- **数据库主机**: 数据库服务器地址（默认 localhost）
- **端口**: PostgreSQL 端口（默认 5432）
- **数据库名**: 数据库名称（默认 postgres）
- **模式（Schema）**: 数据库模式名（默认 public，可改为自定义模式如 ai）
- **用户名**: 数据库用户名（默认 postgres）
- **密码**: 数据库密码

> **重要**: 连接数据库后，系统会自动设置 `search_path` 到用户指定的 Schema，
> 所有表操作（创建向量表、召回结果表等）都会在该 Schema 下执行。
> 同时保留 `public` 模式以访问 pgvector 等扩展。

## 三、启动程序

```bash
# 激活虚拟环境
source venv/bin/activate  # Linux/macOS
venv\Scripts\activate     # Windows

# 启动 Streamlit 应用
streamlit run app.py
```

启动后访问 http://localhost:8501 即可使用系统。

> 系统启动后会在界面中显示当前运行模式（GPU/CPU），如检测到NVIDIA独立显卡将自动使用GPU加速。

## 四、数据库表结构

系统运行时会自动在用户指定的 Schema 下创建以下表：

### recall_results（粗召回结果表）
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

### match_results（精排匹配结果表）
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
| match_status | VARCHAR(20) | 匹配状态（精确匹配/部分匹配/不匹配） |
| correction_source | VARCHAR(20) | 纠正来源（自动匹配/人工纠正），默认"自动匹配" |
| created_at | TIMESTAMP | 创建时间 |

### mgeo_similarity_results（MGeo地址相似度匹配结果表）
| 字段 | 类型 | 说明 |
|------|------|------|
| id | SERIAL | 主键 |
| address_a | TEXT | 地址A |
| address_b | TEXT | 地址B |
| exact_match | FLOAT | 精确匹配概率 |
| partial_match | FLOAT | 部分匹配概率 |
| not_match | FLOAT | 不匹配概率 |
| match_status | VARCHAR(20) | 匹配状态（精确匹配/部分匹配/不匹配） |
| created_at | TIMESTAMP | 创建时间 |

> **注意**: 以上表名为默认名称，实际表名由 `Config` 类中的配置决定。
> `DataLoader` 的方法支持 `table_name` 参数覆盖默认表名。

## 五、精排匹配逻辑说明

MGeo精排模型输出三个概率值：exact_match（精确匹配）、partial_match（部分匹配）、not_match（不匹配）。

候选排序逻辑：
1. **主排序标准**: `exact_match` - 按精确匹配概率最高值筛选最佳匹配候选
2. **次排序标准**: `not_match` - 当 exact_match 相同时，优先选择不匹配概率更低的候选

匹配状态判断：取三个概率中最大值决定匹配状态
- exact_match 最大 → 精确匹配
- partial_match 最大 → 部分匹配
- not_match 最大 → 不匹配
- 无候选 → 不匹配

### 相似度阈值过滤

相似度阈值在两个阶段均生效，实现双重过滤：

1. **粗召回阶段**：SQL `WHERE` 条件过滤，在数据库层面排除向量相似度低于阈值的候选
2. **精排阶段**：Python 代码中再次过滤，确保即使粗召回未过滤，精排阶段仍可按阈值过滤

> 阈值设为 0 表示不过滤，保留所有候选；阈值越高，过滤越严格。

## 六、常见问题

### Q1: 模型加载失败
- **项目目录部署**：将模型文件放置在 `address_match/models/iic/` 目录下
- **缓存目录部署**：确保模型已下载到 `~/.cache/modelscope/hub/models/iic/` 目录
- **环境变量**：通过 `MODELSCOPE_CACHE` 环境变量指定模型缓存目录
- **在线下载**：配置国内镜像源 `export HF_ENDPOINT="https://hf-mirror.com"`
- **查看日志**：系统日志中会显示详细的模型搜索和加载过程

### Q2: 非public模式下创建向量表失败
- 确保在数据库配置页面填写了正确的模式名（Schema）
- 系统会自动设置 `search_path`，所有表操作在指定 Schema 下执行
- 支持中文表名，系统会自动对SQL标识符进行双引号引用

### Q3: CUDA 不可用
- 确保安装了 NVIDIA 驱动和 CUDA Toolkit
- 安装 GPU 版 PyTorch: `pip install torch --index-url https://download.pytorch.org/whl/cu118`
- 系统会自动回退到CPU模式运行

### Q4: 内存不足
- 减小批处理参数（数据库读取批次、模型推理批次）
- 使用 CPU 模式运行

### Q5: MGeo精排结果全部为0
- 确认模型加载时指定了 `num_labels=3`
- 检查 app.log 中是否有 "index 2 is out of bounds" 错误
- 确认模型文件完整，特别是 configuration.json 中包含 id2label 配置

### Q6: session_state 报错
- 确保使用最新版本代码，已内置 session_state 初始化保护
- 翻页功能已使用 `on_click` 回调机制，解决 widget 绑定后无法修改 session_state 的问题
- 如仍出现报错，尝试清除浏览器缓存后重新访问

### Q7: 相似度阈值不起作用
- 确保使用最新版本代码，阈值已在粗召回和精排两个阶段生效
- 粗召回阶段：SQL WHERE 条件过滤
- 精排阶段：Python 代码过滤

### Q8: MGeo相似度匹配文件输入结果如何获取
- 文件输入模式下，匹配结果不会写入数据库
- 匹配完成后页面会显示"下载Excel格式"和"下载CSV格式"两个下载按钮
- 点击即可将匹配结果保存到本地

### Q9: 旧数据库缺少correction_source字段
- 系统启动时会自动检测并迁移旧表，添加 `correction_source` 字段
- 无需手动执行 ALTER TABLE，系统自动处理
- 旧数据默认 `correction_source='自动匹配'`
