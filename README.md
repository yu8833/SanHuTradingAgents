# SanHuTradingAgents 散户交易智能体

[![License](https://img.shields.io/badge/License-Mixed-blue.svg)](./LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![Documentation](https://img.shields.io/badge/docs-中文文档-green.svg)](./docs/)

---

面向**散户**的多智能体与大模型股票分析学习平台。帮助散户系统化学习如何使用多智能体交易框架与 AI 大模型进行合规的股票研究与策略实验，不提供实盘交易指令，平台定位为学习与研究用途。

## ✨ 核心功能

### 🤖 智能分析系统

- **多智能体协同分析**：7 位分析师（技术面、情绪面、新闻面、基本面、政策面、游资追踪、解禁追踪）并行工作
- **风控决策机制**：三方风控（激进/保守/风险经理）双重验证，确保分析质量
- **置信度评估**：自动计算报告质量评分，提供可信度参考
- **风险扫描**：4 大类 40+ 检查项（财务类、市场类、交易类、ST退市）全方位风险预警
- **多维度报告**：维度分析、多空辩论、最终结论、完整报告等多种视图
- **快速分析模式**：简化版快速分析报告，适合快速决策
- **批量分析功能**：支持多只股票同时分析，提升工作效率

### 📊 技术分析工具

- **三买三卖策略**：基于成交量、K线涨幅、均线形态、大盘配合、MACD 五维度评分系统
- **涨停回调策略**：缩量、回调幅度、地量、下影线、空间位置等八维度评估
- **智能股票筛选**：基于多维度指标的股票筛选和排序系统
- **回测系统**：策略历史回测与性能验证，结果持久化保存

### 📰 投研资讯中心

- **复盘模块**：大盘看板、资金流向、短线情绪全景监控
- **资讯模块**：12 赛道 108 个 RSS 源资讯雷达、个股公告、个股新闻
- **板块模块**：板块骨架、板块详情、板块资金流分析
- **记录模块**：研究记录本地管理，支持标签和搜索

### 💼 投资管理

- **自选股管理**：个人自选股收藏、分组管理和跟踪功能
- **个股详情页**：完整的个股信息展示和历史分析记录
- **模拟交易系统**：虚拟交易环境，验证投资策略效果
- **投资组合**：持仓管理与收益跟踪

### ⚙️ 系统管理

- **用户权限管理**：完整的用户认证、角色管理、操作日志系统
- **配置管理中心**：可视化的大模型配置、数据源管理、系统设置
- **多 LLM 提供商**：支持 OpenAI、Google、国内主流模型等多家供应商
- **多数据源同步**：统一的数据源管理，支持 Tushare、AkShare、BaoStock
- **缓存管理系统**：智能缓存策略，支持 MongoDB/Redis/文件多级缓存
- **实时通知系统**：SSE+WebSocket 双通道推送，实时跟踪分析进度
- **定时任务调度**：可视化任务管理与调度
- **报告导出**：支持 Markdown/Word/PDF 多格式专业报告导出

## 🏗️ 技术架构

| 层级 | 技术选型 |
|------|---------|
| **后端框架** | FastAPI + Uvicorn |
| **前端框架** | Vue 3 + Vite + Element Plus |
| **AI 框架** | LangGraph + LangChain |
| **数据库** | MongoDB + Redis |
| **消息队列** | Redis Queue |
| **部署方式** | Docker + Docker Compose |
| **数据源** | AkShare + Tushare + BaoStock + 东方财富 + 新浪财经 |

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
docker-compose up -d

# 访问前端
# http://localhost:8080
# 默认账号: admin / admin123
```

### 本地开发

```bash
# 后端
cd SanHuTradingAgents
pip install -r requirements.txt
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 前端
cd frontend
npm install
npm run dev
```

## 📁 项目结构

```
SanHuTradingAgents/
├── app/                      # 后端 FastAPI 应用
│   ├── services/             # 业务服务层
│   │   ├── stock_analyzer/   # 多智能体分析引擎
│   │   ├── analysis/         # 分析服务
│   │   ├── screening/        # 选股服务
│   │   ├── news_data_service.py    # 新闻数据
│   │   ├── newsradar.py      # 资讯雷达
│   │   ├── three_buys_three_sells_service.py  # 三买三卖
│   │   ├── limit_up_pullback_service.py      # 涨停回调
│   │   └── vibe_astock.py    # A股数据层
│   ├── routers/              # API 路由
│   └── models/               # 数据模型
├── frontend/                 # 前端 Vue 3 应用
│   ├── src/
│   │   ├── views/            # 页面组件
│   │   │   ├── Analysis/     # 分析页面
│   │   │   ├── Screening/    # 选股页面
│   │   │   ├── Vibe/         # 投研资讯（复盘/资讯/板块/记录）
│   │   │   ├── Reports/      # 报告页面
│   │   │   └── System/       # 系统管理
│   │   ├── components/       # 公共组件
│   │   └── api/              # API 封装
│   └── ...
├── docs/                     # 文档
├── docker-compose.yml        # Docker Compose 配置
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
