[text](../../../../../PokieTicker/README.md)# Biotech Quant Framework Design

日期：2026-04-20

## 1. 项目定位

基于 Cassandra（生物医药证据整理与报告生成系统）为主体，集成 PokieTicker 的 K 线+事件粒子渲染组件，构建一个专注于美股生物医药领域的金融量化框架。

核心能力：
- 事件驱动的 K 线可视化（覆盖 FDA、临床、合作、融资、专利、竞品全谱事件）
- K线异动 ↔ Cassandra报告 双向闭环
- 10年历史数据回测，多池验证 alpha 鲁棒性

## 2. 系统架构

```
┌─────────────────────────────────────────────────────┐
│  Cassandra Flask App (主体)                          │
│  ┌───────────────┐  ┌────────────────────────────┐  │
│  │ Jinja 模板    │  │ K线 Widget (React bundle)   │  │
│  │ 步骤条/报告   │  │ CandlestickChart + Particles│  │
│  └───────────────┘  └────────────────────────────┘  │
├─────────────────────────────────────────────────────┤
│  Cassandra 后端 (Flask + Socket.IO)                  │
│  ┌──────────┐ ┌──────────────┐ ┌────────────────┐  │
│  │harvester │→│extension_hand│→│    writer       │  │
│  │          │ │off (K线数据流)│ │                 │  │
│  └──────────┘ └──────────────┘ └────────────────┘  │
├─────────────────────────────────────────────────────┤
│  数据层                                              │
│  ┌────────────┐ ┌─────────────┐ ┌───────────────┐  │
│  │事件采集    │ │OHLC行情     │ │回测引擎        │  │
│  │(FDA/临床等)│ │(yfinance)   │ │(多池验证)      │  │
│  └────────────┘ └─────────────┘ └───────────────┘  │
├─────────────────────────────────────────────────────┤
│  闭环逻辑                                            │
│  K线异动检测 ──→ 触发Cassandra报告                    │
│  报告催化剂识别 ──→ 反馈为K线事件标注 + 交易信号       │
└─────────────────────────────────────────────────────┘
```

## 3. K线组件集成方案

### 3.1 提取文件

从 PokieTicker 提取：
- `frontend/src/components/CandlestickChart.tsx` — 核心渲染逻辑
- `frontend/package.json` — 依赖版本参考
- `frontend/src/App.tsx` — 状态管理参考
- `backend/ml/features.py` — 特征工程逻辑（回测复用）

### 3.2 嵌入方式

React 组件编译为独立 UMD bundle（Vite library mode），通过全局 API 嵌入 Cassandra Jinja 模板：

```js
window.PokieChart = {
  render(container, { ohlcData, events, onEventClick, onAnomalyDetected })
}
```

模板嵌入：
```html
<div id="kline-container"></div>
<script src="/static/vendor/pokie-chart.umd.js"></script>
<script>
  PokieChart.render(document.getElementById('kline-container'), {
    ohlcData: {{ ohlc_json | tojson }},
    events: {{ events_json | tojson }},
    onEventClick: (evt) => socket.emit('request_report', evt),
    onAnomalyDetected: (signal) => socket.emit('anomaly_signal', signal)
  });
</script>
```

### 3.3 事件数据结构

```ts
interface BiotechEvent {
  id: string;
  date: string;
  type: 'fda_decision' | 'clinical_readout' | 'partnership' | 'financing' | 'patent' | 'competitor';
  priority: 1 | 2 | 3;
  ticker: string;
  disease_area: string;
  catalyst: string;
  sentiment: 'positive' | 'negative' | 'neutral';
  price_impact?: number;
}
```

事件优先级：
- P1：PDUFA 决策日、Phase 3 关键读出、CRL
- P2：Phase 2 数据、合作交易、AdCom 会议
- P3：融资、专利、早期临床、竞品动态

## 4. 双向闭环逻辑

### 4.1 正向链路（K线 → 报告）

```
K线异动检测（放量/跳空/粒子聚集）
  ↓ socket.emit('anomaly_signal', { ticker, date, type, magnitude })
Flask 接收 → 构造 user_query → 调用 Cassandra 主链
  ↓ harvester → extension_handoff（注入行情上下文）→ writer
生成报告（解释异动原因）
  ↓ socket.emit('report_ready', { report_path, key_catalysts })
K线组件接收 → 添加报告标注粒子
```

### 4.2 反向链路（报告 → 信号）

```
Cassandra 报告生成完毕 → writer 输出提取结构化催化剂
  ↓ 识别未来关键日期（PDUFA、数据读出预期）
写入 extension_payloads
  ↓ socket.emit('upcoming_catalysts', [...])
K线组件标注未来事件（虚线标记）
  ↓ 回测引擎同步接收作为交易信号输入
```

### 4.3 触发条件

- 异动检测：日涨跌幅 > 5%、成交量 > 20日均量2倍、单日事件粒子 ≥ 3个
- 频率限制：同一 ticker 24小时内最多触发1次报告
- 催化剂信号有效期：事件日期前后各5个交易日

## 5. 数据源

全部免费方案：

| 事件类型 | 数据源 | 采集方式 |
|---------|--------|---------|
| OHLC 行情 | yfinance | Python API，10年日线 |
| FDA 决策/PDUFA | FDA.gov OpenFDA API | 结构化 API，按日期拉取 |
| 临床试验进展 | ClinicalTrials.gov API | 按 NCT ID 追踪状态变更 |
| 临床数据读出 | SEC 8-K filings (EDGAR) | 关键词过滤 + NLP 分类 |
| 合作/授权交易 | SEC 8-K + PR Newswire RSS | 关键词匹配 |
| 融资事件 | SEC S-1/424B filings | 结构化提取 |
| 专利到期 | FDA Orange Book | 定期快照对比 |
| 竞品数据 | ClinicalTrials.gov 交叉查询 | 按适应症聚合 |

采集节奏：
- 生产模式：每日增量拉取
- 回测模式：批量历史拉取，按日期对齐到交易日

## 6. 回测引擎

### 6.1 时间框架

Walk-forward + 市场周期分层：
- 训练窗口：滚动5年
- 验证窗口：滚动1年
- 测试窗口：滚动1年
- 示例：2014-2018训练 → 2019验证 → 2020测试 → 滚动一年重复

额外分层：按 VIX 水平划分低波动/高波动环境，分别统计 alpha。

### 6.2 多池验证矩阵

| 池子 | 标的数 | 目的 |
|------|--------|------|
| 核心池 | 5-15只 | 大型 biotech，验证基础逻辑 |
| 中等池 | 30-50只 | XBI/IBB 成分股，验证策略容量 |
| 广覆盖池 | 100+只 | 有活跃管线的公司，验证泛化能力 |
| 动态池 | 变动 | 按未来30天催化剂事件筛选，验证事件择时 |

### 6.3 三层验证指标

**层1 — 事件可预测性：**
- 事件前后异常收益率（CAR）统计显著性
- 各事件类型的信息系数（IC）
- 事件窗口：[-5, +10] 交易日

**层2 — 报告信号有效性：**
- Cassandra 报告看多/看空信号 vs 后续收益相关性
- 信号胜率、盈亏比
- 信号衰减曲线（信号发出后多少天内有效）

**层3 — 端到端策略：**
- 年化收益、Sharpe ratio、最大回撤
- 相对 XBI 的超额收益
- 换手率、交易成本敏感性分析

### 6.4 策略框架

```
信号生成 → 仓位计算 → 风控过滤 → 执行
```

- 信号：事件评分 × Cassandra 报告置信度
- 仓位：等权 or 按信号强度加权，单只上限 20%
- 风控：单日止损 -8%，组合回撤 -15% 减仓50%
- 执行假设：T+1 开盘价成交，滑点 0.1%，佣金忽略

### 6.5 回测数据存储

- OHLC 行情：Parquet 文件，按 ticker 分文件存储（`data/ohlc/{ticker}.parquet`）
- 事件数据：SQLite 单库（`data/events.db`），表按事件类型分
- 回测结果：JSON + Parquet（每次回测运行生成一个结果目录）
- 选择 Parquet 原因：列式存储适合时间序列查询，pandas 原生支持，体积小

## 7. Cassandra 中的目标结构

```
cassandra/
├── src/
│   ├── graph/              # 现有编排层
│   ├── agents/             # 现有协调层
│   ├── services/           # 现有服务层
│   └── kline/              # 新增：K线模块
│       ├── chart/
│       │   ├── CandlestickChart.tsx
│       │   ├── types.ts
│       │   └── index.tsx
│       ├── build/
│       │   ├── pokie-chart.umd.js
│       │   └── pokie-chart.css
│       ├── package.json
│       └── vite.config.ts
├── src/backtest/           # 新增：回测引擎
│   ├── data/               # 数据获取
│   ├── events/             # 事件采集与分类
│   ├── signals/            # 信号生成
│   ├── strategy/           # 策略执行与仓位管理
│   ├── metrics/            # 绩效统计
│   └── runner.py           # 回测主入口
├── templates/
│   └── kline.html
├── static/vendor/
└── app.py
```

## 8. 合并步骤

1. 在 Cassandra 中创建 `src/kline/chart/` 目录
2. 复制 PokieTicker 的 `CandlestickChart.tsx`
3. 创建 `types.ts`（BiotechEvent 接口）和 `index.tsx`（入口封装）
4. 创建独立 `package.json` 和 `vite.config.ts`（library mode）
5. `cd src/kline && npm install && npm run build`
6. 将 build 输出复制到 `static/vendor/`
7. 在 `templates/kline.html` 中引入 bundle
8. 在 `app.py` 中添加 Socket.IO 事件路由
9. 在 `extension_handoff` 节点中接入行情数据流
10. 创建 `src/backtest/` 目录结构，实现回测引擎
