# 华宝油气 LOF (162411) 折溢价监控

## 项目用途

华宝油气 LOF (162411) 折溢价监控与套利决策系统。从"发现机会 -> 判断可操作性 -> 量化真实收益 -> 预判底层方向 -> 历史回测验证"全链路辅助 QDII-LOF 套利/交易决策。

**核心结论**（2026-07-10 回测验证）：T+0 折价套利不赚钱（1.5% 赎回费 + 美股波动盲盒），真正机会在溢价端（已持有者卖出信号）。

## 架构

```
两部分独立运行：

1. Streamlit 看板（app.py）- 被动查看
   -> 5 个 tab：实时监控 / 多LOF对比 / 套利计算器 / 先行指标 / 历史回测
   -> yfinance: 场内价 + XOP + USDCNH + 原油期货 + 美股期货
   -> akshare:  净值历史(东财) + 场内价历史(Sina) + 申购赎回状态(东财移动API)
   -> plotly 渲染

2. 定时推送（notify.py + GitHub Actions）- 主动通知
   -> A 股交易时段每 30-60 分钟检查
   -> 折价/溢价超阈值、申购赎回状态变化 -> PushPlus 微信推送
   -> state.json 去重（每信号每天最多推 1 次）
```

## 核心公式

```
iopv_est = latest_nav × (1 + xop_cum_ret × w) × (1 + fx_cum_ret)
premium_rate = (current_price / iopv_est) − 1
```

| 变量 | 含义 | 来源 |
|------|------|------|
| `latest_nav` | nav_date 当日官方净值 | akshare 东财 |
| `xop_cum_ret` | nav_date 对应美股收盘日 -> 最新 的 XOP **累计**涨幅 | yfinance `XOP` 3mo 日线 |
| `fx_cum_ret` | 同上，USD/CNH 累计涨幅 | yfinance `USDCNH=X` |
| `w` | 仓位系数（股票占比，默认 0.94） | 侧边栏 slider |

**关键设计**：`xop_cum_ret` / `fx_cum_ret` 是累计涨幅（基线 = nav_date 之前最近的美股收盘日），**不是当日涨幅**。

## 文件结构

| 文件 | 作用 |
|------|------|
| `app.py` | Streamlit 看板，5 个 tab（~650 行） |
| `notify.py` | 定时推送脚本：检查折溢价 + 申购赎回状态 -> PushPlus |
| `config.json` | 推送监控列表 + 阈值 |
| `state.json` | 推送去重状态 |
| `.github/workflows/lof-check.yml` | GitHub Actions 定时触发 |
| `requirements.txt` | streamlit / akshare / pandas / yfinance / plotly / requests |
| `REPORT.html` | 项目优化总结报告（P1-P5 + 回测结果） |

## 5 个 Tab 功能

1. **实时监控**：IOPV 估算 + 折溢价 + 底层资产累计变动 + 快速套利可行性提示
2. **多LOF对比**：6 只 QDII-LOF 横向对比（华宝油气/广发石油/南方原油/嘉实原油/易方达原油/国泰大宗），含申购赎回状态 + 自动筛选可操作标的
3. **套利计算器**：各持有期档位收益测算 + 盈亏平衡美股跌幅 + 情景分析 + 结论判定
4. **先行指标**：WTI/Brent 原油期货 + 美股期货 + XOP + 美元指数，预判今晚美股方向
5. **历史回测**：遍历历史模拟买入+赎回，算真实收益/胜率/分布，验证策略有效性

## 重要约束（务必遵守）

1. **基线选择用 `< nav_date`（严格小于）**：QDII 的 nav_date D 反映 US D-1 收盘。
2. **失败返回 None，不要回退 0.0**：0.0 会让 IOPV 静默算错。`iopv_ok` 校验四要素全到位才算。
3. **仓位系数 w 不进缓存函数参数**：改 slider 不触发数据重取。
4. **历史曲线用 settled NAV，不用估算 IOPV**：`premium = close_D / nav_D - 1`，与实时 estimated IOPV 口径不同。
5. **yfinance `history()` 返回空时必须重置变量为 None**：先校验长度再赋值。
6. **回测数据源三重 fallback**：`ak.fund_etf_hist_sina()` -> 东财 K 线 API -> yfinance。Sina 源最稳。
7. **PUSHPLUS_TOKEN 不硬编码**：通过 GitHub Secrets 传入，仓库 PUBLIC。

## 回测结论（2026-07-10 验证）

数据范围 2025-06-05 ~ 2026-07-08（266 交易日）：

| 策略 | 笔数 | 胜率 | 平均收益 | 结论 |
|------|------|------|----------|------|
| 折价>3% + T+0赎回(1.5%) | 5 | 20% | -0.15% | ❌ 亏 |
| 折价>3% + 30天后赎回(0.5%) | 5 | 60% | +0.85% | ⚠️ 勉强 |
| 折价>5% + T+0赎回(1.5%) | 1 | 0% | -0.12% | ❌ 亏 |
| 折价>8% | 0 | - | - | 未出现 |

- 大折价极罕见：>5% 仅 1 次（13 个月），>8% 零次
- 最大溢价 +21.12%（溢价端才是机会）
- **T+0 折价套利期望收益为负，不建议做**

## 已知限制

1. **回测样本小**：13 个月仅 5 次 3%+ 折价，统计显著性有限。
2. **QDII 净值滞后**：回测用 nav_{D-1} 作基线有轻微前视偏差。
3. **无节假日日历**：只处理周末。
4. **申购赎回状态依赖第三方 API**：东财移动 API 可能变更。
5. **未实现自动对冲**：真无风险套利需做空 XOP/原油期货，普通人无此工具。

## 常用命令

```bash
# 本地运行看板
cd /Users/bt/lof-monitor
pip install -r requirements.txt
streamlit run app.py

# 手动触发推送检查（GitHub Actions）
gh workflow run lof-check.yml

# 查看推送日志
gh run list --workflow=lof-check.yml --limit 5

# 查看远程最新
git log --oneline -10
```

## 变更历史

### 2026-07-10 P1-P5 五项功能 + 回测验证

从"能不能真赚钱"出发，补全"判断可操作性"和"量化真实收益"两层：

- **P1 套利计算器**：各持有期档位净收益 + 盈亏平衡美股跌幅 + 情景分析
- **P2 先行指标**：WTI/Brent 原油 + 美股期货 + XOP + 美元指数
- **P3 历史回测**：遍历历史模拟买入+赎回，算真实收益/胜率。回测数据源三重 fallback
- **P4 多LOF对比**：6 只 QDII-LOF 横向对比 + 申购赎回状态 + 自动筛选
- **P5 通知推送**：notify.py + GitHub Actions + PushPlus，4 类信号 + state 去重

回测验证：T+0 折价套利不赚钱（1.5% 赎回费吃掉利润，5 笔交易胜率 20%）。真正机会在溢价端。

### 2026-07-10 IOPV 估算四项加固（commit `27ccf88`）

净值滞后对齐 + 错误降级透明化 + 仓位系数可配置 + 历史折溢价曲线。

### 2026-03-19 改用 Yahoo Finance 获取 XOP（commit `303d7f1`）

### 2026-03 初版

d5a5610 起逐步搭建。
