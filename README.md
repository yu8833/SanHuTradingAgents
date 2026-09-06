# SanHuTradingAgents 散户交易智能体

[![License](https://img.shields.io/badge/License-Mixed-blue.svg)](./LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![Documentation](https://img.shields.io/badge/docs-中文文档-green.svg)](./docs/)

---

面向**散户**的多智能体与大模型股票分析学习平台。帮助散户系统化学习如何使用多智能体交易框架与 AI 大模型进行合规的股票研究与策略实验，不提供实盘交易指令，平台定位为学习与研究用途。

## ✨ 核心功能

### 🎯 作战室（WarRoom）

开盘前到收盘后的一站式交易主控台，按「盘前 → 盘中 → 盘后 → 周度」四个时段组织，顶部流程引导条实时显示各时段待办角标（每 60s 自动刷新），进入页面即自动加载各时段数据，无需手动逐项触发。

- **宏观方向判断**：仪表盘式展示当日方向四态（偏多 / 偏空 / 中性观望 / 数据不足）+ 置信度 + 依据明细 + LLM 解读，盘前基准当日锁定避免盘中横跳
- **当日计划生成流水线**：行业方向预测 → 候选池 → 计划装配全链路，带审计进度（后台异步 + SSE 实时推流），盘前 8:15 自动预生成快照，打开即读无需点击
- **盘中买卖指导**：对照实时价评估持仓/待执行计划，三买三卖「待确认指令」直达共享纸面交易执行
- **参考 Tab**：外围指数 / 财经日历（含已公布事件实际值）/ 重要快讯独立实时数据，短缓存秒回，不依赖宏观快照

### 🎯 核心交易主线（候选池 → 自选 → 交易 → 分析 → 策略）

- **候选池**：行业 → 个股 → 择时 三层流水线，自动更新
  - Tab1「强势行业/概念」：基于本地个股 `industry` 聚合的动量/量能合成行业强度分 `sector_score`
  - Tab2「候选个股」：多因子质量打分（估值/盈利/规模/ΔG景气/财务/技术），叠加三买三卖择时预览与辅助信号确认
  - 顶部大盘总开关 + 「加入自选」批量入口，可直接转入自选池
- **监控中心**：三买三卖规则引擎自动执行闭环
  - 内置三条默认 `tbs` 规则（默认启用、可修改、可关闭、**不可删除**）：买1监自选→买入；买2/3、卖1/2/3监持仓→加减仓→清仓转自选
  - 择时信号由系统自动计算，可配置监听方向与信号，落为「待确认指令」后走共享纸面交易入口执行
- **交易复盘**：自动成交记录 + 手动复盘笔记，沉淀「决策 → 执行 → 复盘 → 改进」经验飞轮

### 🤖 智能分析系统

- **多智能体协同分析**：7 位分析师（技术面、情绪面、新闻面、基本面、政策面、游资追踪、解禁追踪）并行工作，经质量门控 → 多空研究员 → 交易员 → 三方风控辩论 → 组合经理的 LangGraph 有状态工作流
- **公式化硬打分**：6 位分析师（市场/基本面/新闻/资金/情绪/解禁）由规则引擎确定性打分，与 LLM 主观评分偏差超过阈值时自动标注警示，将主观评分转为可验证的量化环节
- **置信度统计校准**：按评级/置信度分桶统计历史命中率并计算校准曲线，注入风控与组合经理 prompt，让决策置信度有实证支撑
- **风控决策机制**：三方风控（激进/保守/风险经理）双重验证，确保分析质量
- **置信度评估**：自动计算报告质量评分，提供可信度参考
- **风险扫描**：4 大类 40+ 检查项（财务类、市场类、交易类、ST退市）全方位风险预警
- **多维度报告**：维度分析、多空辩论、最终结论、完整报告等多种视图
- **快速分析模式**：简化版快速分析报告，适合快速决策
- **批量分析功能**：支持多只股票同时分析（后台任务 + 日志实时推流），提升工作效率

### 📊 策略系统

- **三买三卖**：基于成交量、K线涨幅、均线形态、大盘配合、MACD 五维度评分系统，内置 B1/B2/B3/S1/S2/S3 六信号择时引擎
- **常用策略池**：14 个统一卡片策略（均线/金叉、趋势突破、超跌反弹、量价齐升、困境反转、小盘价值等），可统一筛选、回测、加自选
- **智能股票筛选**：基于多维度指标的股票筛选和排序系统
- **回测系统**：策略历史回测与性能验证，结果持久化到 MongoDB，支持跨策略结果对比
  - **防未来函数**：T 日收盘信号一律 T+1 开盘执行（信号后移一天），止损/止盈按触发价成交，杜绝"已知当日价格再成交"的高估
  - **后复权治理**：默认用 `pct_chg` 链重建 hfq 后复权价格，消除除权除息造成的价格断层，避免误触发 MA/突破类信号
  - **成交成本真实**：回测纳入滑点与手续费，避免收益虚高
  - **技术指标本地计算**：指标在本地 pandas 原子计算，与数据源解耦、可复现

### 📰 投研资讯中心

- **宏观快扫**：交易日盘前（8:15）自动聚合外围指数/财经日历/重要快讯/大盘状态，经规则引擎定方向与置信度，LLM 解读后落库；快照缺失时自动在后台补生成，打开即读
- **复盘模块**：大盘看板、短线情绪、概念分析全景监控
- **资讯模块**：12 赛道 108 个 RSS 源资讯雷达、个股公告、个股新闻
- **板块模块**：板块骨架、板块详情、板块资金流分析
- **记录模块**：研究记录本地管理，支持标签和搜索

### 💼 投资管理

- **自选股管理**：个人自选股收藏、分组管理和跟踪功能，支持作用域隔离
- **个股详情页**：完整的个股信息展示和历史分析记录
- **模拟交易系统**：虚拟交易环境，验证投资策略效果
- **投资组合**：持仓管理与收益跟踪

### ⚙️ 系统管理

- **用户权限管理**：完整的用户认证、角色管理、操作日志系统
- **配置管理中心**：可视化的大模型配置、数据源管理、系统设置
- **多 LLM 提供商**：支持 OpenAI、Google、国内主流模型等多家供应商
- **多数据源同步**：统一的数据源管理，支持 Tushare、AkShare、BaoStock 三级容灾 + 一致性校验与自动补数
- **多市场支持**：统一查询 A股 / 港股 / 美股，支持多市场行情同步与 ETF 数据
- **缓存管理系统**：智能缓存策略，支持 Redis / 文件多级缓存 + 动态 TTL 失效
- **实时通知系统**：WebSocket + SSE 双通道推送，实时跟踪分析进度与行情变化
- **定时任务调度**：可视化任务管理与调度，含数据完整性检查与自动补数
- **报告中心**：分析报告归档、结构化字段抽取，支持 Markdown 下载导出

## 🏗️ 技术架构

| 层级 | 技术选型 |
|------|---------|
| **后端框架** | FastAPI + Uvicorn |
| **前端框架** | Vue 3 + Vite + Element Plus |
| **AI 框架** | LangGraph + LangChain |
| **数据库** | MongoDB + Redis |
| **消息队列** | Redis Queue |
| **任务调度** | APScheduler |
| **部署方式** | Docker + Docker Compose |
| **数据源** | Tushare + AkShare + BaoStock（三级容灾）+ 多市场（A股/港股/美股） |

## 🚀 快速开始

### Docker 部署（推荐）

```bash
# 克隆仓库
git clone https://github.com/your-username/SanHuTradingAgents.git
cd SanHuTradingAgents

# 复制环境变量配置
cp .env.example .env
# 编辑 .env 配置 LLM API 密钥等

# 启动服务
docker compose up -d

# 访问前端
# http://localhost
# 默认账号: admin / admin123
```

Docker Compose 包含：`backend`（FastAPI 后端）、`worker`（分析任务）、`backtest_worker`（回测任务）、`frontend`（Vue 前端）、`mongodb`、`redis`，以及可选的 `test` / `redis-commander` / `mongo-express` 服务（通过 `--profile test` / `--profile management` 启用）。

### 本地开发

```bash
# 后端
cd SanHuTradingAgents
pip install -r requirements.txt
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 前端
cd frontend
yarn install
yarn dev
```

## 📁 项目结构

```
SanHuTradingAgents/
├── app/                          # 后端 FastAPI 应用
│   ├── core/                     # 核心配置、数据库、Redis、日志、中间件
│   ├── models/                   # 数据模型
│   ├── routers/                  # API 路由（分析/选股/候选池/监控/复盘/模拟交易等）
│   ├── services/                 # 业务服务层
│   │   ├── candidate_pool/       # 候选池三层流水线
│   │   │   ├── industry_layer.py         # 第1层：行业轮动打分
│   │   │   ├── stock_score_layer.py      # 第2层：个股多因子打分
│   │   │   ├── auxiliary_signal_layer.py # 第3层：辅助信号确认
│   │   │   └── candidate_pool_service.py # 编排 0→1→2→3 层
│   │   ├── monitor_service.py    # 监控中心规则引擎（含三买三卖自动执行）
│   │   ├── paper_executor.py     # 共享纸面交易执行入口
│   │   ├── screening_service.py  # 选股服务
│   │   ├── macro/                # 宏观快扫（快照/规则引擎/LLM解读/财经日历）
│   │   ├── plan_generation_service.py # 当日计划生成流水线（后台任务+SSE进度）
│   │   ├── data_sources/         # 多数据源适配（Tushare/AkShare/BaoStock）
│   │   └── ...（行情/新闻/财务/景气/复盘等）
│   ├── strategy_system/          # 策略系统
│   │   ├── strategies.py         # 内置策略池（三买三卖/常用策略）
│   │   ├── screener.py           # 策略筛选
│   │   ├── backtest.py           # 回测引擎（防未来函数/后复权/真实成本）
│   │   ├── data_adapter.py       # 回测数据面板加载（hfq 复权）
│   │   ├── backtest_results_store.py     # 回测结果落库
│   │   └── task_manager.py       # 回测任务管理
│   ├── routers/
│   │   ├── war_room.py           # 作战室聚合（宏观/当日计划/盘中指导）
│   │   ├── macro.py              # 宏观快扫 API
│   │   └── ...（分析/选股/候选池/监控/复盘/模拟交易等）
│   ├── worker/                   # 异步任务 Worker（分析/回测/数据同步）
│   └── main.py                   # 应用入口
├── frontend/                     # 前端 Vue 3 应用
│   └── src/
│       ├── views/                # 页面组件
│       │   ├── WarRoom/          # 作战室（盘前/盘中/盘后/周度 一站式主控台）
│       │   ├── Candidate/        # 候选池（Tab1 强势行业 / Tab2 候选个股）
│       │   ├── StockAlerts/      # 监控中心（三买三卖规则引擎）
│       │   ├── PaperTrading/     # 模拟交易 + 交易复盘
│       │   ├── Screening/        # 策略（三买三卖/常用策略/回测）
│       │   ├── Vibe/             # 投研资讯（复盘/资讯）
│       │   ├── Tasks/            # 任务中心（定时任务调度）
│       │   └── System/           # 系统管理
│       ├── components/           # 公共组件
│       └── api/                  # API 封装
├── tradingagents/                # 多智能体分析核心（LangGraph）
│   ├── agents/
│   │   ├── analysts/             # 7 位分析师（技术/情绪/新闻/基本面/政策/游资/解禁）
│   │   ├── managers/             # 多空研究员 / 组合经理
│   │   └── utils/                # 公式化硬打分 / 置信度统计校准 / 记忆等
│   ├── graph/                    # 分析工作流（并行分析/否决/信号处理/反射/状态持久化）
│   └── dataflows/                # 数据流与工具接入
├── docs/                         # 文档
├── scripts/                      # 运维/构建/调试脚本
├── docker-compose.yml            # Docker Compose 配置
└── README.md
```

## 📄 许可证

本项目采用**混合许可证**模式，详见 [LICENSE](LICENSE) 文件：

- **开源部分（Apache 2.0）**：除 `app/` 和 `frontend/` 外的所有文件
- **专有部分（需商业授权）**：`app/`（FastAPI 后端）和 `frontend/`（Vue 前端）目录

详见 [COPYRIGHT.md](./COPYRIGHT.md)。

## 🙏 致谢

本项目基于以下优秀开源项目衍生而来，在此致以最诚挚的感谢：

- **[TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents)** — 原始多智能体交易框架
- **[TradingAgents-CN](https://github.com/yu8833/TradingAgents-CN)** — 中文增强版，本项目的基础

详细致谢请参阅 [ACKNOWLEDGMENTS.md](./ACKNOWLEDGMENTS.md)。

## ⚠️ 风险提示

**重要声明**：本框架仅用于研究和教育目的，不构成投资建议。

- 📊 交易表现可能因多种因素而异
- 🤖 AI 模型的预测存在不确定性
- 💰 投资有风险，决策需谨慎
- 👨‍💼 建议咨询专业财务顾问

---

<div align="center">

**🌟 如果这个项目对您有帮助，请给我们一个 Star！**

</div>