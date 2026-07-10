import streamlit as st
import akshare as ak
import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
from datetime import datetime
import pytz

# --- 页面基础设置 ---
st.set_page_config(page_title="华宝油气(162411)实时监控", page_icon="🛢️", layout="wide")
st.title("🛢️ 华宝油气 LOF (162411) 实时折溢价监控")

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
    st.subheader("模型说明")
    st.write("**IOPV 估算公式**：")
    st.write("IOPV = NAV(nav_date) × (1 + r_XOP × w) × (1 + r_FX)")
    st.caption(
        "r_XOP / r_FX 为 nav_date 对应美股收盘日至今的累计涨幅（非仅当日涨幅），"
        "解决 QDII 净值滞后 1-2 日带来的时间窗口错配。"
    )
    st.write("🌐 数据源：雅虎财经（XOP / 汇率 / 场内价）+ 东方财富（净值）")

# --- 交易时段提示 ---
if now.hour < 9 or now.hour >= 15 or now.weekday() >= 5:
    st.warning("⏰ 当前非 A 股交易时段，场内价格为最近交易日收盘价。")
st.caption("ℹ️ QDII 净值通常滞后 1-2 个交易日公布，IOPV 估算已按 nav_date 对齐累计底层涨幅。")


# --- 数据获取 ---
@st.cache_data(ttl=60)
def fetch_data():
    debug_log = []

    # 1. 场内实时价格
    current_price = None
    try:
        price_raw = yf.Ticker("162411.SZ").fast_info['lastPrice']
        if price_raw and float(price_raw) > 0:
            current_price = float(price_raw)
    except Exception as e:
        debug_log.append(f"场内价格(雅虎)失败: {e}")

    # 2. 官方净值历史
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

    # 3. XOP 历史日线（最后一根为最新，含当日盘中）
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

    # 4. 汇率历史
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

    # 5. 场内历史（用于折溢价曲线）
    lof_hist = None
    try:
        hist = yf.Ticker("162411.SZ").history(period="6mo")
        if hist is not None and len(hist) > 0:
            lof_hist = hist
        else:
            debug_log.append("场内历史为空")
    except Exception as e:
        debug_log.append(f"场内历史失败: {e}")

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
        'lof_hist': lof_hist,
        'debug_log': debug_log,
    }


data = fetch_data()
debug_log = data['debug_log']

if debug_log:
    with st.expander(f"⚠️ 数据源异常（{len(debug_log)} 项）", expanded=False):
        for err in debug_log:
            st.write(f"- {err}")

# --- 核心指标 ---
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

st.subheader("📊 核心指标")
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

    # 底层累计变动
    st.markdown("---")
    st.subheader("📈 底层资产累计变动（nav_date 对应美股日 → 最新）")
    col_a, col_b = st.columns(2)
    col_a.metric(
        "XOP 累计涨幅",
        f"{xop_cum_ret*100:+.2f}%",
        f"{data['xop_baseline_date']} ¥{data['xop_baseline']:.2f} → {data['xop_current_date']} ¥{data['xop_current']:.2f}",
    )
    col_b.metric(
        "USD/CNH 累计涨幅",
        f"{fx_cum_ret*100:+.2f}%",
        f"{data['fx_baseline_date']} {data['fx_baseline']:.4f} → {data['fx_current_date']} {data['fx_current']:.4f}",
    )

    # IOPV 拆解
    with st.expander("🔬 IOPV 估算拆解"):
        st.write(f"**NAV 基准**（{nav_date}）：¥{latest_nav:.4f}")
        st.write(
            f"**XOP 累计涨幅**：{xop_cum_ret*100:+.2f}%"
            f"（{data['xop_baseline_date']} ¥{data['xop_baseline']:.2f} → {data['xop_current_date']} ¥{data['xop_current']:.2f}）"
        )
        st.write(
            f"**仓位系数 w**：{position_ratio:.2f}"
            f"（股票 {position_ratio*100:.0f}% + 现金 {(1-position_ratio)*100:.0f}%）"
        )
        st.write(
            f"**汇率累计涨幅**：{fx_cum_ret*100:+.2f}%"
            f"（{data['fx_baseline_date']} {data['fx_baseline']:.4f} → {data['fx_current_date']} {data['fx_current']:.4f}）"
        )
        st.write(
            f"**公式**：IOPV = {latest_nav:.4f} × (1 + ({xop_cum_ret:.4f}) × {position_ratio}) "
            f"× (1 + {fx_cum_ret:.4f}) = ¥{iopv_est:.4f}"
        )
        st.write(f"**折溢价**：(¥{current_price:.4f} / ¥{iopv_est:.4f}) − 1 = {premium_rate*100:+.2f}%")
else:
    col3.metric("IOPV 估算", "N/A")
    col4.metric("实时折溢价率", "N/A")
    st.error("❌ 核心数据缺失，无法计算 IOPV / 折溢价。缺失项：")
    if not (current_price and current_price > 0):
        st.write("- 场内实时价格")
    if not (latest_nav and latest_nav > 0):
        st.write("- 官方净值")
    if xop_cum_ret is None:
        st.write("- XOP 累计涨幅")
    if fx_cum_ret is None:
        st.write("- 汇率累计涨幅")

# --- 历史折溢价曲线 ---
st.markdown("---")
st.subheader("📉 历史收盘折溢价曲线（基于当日公布净值）")

if data['nav_data'] is not None and data['lof_hist'] is not None:
    try:
        nav_df = data['nav_data'][['净值日期', '单位净值']].copy()
        nav_df['date_str'] = pd.to_datetime(nav_df['净值日期']).dt.strftime('%Y-%m-%d')
        nav_df = nav_df.rename(columns={'单位净值': 'nav'})

        lof_hist = data['lof_hist'].copy()
        lof_hist['date_str'] = pd.to_datetime(lof_hist.index).strftime('%Y-%m-%d')
        lof_hist = lof_hist[['date_str', 'Close']].rename(columns={'Close': 'close'})

        merged = pd.merge(nav_df, lof_hist, on='date_str', how='inner')
        merged = merged.sort_values('date_str').tail(60)
        merged['premium'] = merged['close'] / merged['nav'] - 1

        if len(merged) > 0:
            mean_premium = merged['premium'].mean()
            col_p1, col_p2, col_p3, col_p4 = st.columns(4)
            col_p1.metric("近60日最高溢价", f"{merged['premium'].max()*100:+.2f}%")
            col_p2.metric("近60日最低溢价", f"{merged['premium'].min()*100:+.2f}%")
            col_p3.metric("近60日均值", f"{mean_premium*100:+.2f}%")
            col_p4.metric("最新一日分位", f"{merged['premium'].rank(pct=True).iloc[-1]*100:.0f}%")

            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=merged['date_str'], y=merged['premium'] * 100,
                mode='lines+markers', name='折溢价',
                line=dict(color='royalblue', width=2),
                marker=dict(size=4),
            ))
            fig.add_hline(y=0, line_dash="dash", line_color="gray", annotation_text="0%")
            fig.add_hline(
                y=mean_premium * 100, line_dash="dot", line_color="orange",
                annotation_text=f"均值 {mean_premium*100:+.2f}%",
            )
            fig.update_layout(
                xaxis_title="日期", yaxis_title="折溢价率 (%)",
                height=400, margin=dict(l=20, r=20, t=20, b=20),
                showlegend=False, hovermode='x unified',
            )
            fig.update_xaxes(tickformat='%m-%d')
            st.plotly_chart(fig, use_container_width=True)

            with st.expander("📋 历史明细（近 20 日）"):
                show_df = merged.tail(20).copy()
                show_df['折溢价'] = show_df['premium'].apply(lambda x: f"{x*100:+.2f}%")
                show_df = show_df[['date_str', 'nav', 'close', '折溢价']].rename(
                    columns={'date_str': '日期', 'nav': '净值', 'close': '收盘价'}
                )
                st.dataframe(show_df, use_container_width=True, hide_index=True)
        else:
            st.warning("历史净值与场内价无重叠日期，可能是数据源时区/日期对齐问题。")
    except Exception as e:
        st.error(f"历史折溢价计算失败: {e}")
else:
    st.warning("缺少净值历史或场内价历史，无法绘制曲线。")

# --- 原始净值明细 ---
if data['nav_data'] is not None:
    st.markdown("---")
    st.subheader("📋 最近净值明细")
    display_df = data['nav_data'].tail(10).sort_values(by='净值日期', ascending=False)
    safe_cols = [c for c in ['净值日期', '单位净值', '累计净值', '日增长率'] if c in display_df.columns]
    st.dataframe(display_df[safe_cols], use_container_width=True, hide_index=True)
