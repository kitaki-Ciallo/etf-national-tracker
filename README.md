# 🏛️ ETF 国家队量化看板

实时追踪国家队（中央汇金、社保基金等）持仓 ETF 的**份额变化**与**十大持有人**状况，帮助观察机构资金动向。

![Python](https://img.shields.io/badge/Python-3.10+-blue?logo=python&logoColor=white)
![Flask](https://img.shields.io/badge/Flask-3.0+-green?logo=flask&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-14+-336791?logo=postgresql&logoColor=white)
![ECharts](https://img.shields.io/badge/ECharts-5-red?logo=apache-echarts&logoColor=white)

> ⚠️ **关于数据时效性**
>
> - **每日份额**：由上交所公布，但存在 **T+1 延迟**（当日份额次日才可获取），看板主页标题处会显示份额数据的实际更新日期。
> - **十大持有人**：严格遵循公募基金信息披露规则，仅在**半年报**（报告期截至 6 月 30 日，8 月底前披露）和**年报**（报告期截至 12 月 31 日，次年 3 月底前披露）中公布，**每半年才更新一次**。因此"国家队持仓占比"及"持仓变化"等指标**延迟最长可达 6 个月**，仅反映最近一次定期报告时点的快照。

## ✨ 功能概览

### 主页看板
- 📈 **国家队 ETF 总份额变化曲线** — 叠加沪深300、中证500、中证1000 价格走势
- 📋 **持仓明细表格** — 日/周/月/季/年份额变化百分比、国家队占比、份额变化、新进标记
- 🔄 支持 1 月 / 3 月 / 1 年时间范围切换
- 🔢 表头可排序，点击行跳转详情

### ETF 详情页
- 📈 **价格 + 份额双轴叠加曲线**
- 👥 **十大持有人对比** — 最新期 vs 上一期，份额变化百分比
- 🏷️ 国家队持有人自动标记

## 🏗️ 技术架构

```mermaid
graph TB
    subgraph 数据采集层
        S1["daily_collector.py<br>每日份额 + 价格采集"]
        S2["holder_collector.py<br>十大持有人采集<br>半年一次"]
        S3["init_data.py<br>历史数据初始化"]
    end

    subgraph 数据存储层
        DB[("PostgreSQL")]
    end

    subgraph 服务层
        API["Flask API 服务<br>app.py"]
    end

    subgraph 展示层
        FE["Web 看板<br>ECharts + HTML/CSS/JS"]
    end

    S1 --> DB
    S2 --> DB
    S3 --> DB
    DB --> API
    API --> FE
```

| 层级 | 技术 |
|---|---|
| 数据采集 | 上交所 SSE API (份额) + 新浪财经 API (价格、持有人) |
| 数据库 | PostgreSQL |
| 后端 | Flask |
| 前端 | HTML + CSS + JavaScript + ECharts |

> 📌 份额采集已**完全移除 AKShare 依赖**，改为直接调用上交所 `query.sse.com.cn` API。采用 `requests` 优先 + `curl` 自动 fallback 的双重策略，确保在云服务器上也能稳定运行。

## 📁 项目结构

```
etf_tools/
├── schema.sql              # PostgreSQL 建表脚本
├── config.py               # 配置文件 (数据库连接、常量)
├── app.py                  # Flask 后端 API
├── init_data.py            # 历史数据初始化 (首次运行)
├── daily_collector.py      # 每日份额 + 价格采集
├── holder_collector.py     # 十大持有人采集 (半年一次)
├── crawl_sse_etf.py        # 上交所 ETF 列表爬虫
├── find_nt_etfs.py         # 国家队 ETF 筛选爬虫
├── requirements.txt        # Python 依赖
└── static/
    ├── index.html          # 看板主页
    ├── detail.html         # ETF 详情页
    ├── css/style.css       # 暗色主题样式
    └── js/
        ├── main.js         # 主页逻辑
        └── detail.js       # 详情页逻辑
```

## 🚀 快速开始

### 1. 环境准备

- Python 3.10+
- PostgreSQL 14+

```bash
pip install -r requirements.txt
```

### 2. 创建数据库

```bash
createdb -U postgres etf_dashboard
psql -U postgres -d etf_dashboard -f schema.sql
```

### 3. 配置数据库连接

编辑 `config.py` 中的 `DB_CONFIG`，或通过环境变量配置：

```bash
export ETF_DB_HOST=localhost
export ETF_DB_PORT=5432
export ETF_DB_NAME=etf_dashboard
export ETF_DB_USER=postgres
export ETF_DB_PASSWORD=your_password
```

### 4. 获取 ETF 列表 & 国家队筛选

```bash
python crawl_sse_etf.py        # 生成 etf_list.csv
python find_nt_etfs.py         # 生成 national_team_etfs.csv
```

### 5. 初始化历史数据

```bash
python init_data.py
```

> 首次运行约需 15-20 分钟，包括：
> - 回溯约 1 年每日份额数据 (直接调用上交所 API)
> - 获取约 1023 条日K线历史价格 (新浪财经)
> - 获取最新两期十大持有人 (新浪财经)

### 6. 启动看板

```bash
python app.py
```

访问 http://localhost:5000

### Docker 部署 (可选)

如果数据库通过 Docker Compose 运行：

```bash
# 1. 创建数据库
docker exec -i <container_id> psql -U quant_user postgres -c "CREATE DATABASE etf_dashboard;"

# 2. 导入表结构
cat schema.sql | docker exec -i <container_id> psql -U quant_user etf_dashboard

# 3. 如果服务器访问上交所 API 较慢，可从本地导出 CSV 再导入
#    本地导出:
#    psql -d etf_dashboard -c "\COPY etf_daily_share TO 'export_share.csv' WITH CSV HEADER"
#    服务器导入:
cat export_share.csv | docker exec -i <container_id> psql -U quant_user etf_dashboard -c "COPY etf_daily_share FROM STDIN WITH CSV HEADER"

# 4. 启动
ETF_DB_PASSWORD='your_password' python app.py
```

## 📅 日常维护

```bash
# 每个交易日收盘后运行 (建议 19:00 之后)
python daily_collector.py

# 指定日期采集
python daily_collector.py --date 20260514

# 半年报/年报发布后运行
python holder_collector.py
```

## 📊 数据源说明

| 数据 | 来源 | 更新频率 | 延迟 |
|---|---|---|---|
| ETF 每日份额 | 上交所 SSE API (`query.sse.com.cn`) | 每个交易日 | T+1 |
| ETF 历史价格 | 新浪财经 K线 API | 每个交易日 | 实时 |
| 十大持有人 | 新浪财经基金 API | 半年报 / 年报 | 最长 6 个月 |
| ETF 列表 | 上交所云行情 API | 按需 | - |

> ⚠️ **数据时效性提示**：份额数据存在 T+1 延迟，十大持有人数据仅在半年报/年报中披露。看板主页会显示份额数据的实际更新日期。

## 🔧 数据库表结构

| 表名 | 用途 |
|---|---|
| `etf_info` | ETF 基本信息 (代码、名称、是否国家队持有) |
| `etf_daily_share` | 每日份额快照 |
| `etf_daily_price` | 每日 OHLCV 价格 |
| `etf_holder` | 十大持有人 (按报告期存储) |
| `nt_etf_list` | 国家队持仓汇总 |

## 📜 License

MIT
