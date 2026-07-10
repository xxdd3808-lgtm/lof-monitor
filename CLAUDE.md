# 华宝油气 LOF (162411) 折溢价监控

## 项目用途

Streamlit 实时看板，估算华宝油气 LOF (162411) 的 IOPV（参考净值），算出场内折溢价率，辅助 QDII-LOF 套利/交易决策。本仓库为个人自用监控工具，无定时推送（如需推送可参考同账号下 `dingshi-renwu` 项目的 SCF + PushPlus 架构）。

## 架构

```
Streamlit Cloud（或本地 streamlit run）
  -> app.py 单文件
    -> yfinance: 场内价(162411.SZ) + XOP + USDCNH
    -> akshare:  净值历史(东财 fund_open_fund_info_em)
    -> 计算 IOPV + 折溢价 + 历史曲线
    -> plotly 渲染
```

`@st.cache_data(ttl=60)` 缓存 60 秒，侧边栏"手动刷新"按钮清缓存。

## 核心公式（2026-07-10 加固版）

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

**关键设计**：`xop_cum_ret` / `fx_cum_ret` 是累计涨幅（基线 = nav_date 之前最近的美股收盘日），**不是当日涨幅**。这解决了 QDII 净值滞后 1-2 日的时间窗口错配——原版只用 `fast_info` 的当日涨幅，nav_date 若是 T-2 就漏算 1 个交易日。

## 文件结构

| 文件 | 作用 |
|------|------|
| `app.py` | 全部逻辑（~320 行）：数据获取 + IOPV 计算 + Streamlit 渲染 |
| `requirements.txt` | streamlit / akshare / pandas / yfinance / plotly |

## 重要约束（务必遵守）

1. **基线选择用 `< nav_date`（严格小于）**：QDII 的 nav_date D 反映的是 US D-1 收盘。若用 `<=` 会误纳 US D 日收盘（该日收盘发生在 Beijing D 04:00，早于 D 日 15:00 的净值计算时点，但 D 日 NAV 不含 US D 日涨幅）。严格小于保证取到 US D-1。
2. **失败返回 None，不要回退 0.0**：0.0 会让 IOPV 静默算错（原版 bug）。所有数据源 try/except 后，IOPV 计算前用 `iopv_ok` 校验四要素全到位，否则显示 N/A + 列出缺失项。
3. **仓位系数 w 不进缓存函数参数**：`fetch_data()` 不接受 `position_ratio`，改 slider 不触发数据重取，只重算 IOPV。
4. **历史曲线用 settled NAV，不用估算 IOPV**：`premium = close_D / nav_D - 1`，label 明确写"基于当日公布净值"。与实时看板的 estimated IOPV 是不同口径，不要混。
5. **yfinance `history()` 返回空时必须重置变量为 None**：`Ticker.history()` 可能返回空 DataFrame，不能直接 `if lof_hist is not None` 判断，要先校验长度再赋值（app.py:141-150 有正例）。

## 已知限制（未处理，如需完善可参考）

1. **XOP 盘前/盘后语义不区分**：`history().iloc[-1]` 在美股盘中返回当日盘中价，此时 A 股已收盘，场内价与 XOP 时间点不对齐。北京时间白天（A 股盘中）取到昨夜美股收盘，正确；北京时间深夜美股盘中时存在错配。影响有限。
2. **0.94 默认值是经验估算**：slider 让用户可调，但未自动拉取基金季报实际仓位。如需精确，可接 akshare 季报接口自动填入。
3. **无节假日日历**：`now.weekday() >= 5` 只处理周末，A 股/美股法定节假日不判断，非交易时段提示可能误报。
4. **无定时推送**：纯被动看板。如需"折价超 3% 推送"，参考 `dingshi-renwu` 的 SCF + PushPlus 架构。
5. **无多 LOF 对比**：只监控 162411。华宝原油(162411)、南方原油(501018)、嘉实原油(160723) 等 QDII-LOF 可横向对比但未实现。

## 常用命令

```bash
# 本地运行
cd /Users/bt/lof-monitor
pip install -r requirements.txt
streamlit run app.py

# 部署（推荐 Streamlit Cloud，免费，连 GitHub 仓库自动部署）
# 访问 https://share.streamlit.io/ 连接 xxdd3808-lgtm/lof-monitor

# 查看远程最新
git log --oneline -10
```

## 变更历史

### 2026-07-10 IOPV 估算四项加固（commit `27ccf88`）

从第一性原理审视后修复 4 个问题：

1. **净值滞后对齐**（最严重）：原 `xop_pct = (fast_info.lastPrice - fast_info.previousClose) / previousClose` 只算当日涨幅。QDII 净值滞后 1-2 日，nav_date 若是 T-2，中间 1 个交易日的 XOP 涨幅被漏算，IOPV 系统性偏差。改为下载 3mo 日线，找 nav_date 之前最近美股收盘日为基线，累计涨幅覆盖全部交易日。

2. **错误降级透明化**：原各数据源失败时 `= 0.0`，IOPV 照算不误，用户看到的是看似正常但完全错误的折溢价率。改为返回 None，`iopv_ok` 校验四要素，不通过显示 N/A + 缺失项清单。debug_log 收进可折叠 expander。

3. **仓位系数可配置**：原 `0.94` 硬编码且无说明。改为侧边栏 slider 0.50-1.00，help 文本说明"经验估算 + 请结合季报"，IOPV 标签带当前仓位。改 slider 不触发数据重取。

4. **历史折溢价曲线**：原只有当前快照。新增 plotly 60 日曲线（close/nav-1），附 0%/均值参考线、最高/最低/均值/最新分位 4 个统计、20 日明细表。

另修复 `lof_hist` 在 yfinance 返回空 DataFrame 时未重置为 None 的 bug（原 `is not None` 误判）。

### 2026-03-19 改用 Yahoo Finance 获取 XOP（commit `303d7f1`）

XOP 数据源切到 yfinance，绕开国内封锁（海外部署场景）。

### 2026-03 初版

d5a5610 起逐步搭建，12 个 commit 演进到 2026-03-19 版本。
