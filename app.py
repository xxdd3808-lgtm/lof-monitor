import streamlit as st
import akshare as ak
import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime, timedelta
import pytz
import numpy as np

# --- 页面基础设置 ---
st.set_page_config(page_title="华宝油气(162411)折溢价监控", page_icon="🛢️", layout="wide")
st.title("🛢️ 华宝油气 LOF (162411) 折溢价监控与套利决策")
st.caption("从发现机会 → 判断可操作性 → 量化真实收益 → 预判底层方向 → 历史回测验证")

tz = pytz.timezone('Asia/Shanghai')
now = datetime.now(tz)

# --- 侧边栏 ---
with st.sidebar:
    st.header("⚙️ 控制面板")
    if st.button("🔄 手动刷新数据"):
        st.cache_data.clear()
        st.rerun()

    st.markdown("---")
    st.subheader("模型参数")
    position_ratio = st.slider(
        "股票仓位系数 w",
        min_value=0.50, max_value=1.00, value=0.94, step=0.01,
        help=(
            "基金股票仓位占比，剩余 (1-w) 为现金。"
            "IOPV ≈ NAV × (1 + XOP累计涨幅 × w) × (1 + 汇率累计涨幅)。"
            "0.94 = 94% 股票 + 6% 现金，依据为暂停申购期间现金拖累的经验估算，"
            "请结合最新季报披露的实际股票仓位调整。"
        ),
    )
    st.caption(f"当前：{position_ratio*100:.0f}% 股票 + {(1-position_ratio)*100:.0f}% 现金")

    st.markdown("---")
    st.subheader("费用参数（套利计算器用）")
    commission_rate = st.number_input("买入佣金率", value=0.0001, format="%.5f", help="券商佣金，万一=0.0001")
    st.caption("赎回费按持有期阶梯：<7天 1.5%，7-30天 0.75%，30天-1年 0.5%，>1年 0%")

    st.markdown("---")
    st.subheader("模型说明")
    st.write("**IOPV 估算公式**：")
    st.write("IOPV = NAV(nav_date) × (1 + r_XOP × w) × (1 + r_FX)")
    st.caption(
        "r_XOP / r_FX 为 nav_date 对应美股收盘日至今的累计涨幅（非仅当日涨幅），"
        "解决 QDII 净值滞后 1-2 日的时间窗口错配。"
    )
    st.write("🌐 数据源：雅虎财经（XOP/汇率/原油/期货）+ 东方财富（净值/场内价）")

# --- 交易时段提示 ---
if now.hour < 9 or now.hour >= 15 or now.weekday() >= 5:
    st.warning("⏰ 当前非 A 股交易时段，场内价格为最近交易日收盘价。")


# ========== 通用工具 ==========
def safe_float(val, default=None):
    try:
        v = float(val)
        if np.isnan(v) or np.isinf(v):
            return default
        return v
    except (TypeError, ValueError):
        return default


# ========== 数据获取：华宝油气主数据 ==========
@st.cache_data(ttl=60, show_spinner=False)
def fetch_main_data():
    debug_log = []

    current_price = None
    try:
        price_raw = yf.Ticker("162411.SZ").fast_info['lastPrice']
        if price_raw and float(price_raw) > 0:
            current_price = float(price_raw)
    except Exception as e:
        debug_log.append(f"场内价格(雅虎)失败: {e}")

    latest_nav = None
    nav_date = None
    nav_data = None
    try:
        nav_data = ak.fund_open_fund_info_em(symbol="162411", indicator="单位净值走势")
        latest = nav_data.iloc[-1]
        latest_nav = float(latest['单位净值'])
        nav_date = str(latest['净值日期'])[:10]
    except Exception as e:
        debug_log.append(f"官方净值(东财)失败: {e}")

    xop_cum_ret = None
    xop_baseline = None
    xop_current = None
    xop_baseline_date = None
    xop_current_date = None
    try:
        xop_hist = yf.Ticker("XOP").history(period="3mo")
        if xop_hist is None or len(xop_hist) == 0:
            raise ValueError("XOP 历史为空")
        xop_hist['date_str'] = pd.to_datetime(xop_hist.index).strftime('%Y-%m-%d')
        xop_current = float(xop_hist['Close'].iloc[-1])
        xop_current_date = xop_hist['date_str'].iloc[-1]
        if nav_date:
            prior = xop_hist[xop_hist['date_str'] < nav_date]
            if len(prior) > 0:
                xop_baseline = float(prior['Close'].iloc[-1])
                xop_baseline_date = prior['date_str'].iloc[-1]
            else:
                xop_baseline = float(xop_hist['Close'].iloc[0])
                xop_baseline_date = xop_hist['date_str'].iloc[0]
                debug_log.append(f"XOP: 无 {nav_date} 之前的数据，退回用最早 {xop_baseline_date} 作基线")
            if xop_baseline and xop_baseline > 0:
                xop_cum_ret = (xop_current - xop_baseline) / xop_baseline
        else:
            debug_log.append("XOP: 缺少 nav_date，无法计算累计涨幅")
    except Exception as e:
        debug_log.append(f"XOP 数据失败: {e}")

    fx_cum_ret = None
    fx_baseline = None
    fx_current = None
    fx_baseline_date = None
    fx_current_date = None
    try:
        fx_hist = yf.Ticker("USDCNH=X").history(period="3mo")
        if fx_hist is None or len(fx_hist) == 0:
            raise ValueError("汇率历史为空")
        fx_hist['date_str'] = pd.to_datetime(fx_hist.index).strftime('%Y-%m-%d')
        fx_current = float(fx_hist['Close'].iloc[-1])
        fx_current_date = fx_hist['date_str'].iloc[-1]
        if nav_date:
            prior = fx_hist[fx_hist['date_str'] < nav_date]
            if len(prior) > 0:
                fx_baseline = float(prior['Close'].iloc[-1])
                fx_baseline_date = prior['date_str'].iloc[-1]
            else:
                fx_baseline = float(fx_hist['Close'].iloc[0])
                fx_baseline_date = fx_hist['date_str'].iloc[0]
                debug_log.append(f"FX: 无 {nav_date} 之前的数据，退回用最早 {fx_baseline_date} 作基线")
            if fx_baseline and fx_baseline > 0:
                fx_cum_ret = (fx_current - fx_baseline) / fx_baseline
        else:
            debug_log.append("FX: 缺少 nav_date，无法计算累计涨幅")
    except Exception as e:
        debug_log.append(f"汇率数据失败: {e}")

    return {
        'current_price': current_price,
        'latest_nav': latest_nav,
        'nav_date': nav_date,
        'nav_data': nav_data,
        'xop_cum_ret': xop_cum_ret,
        'xop_baseline': xop_baseline,
        'xop_current': xop_current,
        'xop_baseline_date': xop_baseline_date,
        'xop_current_date': xop_current_date,
        'fx_cum_ret': fx_cum_ret,
        'fx_baseline': fx_baseline,
        'fx_current': fx_current,
        'fx_baseline_date': fx_baseline_date,
        'fx_current_date': fx_current_date,
        'debug_log': debug_log,
    }


# ========== 数据获取：多 LOF 对比（P4）==========
LOF_LIST = [
    {"code": "162411", "name": "华宝油气", "underlying": "SPSIOP 油气股", "category": "油气股"},
    {"code": "162719", "name": "广发石油", "underlying": "道琼斯石油", "category": "油气股"},
    {"code": "501018", "name": "南方原油", "underlying": "WTI 原油", "category": "原油"},
    {"code": "160723", "name": "嘉实原油", "underlying": "布伦特原油", "category": "原油"},
    {"code": "161129", "name": "易方达原油", "underlying": "WTI 原油", "category": "原油"},
    {"code": "160216", "name": "国泰大宗", "underlying": "大宗商品", "category": "商品"},
]


@st.cache_data(ttl=300, show_spinner=False)
def fetch_lof_compare():
    """获取多只 QDII-LOF 的场内价、净值、折溢价、申购赎回状态"""
    import requests
    results = []
    for lof in LOF_LIST:
        code = lof["code"]
        row = {**lof, "price": None, "nav": None, "nav_date": None,
               "premium": None, "buy_status": "未知", "redeem_status": "未知"}
        # 场内价 + 净值
        try:
            nav_df = ak.fund_open_fund_info_em(symbol=code, indicator="单位净值走势")
            if nav_df is not None and len(nav_df) > 0:
                latest = nav_df.iloc[-1]
                row["nav"] = float(latest['单位净值'])
                row["nav_date"] = str(latest['净值日期'])[:10]
        except Exception:
            pass
        try:
            spot = yf.Ticker(f"{code}.SZ").fast_info
            p = spot.get('lastPrice') if spot else None
            if p and float(p) > 0:
                row["price"] = float(p)
        except Exception:
            pass
        # 申购赎回状态（东财移动 API）
        try:
            url = "https://fundmobapi.eastmoney.com/FundMNewApi/FundMNNBasicInformation"
            params = {"FundCode": code, "deviceid": "Wap", "plat": "Wap",
                      "product": "EFund", "version": "2.0.0"}
            r = requests.get(url, params=params, timeout=8,
                             headers={"User-Agent": "Mozilla/5.0"})
            data = r.json()
            info = data.get("Expansion", {})
            # FundBGRO: 申购状态, FundRGRO: 赎回状态
            bgro = info.get("FundBGRO", "")
            rgro = info.get("FundRGRO", "")
            if bgro:
                row["buy_status"] = "开放申购" if "正常" in str(bgro) else f"{bgro}"
            if rgro:
                row["redeem_status"] = "开放赎回" if "正常" in str(rgro) else f"{rgro}"
        except Exception:
            pass
        # 折溢价
        if row["price"] and row["nav"] and row["nav"] > 0:
            row["premium"] = row["price"] / row["nav"] - 1
        results.append(row)
    return results


# ========== 数据获取：先行指标（P2）==========
INDICATOR_TICKERS = {
    "WTI 原油期货 (CL=F)": "CL=F",
    "Brent 原油期货 (BZ=F)": "BZ=F",
    "标普500期货 (ES=F)": "ES=F",
    "纳指期货 (NQ=F)": "NQ=F",
    "XOP 油气ETF": "XOP",
    "美元指数 (DXY)": "DX-Y.NYB",
}


@st.cache_data(ttl=60, show_spinner=False)
def fetch_indicators():
    results = {}
    for name, ticker in INDICATOR_TICKERS.items():
        entry = {"name": name, "last": None, "prev": None, "chg_pct": None, "err": None}
        try:
            t = yf.Ticker(ticker)
            fi = t.fast_info
            last = safe_float(fi.get('lastPrice'))
            prev = safe_float(fi.get('previousClose'))
            if last and prev and prev > 0:
                entry["last"] = last
                entry["prev"] = prev
                entry["chg_pct"] = (last - prev) / prev
        except Exception as e:
            entry["err"] = str(e)
        results[name] = entry
    return results


# ========== 数据获取：历史回测（P3）==========
@st.cache_data(ttl=600, show_spinner=False)
def fetch_backtest_data(days=400):
    """获取华宝油气历史净值 + 场内收盘价，用于回测"""
    debug_log = []
    end = datetime.now().strftime('%Y-%m-%d')
    start = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')

    # 净值历史
    nav_df = None
    try:
        nav_df = ak.fund_open_fund_info_em(symbol="162411", indicator="单位净值走势")
        nav_df = nav_df[['净值日期', '单位净值']].copy()
        nav_df['净值日期'] = pd.to_datetime(nav_df['净值日期'])
        nav_df = nav_df.rename(columns={'净值日期': 'date', '单位净值': 'nav'})
        nav_df['date_str'] = nav_df['date'].dt.strftime('%Y-%m-%d')
        nav_df = nav_df[nav_df['date_str'] >= start].reset_index(drop=True)
    except Exception as e:
        debug_log.append(f"净值历史失败: {e}")

    # 场内收盘价历史（优先 Sina 源，实测最稳；东财 API 和 yfinance 作 fallback）
    price_df = None
    # 源1: akshare Sina
    try:
        ph = ak.fund_etf_hist_sina(symbol="sz162411")
        ph = ph[['date', 'close']].copy()
        ph['date_str'] = ph['date'].astype(str).str[:10]
        ph['close'] = ph['close'].astype(float)
        ph = ph[ph['date_str'] >= start][['date_str', 'close']].reset_index(drop=True)
        if len(ph) > 0:
            price_df = ph
    except Exception as e:
        debug_log.append(f"场内价历史(Sina)失败: {e}")
    # 源2: 东财 K 线 API
    if price_df is None:
        try:
            import requests
            url = "http://push2his.eastmoney.com/api/qt/stock/kline/get"
            params = {
                "secid": "0.162411", "klt": "101", "fqt": "0",
                "beg": start.replace('-', ''), "end": end.replace('-', ''),
                "fields1": "f1,f2,f3", "fields2": "f51,f52,f53,f54,f55,f56,f57",
                "ut": "fa5fd1943c7b386f172d6893dbfba10b",
            }
            r = requests.get(url, params=params, timeout=15,
                             headers={"User-Agent": "Mozilla/5.0"})
            klines = r.json().get("data", {}).get("klines", [])
            if klines:
                rows = [{"date_str": line.split(",")[0], "close": float(line.split(",")[2])}
                        for line in klines]
                price_df = pd.DataFrame(rows)
        except Exception as e:
            debug_log.append(f"场内价历史(东财API)失败: {e}")
    # 源3: yfinance
    if price_df is None:
        try:
            yh = yf.Ticker("162411.SZ").history(period="1y")
            yh = yh.reset_index()[['Date', 'Close']].copy()
            yh['Date'] = pd.to_datetime(yh['Date']).dt.tz_localize(None)
            yh = yh.rename(columns={'Date': 'date', 'Close': 'close'})
            yh['date_str'] = yh['date'].dt.strftime('%Y-%m-%d')
            price_df = yh[['date_str', 'close']]
        except Exception as e2:
            debug_log.append(f"场内价历史(yfinance)失败: {e2}")

    if nav_df is None or price_df is None:
        return None, debug_log

    merged = pd.merge(nav_df, price_df[['date_str', 'close']], on='date_str', how='inner')
    merged = merged.sort_values('date_str').reset_index(drop=True)
    return merged, debug_log


def run_backtest(merged, threshold_pct, redeem_fee, commission, hold_days_label):
    """执行回测：折价超过阈值时买入+赎回"""
    df = merged.copy()
    df['nav_prev'] = df['nav'].shift(1)  # 前一日净值（作为决策时已知基线）
    df = df.dropna(subset=['nav_prev'])
    df['signal'] = df['close'] / df['nav_prev'] - 1  # 决策时看到的折价
    df['redeem_nav'] = df['nav']  # 赎回净值（当日实际净值）
    df['gross_ret'] = df['redeem_nav'] / df['close'] - 1
    df['net_ret'] = df['gross_ret'] - redeem_fee - commission

    threshold = -threshold_pct / 100.0  # threshold_pct 是正数，如 3 表示折价 3%
    trades = df[df['signal'] <= threshold].copy()
    trades = trades[['date_str', 'close', 'nav_prev', 'signal', 'redeem_nav', 'gross_ret', 'net_ret']]

    stats = {
        'total_trades': len(trades),
        'win_count': int((trades['net_ret'] > 0).sum()) if len(trades) > 0 else 0,
        'win_rate': float((trades['net_ret'] > 0).mean()) if len(trades) > 0 else 0.0,
        'avg_ret': float(trades['net_ret'].mean()) if len(trades) > 0 else 0.0,
        'median_ret': float(trades['net_ret'].median()) if len(trades) > 0 else 0.0,
        'max_loss': float(trades['net_ret'].min()) if len(trades) > 0 else 0.0,
        'max_gain': float(trades['net_ret'].max()) if len(trades) > 0 else 0.0,
        'cum_ret': float(trades['net_ret'].sum()) if len(trades) > 0 else 0.0,
        'threshold': threshold_pct,
        'redeem_fee': redeem_fee,
        'hold_days_label': hold_days_label,
    }
    return trades, stats


# ========== 主数据加载（Tab 1 用）==========
data = fetch_main_data()
debug_log = data['debug_log']

# ========== Tabs ==========
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "📊 实时监控", "📋 多LOF对比", "🧮 套利计算器", "🌐 先行指标", "🔬 历史回测"
])


# ---------- Tab 1: 实时监控 ----------
with tab1:
    if debug_log:
        with st.expander(f"⚠️ 数据源异常（{len(debug_log)} 项）", expanded=False):
            for err in debug_log:
                st.write(f"- {err}")

    current_price = data['current_price']
    latest_nav = data['latest_nav']
    nav_date = data['nav_date']
    xop_cum_ret = data['xop_cum_ret']
    fx_cum_ret = data['fx_cum_ret']

    iopv_ok = all([
        current_price and current_price > 0,
        latest_nav and latest_nav > 0,
        xop_cum_ret is not None,
        fx_cum_ret is not None,
    ])

    st.subheader("核心指标")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("场内实时价格", f"¥{current_price:.4f}" if current_price else "N/A")
    col2.metric(f"官方净值 ({nav_date or 'N/A'})", f"¥{latest_nav:.4f}" if latest_nav else "N/A")

    if iopv_ok:
        iopv_est = latest_nav * (1 + xop_cum_ret * position_ratio) * (1 + fx_cum_ret)
        premium_rate = (current_price / iopv_est) - 1
        col3.metric(f"IOPV 估算 (仓位 {position_ratio:.0%})", f"¥{iopv_est:.4f}")
        if premium_rate < 0:
            col4.metric("实时折溢价率", f"{premium_rate*100:+.2f}%", "折价", delta_color="inverse")
        else:
            col4.metric("实时折溢价率", f"{premium_rate*100:+.2f}%", "溢价", delta_color="normal")

        st.markdown("---")
        st.subheader("底层资产累计变动（nav_date 对应美股日 -> 最新）")
        col_a, col_b = st.columns(2)
        col_a.metric(
            "XOP 累计涨幅", f"{xop_cum_ret*100:+.2f}%",
            f"{data['xop_baseline_date']} ¥{data['xop_baseline']:.2f} -> {data['xop_current_date']} ¥{data['xop_current']:.2f}",
        )
        col_b.metric(
            "USD/CNH 累计涨幅", f"{fx_cum_ret*100:+.2f}%",
            f"{data['fx_baseline_date']} {data['fx_baseline']:.4f} -> {data['fx_current_date']} {data['fx_current']:.4f}",
        )

        with st.expander("🔬 IOPV 估算拆解"):
            st.write(f"**NAV 基准**（{nav_date}）：¥{latest_nav:.4f}")
            st.write(f"**XOP 累计涨幅**：{xop_cum_ret*100:+.2f}%（{data['xop_baseline_date']} ¥{data['xop_baseline']:.2f} -> {data['xop_current_date']} ¥{data['xop_current']:.2f}）")
            st.write(f"**仓位系数 w**：{position_ratio:.2f}（股票 {position_ratio*100:.0f}% + 现金 {(1-position_ratio)*100:.0f}%）")
            st.write(f"**汇率累计涨幅**：{fx_cum_ret*100:+.2f}%（{data['fx_baseline_date']} {data['fx_baseline']:.4f} -> {data['fx_current_date']} {data['fx_current']:.4f}）")
            st.write(f"**公式**：IOPV = {latest_nav:.4f} × (1 + ({xop_cum_ret:.4f}) × {position_ratio}) × (1 + {fx_cum_ret:.4f}) = ¥{iopv_est:.4f}")
            st.write(f"**折溢价**：(¥{current_price:.4f} / ¥{iopv_est:.4f}) − 1 = {premium_rate*100:+.2f}%")

        # 快速套利可行性提示
        st.markdown("---")
        st.subheader("⚡ 快速套利可行性")
        if premium_rate > 0:
            st.warning(f"当前 **溢价 {premium_rate*100:+.2f}%**。溢价套利=申购→卖出，但华宝油气常年暂停申购，通道基本堵死。")
        else:
            discount_abs = abs(premium_rate)
            # 盈亏平衡美股跌幅（T+0 赎回费 1.5%）
            breakeven = (1 - (1 + 0.015 + commission_rate) * (1 + premium_rate)) / position_ratio
            st.info(
                f"当前 **折价 {premium_rate*100:+.2f}%**。折价套利=买入→赎回。\n\n"
                f"- T+0 赎回（持有<7天，费率1.5%）：盈亏平衡美股跌幅 **{breakeven*100:.2f}%**\n"
                f"- 美股当晚跌幅超过 {breakeven*100:.2f}% 即亏损\n"
                f"- 折扣 {'够大，值得关注' if discount_abs > 0.05 else '偏小，美股随便一波动就吃掉利润'}\n\n"
                f"👉 去「套利计算器」tab 看详细收益测算"
            )
    else:
        col3.metric("IOPV 估算", "N/A")
        col4.metric("实时折溢价率", "N/A")
        st.error("❌ 核心数据缺失，无法计算 IOPV / 折溢价")


# ---------- Tab 2: 多 LOF 对比（P4） ----------
with tab2:
    st.subheader("QDII-LOF 折溢价横向对比")
    st.caption("同为海外资产 LOF，折溢价和申购赎回状态不同。溢价套利找「开放申购+高溢价」，折价套利找「开放赎回+大折价」。")

    lof_data = fetch_lof_compare()
    if lof_data:
        rows = []
        for r in lof_data:
            premium_str = f"{r['premium']*100:+.2f}%" if r['premium'] is not None else "N/A"
            rows.append({
                "代码": r['code'],
                "名称": r['name'],
                "底层": r['underlying'],
                "场内价": f"¥{r['price']:.4f}" if r['price'] else "N/A",
                "净值": f"¥{r['nav']:.4f}" if r['nav'] else "N/A",
                "净值日期": r['nav_date'] or "N/A",
                "折溢价": premium_str,
                "申购状态": r['buy_status'],
                "赎回状态": r['redeem_status'],
            })
        df_show = pd.DataFrame(rows)
        st.dataframe(df_show, use_container_width=True, hide_index=True)

        st.markdown("---")
        st.subheader("💡 可操作标的筛选")
        # 开放赎回 + 折价
        discount_open = [r for r in lof_data
                         if r['premium'] is not None and r['premium'] < -0.01
                         and "开放" in r['redeem_status']]
        premium_open = [r for r in lof_data
                        if r['premium'] is not None and r['premium'] > 0.01
                        and "开放" in r['buy_status']]

        col_a, col_b = st.columns(2)
        with col_a:
            st.write("**折价套利机会**（开放赎回 + 折价 > 1%）")
            if discount_open:
                for r in sorted(discount_open, key=lambda x: x['premium']):
                    st.write(f"- {r['name']}({r['code']}) 折价 {r['premium']*100:.2f}% | 底层：{r['underlying']}")
            else:
                st.write("（暂无）")
        with col_b:
            st.write("**溢价套利机会**（开放申购 + 溢价 > 1%）")
            if premium_open:
                for r in sorted(premium_open, key=lambda x: -x['premium']):
                    st.write(f"- {r['name']}({r['code']}) 溢价 {r['premium']*100:+.2f}% | 底层：{r['underlying']}")
            else:
                st.write("（暂无，QDII 普遍暂停申购）")

        st.caption("注：申购赎回状态来自东方财富移动 API，可能滞后，以基金公司公告为准。")


# ---------- Tab 3: 套利计算器（P1） ----------
with tab3:
    st.subheader("折价套利收益计算器")
    st.caption("买入→赎回的真实收益 = 折价 - 赎回费 - 佣金 - 美股当晚波动风险")

    current_price = data['current_price']
    latest_nav = data['latest_nav']
    xop_cum_ret = data['xop_cum_ret']
    fx_cum_ret = data['fx_cum_ret']

    if not (current_price and latest_nav and xop_cum_ret is not None and fx_cum_ret is not None):
        st.warning("核心数据缺失，无法计算。请先在「实时监控」tab 确认数据正常。")
    else:
        iopv_est = latest_nav * (1 + xop_cum_ret * position_ratio) * (1 + fx_cum_ret)
        premium_rate = (current_price / iopv_est) - 1

        col_a, col_b = st.columns(2)
        with col_a:
            st.metric("当前折价率", f"{premium_rate*100:+.2f}%")
        with col_b:
            st.metric("IOPV 估算", f"¥{iopv_est:.4f}")

        st.markdown("---")
        st.subheader("各持有期档位收益测算")
        st.caption("假设美股当晚持平（r_XOP=0, r_FX=0），纯折价收敛收益")

        fee_tiers = [
            ("T+0 赎回（持有<7天）", 0.015, "1.5% 惩罚性费率"),
            ("持有 7-30 天", 0.0075, "0.75%"),
            ("持有 30-365 天", 0.005, "0.5%"),
            ("持有 > 1 年", 0.0, "0%"),
        ]

        calc_rows = []
        for label, fee, fee_desc in fee_tiers:
            if premium_rate < 0:  # 折价
                gross = -premium_rate  # 折价率绝对值 = 毛收益
                net = gross - fee - commission_rate
                # 盈亏平衡美股跌幅：net = 0 时美股跌幅
                # (1 - x*w) / (1+premium) - 1 - fee - commission = 0
                # (1 - x*w) = (1 + fee + commission) * (1 + premium)
                # x = [1 - (1+fee+commission)*(1+premium)] / w
                if position_ratio > 0:
                    breakeven = (1 - (1 + fee + commission_rate) * (1 + premium_rate)) / position_ratio
                else:
                    breakeven = 0
                calc_rows.append({
                    "持有期": label,
                    "赎回费": fee_desc,
                    "毛收益(美股持平)": f"{gross*100:.2f}%",
                    "净收益(美股持平)": f"{net*100:+.2f}%",
                    "盈亏平衡美股跌幅": f"{breakeven*100:.2f}%",
                    "评价": "值得做" if net > 0.02 else ("勉强" if net > 0 else "亏"),
                })
            else:  # 溢价，不适合买入赎回
                calc_rows.append({
                    "持有期": label,
                    "赎回费": fee_desc,
                    "毛收益(美股持平)": f"{-premium_rate*100:.2f}%",
                    "净收益(美股持平)": "N/A（溢价）",
                    "盈亏平衡美股跌幅": "N/A",
                    "评价": "溢价不适合买入赎回",
                })

        st.dataframe(pd.DataFrame(calc_rows), use_container_width=True, hide_index=True)

        st.markdown("---")
        st.subheader("情景分析：美股当晚涨跌 vs 实际收益")
        st.caption("赎回净值 = IOPV × (1 + 美股涨幅 × w) × (1 + 汇率涨幅)。此处假设汇率持平。")

        if premium_rate < 0:
            us_scenarios = [-0.08, -0.05, -0.03, -0.02, -0.01, 0, 0.01, 0.03, 0.05]
            scenario_rows = []
            for us_ret in us_scenarios:
                redeem_nav = iopv_est * (1 + us_ret * position_ratio)
                gross = redeem_nav / current_price - 1
                net_t0 = gross - 0.015 - commission_rate
                net_7d = gross - 0.0075 - commission_rate
                scenario_rows.append({
                    "美股当晚涨幅": f"{us_ret*100:+.1f}%",
                    "赎回净值": f"¥{redeem_nav:.4f}",
                    "毛收益": f"{gross*100:+.2f}%",
                    "T+0净收益(费1.5%)": f"{net_t0*100:+.2f}%",
                    "7天后净收益(费0.75%)": f"{net_7d*100:+.2f}%",
                })
            st.dataframe(pd.DataFrame(scenario_rows), use_container_width=True, hide_index=True)

            st.markdown("---")
            st.subheader("结论")
            discount_abs = abs(premium_rate)
            if discount_abs < 0.03:
                st.error(f"折价 {discount_abs*100:.1f}% 太小。T+0 赎回扣 1.5% 费后安全垫仅 {(discount_abs-0.015)*100:.1f}%，美股跌 {(discount_abs-0.015)*100:.1f}% 就亏。不建议做。")
            elif discount_abs < 0.05:
                st.warning(f"折价 {discount_abs*100:.1f}% 一般。安全垫 {(discount_abs-0.015)*100:.1f}%，美股单日 2-3% 波动常见，风险较大。")
            elif discount_abs < 0.08:
                st.info(f"折价 {discount_abs*100:.1f}% 不错。安全垫 {(discount_abs-0.015)*100:.1f}%，有一定缓冲，但仍需关注当晚美股。")
            else:
                st.success(f"折价 {discount_abs*100:.1f}% 较大。安全垫 {(discount_abs-0.015)*100:.1f}%，历史上这个水平做买入+赎回大概率正收益。")


# ---------- Tab 4: 先行指标（P2） ----------
with tab4:
    st.subheader("美股盘前 / 原油期货先行指标")
    st.caption("A 股收盘后美股才开盘。以下指标预判今晚美股方向，决定是否在 15:00 前提交赎回。")

    indicators = fetch_indicators()
    cols = st.columns(3)
    for i, (name, entry) in enumerate(indicators.items()):
        with cols[i % 3]:
            if entry['chg_pct'] is not None:
                color = "🟢" if entry['chg_pct'] > 0 else ("🔴" if entry['chg_pct'] < 0 else "⚪")
                st.metric(
                    f"{color} {name}",
                    f"{entry['last']:.2f}",
                    f"{entry['chg_pct']*100:+.2f}%"
                )
            else:
                st.metric(f"⚪ {name}", "N/A", entry['err'] or "获取失败")

    st.markdown("---")
    st.subheader("📈 原油期货走势（近 5 日）")
    try:
        cl = yf.Ticker("CL=F").history(period="5d")
        bz = yf.Ticker("BZ=F").history(period="5d")
        if cl is not None and len(cl) > 0 and bz is not None and len(bz) > 0:
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=pd.to_datetime(cl.index).strftime('%Y-%m-%d'),
                y=cl['Close'], mode='lines+markers', name='WTI 原油', line=dict(color='royalblue')))
            fig.add_trace(go.Scatter(
                x=pd.to_datetime(bz.index).strftime('%Y-%m-%d'),
                y=bz['Close'], mode='lines+markers', name='Brent 原油', line=dict(color='coral')))
            fig.update_layout(height=350, margin=dict(l=20, r=20, t=20, b=20), hovermode='x unified')
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.warning("原油期货数据获取失败")
    except Exception as e:
        st.warning(f"原油期货图加载失败: {e}")

    st.markdown("---")
    st.subheader("💡 指标解读")
    st.write("""
- **WTI/Brent 原油期货**：油气股最直接的先行指标。全球 24 小时交易，A 股时段也有亚盘价格。原油期货大跌 → 今晚美股油气股大概率高开低走 → 赎回净值风险大。
- **XOP 盘前**：美股油气 ETF 盘前价格（北京晚间才有）。最直接的 XOP 方向参考。
- **标普500/纳指期货**：大盘情绪。美股大盘暴跌时油气股难独善其身。
- **美元指数**：美元走强压制油价和新兴市场资金流。

**决策规则**：折价套利时，若 WTI 原油期货亚盘跌 > 2%，今晚 XOP 大概率跟跌，赎回净值风险大，建议放弃或等原油企稳再赎回。
""")


# ---------- Tab 5: 历史回测（P3） ----------
with tab5:
    st.subheader("折价套利历史回测")
    st.caption("遍历历史每个交易日，模拟「折价超阈值时买入 + 当日赎回」，用事后实际净值算真实收益。")

    with st.spinner("加载历史数据..."):
        merged, bt_debug = fetch_backtest_data(days=400)

    if bt_debug:
        with st.expander(f"回测数据源异常（{len(bt_debug)} 项）"):
            for err in bt_debug:
                st.write(f"- {err}")

    if merged is None or len(merged) < 30:
        st.error("历史数据不足，无法回测")
    else:
        st.write(f"**数据范围**：{merged['date_str'].iloc[0]} ~ {merged['date_str'].iloc[-1]}，共 {len(merged)} 个交易日")

        # 参数选择
        col_p1, col_p2 = st.columns(2)
        with col_p1:
            thresholds = st.multiselect("折价阈值（%）", [3, 5, 8, 10], default=[3, 5, 8])
        with col_p2:
            fee_mode = st.selectbox("赎回费模式", [
                "T+0 赎回（1.5%）",
                "持有7天后赎回（0.75%）",
                "持有30天后赎回（0.5%）",
            ])

        fee_map = {
            "T+0 赎回（1.5%）": 0.015,
            "持有7天后赎回（0.75%）": 0.0075,
            "持有30天后赎回（0.5%）": 0.005,
        }
        redeem_fee = fee_map[fee_mode]

        st.markdown("---")
        st.subheader("各阈值回测结果")

        all_stats = []
        all_trades = {}
        for th in thresholds:
            trades, stats = run_backtest(merged, th, redeem_fee, commission_rate, fee_mode)
            all_stats.append(stats)
            all_trades[th] = trades

        stats_rows = []
        for s in all_stats:
            stats_rows.append({
                "折价阈值": f">{s['threshold']}%",
                "交易次数": s['total_trades'],
                "胜率": f"{s['win_rate']*100:.1f}%" if s['total_trades'] > 0 else "-",
                "平均收益": f"{s['avg_ret']*100:+.2f}%" if s['total_trades'] > 0 else "-",
                "中位收益": f"{s['median_ret']*100:+.2f}%" if s['total_trades'] > 0 else "-",
                "最大亏损": f"{s['max_loss']*100:+.2f}%" if s['total_trades'] > 0 else "-",
                "最大盈利": f"{s['max_gain']*100:+.2f}%" if s['total_trades'] > 0 else "-",
                "累计收益(简单加总)": f"{s['cum_ret']*100:+.2f}%" if s['total_trades'] > 0 else "-",
            })
        st.dataframe(pd.DataFrame(stats_rows), use_container_width=True, hide_index=True)

        # 累计收益曲线
        st.markdown("---")
        st.subheader("累计收益曲线（简单加总，未复利）")
        fig = go.Figure()
        for th in thresholds:
            trades = all_trades[th]
            if len(trades) > 0:
                cum = trades['net_ret'].cumsum()
                fig.add_trace(go.Scatter(
                    x=trades['date_str'], y=cum * 100,
                    mode='lines+markers', name=f"折价>{th}%",
                ))
        fig.add_hline(y=0, line_dash="dash", line_color="gray")
        fig.update_layout(
            xaxis_title="日期", yaxis_title="累计收益 (%)",
            height=400, margin=dict(l=20, r=20, t=20, b=20), hovermode='x unified',
        )
        st.plotly_chart(fig, use_container_width=True)

        # 收益分布
        st.markdown("---")
        st.subheader("单笔收益分布")
        selected_th = st.selectbox("选择阈值查看明细", thresholds)
        trades = all_trades[selected_th]
        if len(trades) > 0:
            fig2 = go.Figure()
            fig2.add_trace(go.Histogram(
                x=trades['net_ret'] * 100, nbinsx=30,
                marker_color='royalblue', name='单笔收益',
            ))
            fig2.add_vline(x=0, line_dash="dash", line_color="red")
            fig2.update_layout(
                xaxis_title="单笔净收益 (%)", yaxis_title="次数",
                height=300, margin=dict(l=20, r=20, t=20, b=20),
            )
            st.plotly_chart(fig2, use_container_width=True)

            with st.expander(f"📋 交易明细（{len(trades)} 笔）"):
                show = trades.copy()
                show['signal'] = show['signal'].apply(lambda x: f"{x*100:+.2f}%")
                show['gross_ret'] = show['gross_ret'].apply(lambda x: f"{x*100:+.2f}%")
                show['net_ret'] = show['net_ret'].apply(lambda x: f"{x*100:+.2f}%")
                show = show.rename(columns={
                    'date_str': '日期', 'close': '买入价', 'nav_prev': '决策基线净值',
                    'signal': '当时折价', 'redeem_nav': '赎回净值',
                    'gross_ret': '毛收益', 'net_ret': '净收益',
                })
                st.dataframe(show, use_container_width=True, hide_index=True)

            st.markdown("---")
            st.subheader("📌 回测结论")
            s = next(x for x in all_stats if x['threshold'] == selected_th)
            if s['total_trades'] == 0:
                st.info(f"折价 > {selected_th}% 在历史数据中未出现过。")
            else:
                verdict = "✅ 能赚钱" if s['avg_ret'] > 0 and s['win_rate'] > 0.6 else (
                    "⚠️ 勉强能赚" if s['avg_ret'] > 0 else "❌ 赚不到钱"
                )
                st.write(f"**{verdict}**：折价 > {selected_th}% 时买入+赎回，"
                         f"共 {s['total_trades']} 笔交易，胜率 {s['win_rate']*100:.1f}%，"
                         f"平均单笔 {s['avg_ret']*100:+.2f}%，累计 {s['cum_ret']*100:+.2f}%。")
                st.write(f"最大单笔亏损 {s['max_loss']*100:+.2f}%，最大单笔盈利 {s['max_gain']*100:+.2f}%。")
                if s['avg_ret'] > 0 and s['win_rate'] > 0.6:
                    st.success("策略有效，但需注意：历史不代表未来，单笔最大亏损仍可能伤及本金。")
                elif s['avg_ret'] <= 0:
                    st.error("策略无效或风险过大。赎回费 + 美股波动吃掉了折价收益。考虑提高阈值或延长持有期降费。")
        else:
            st.info(f"折价 > {selected_th}% 在历史数据中未出现过。")
