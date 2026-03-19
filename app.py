import streamlit as st
import akshare as ak
import pandas as pd
import yfinance as yf
from datetime import datetime
import pytz

# --- 页面基础设置 ---
st.set_page_config(page_title="华宝油气(162411)实时监控", page_icon="🛢️", layout="wide")
st.title("🛢️ 华宝油气 LOF (162411) 实时折溢价监控")

# --- 交易时段提示 ---
tz = pytz.timezone('Asia/Shanghai')
now = datetime.now(tz)
if now.hour < 9 or now.hour >= 15 or now.weekday() >= 5:
    st.warning("⏰ 当前非 A 股交易时段，场内价格为最近一个交易日的收盘价。")

# --- 侧边栏 ---
with st.sidebar:
    st.header("⚙️ 控制面板")
    if st.button("🔄 手动刷新数据"):
        st.cache_data.clear()
        st.rerun()
    st.markdown("---")
    st.write("💡 **底层逻辑**：")
    st.write("已引入 **0.94** 的仓位系数，对冲暂停申购下的现金拖累。")
    st.write("🌐 **当前引擎**：全海外加速版")

# --- 核心数据获取模块 (带独立容错与精准报错) ---
@st.cache_data(ttl=60)
def get_market_data():
    debug_log = []
    
    # 1. 场内价格 (改用雅虎财经，海外服务器最稳，彻底绕开国内封锁)
    try:
        lof = yf.Ticker("162411.SZ")
        current_price = float(lof.fast_info['lastPrice'])
    except Exception as e:
        debug_log.append(f"获取场内价格(雅虎)失败: {e}")
        current_price = 0.0
        
    # 2. 官方最新净值 (恢复为东方财富，实测对海外宽容)
    try:
        nav_data = ak.fund_open_fund_info_em(symbol="162411", indicator="单位净值走势")
        latest_nav = float(nav_data.iloc[-1]['单位净值'])
        nav_date = str(nav_data.iloc[-1]['净值日期'])[:10]
    except Exception as e:
        debug_log.append(f"获取官方净值(东财)失败: {e}")
        latest_nav, nav_date, nav_data = 0.0, "N/A", None
    # 3. 美股 XOP
    try:
        xop = yf.Ticker("XOP")
        xop_prev = float(xop.fast_info['previousClose'])
        xop_curr = float(xop.fast_info['lastPrice'])
        xop_pct = (xop_curr - xop_prev) / xop_prev if xop_prev > 0 else 0.0
    except Exception as e:
        debug_log.append(f"获取XOP(雅虎)失败: {e}")
        xop_pct = 0.0

    # 4. 汇率 USDCNH
    try:
        usdcnh = yf.Ticker("USDCNH=X")
        fx_prev = float(usdcnh.fast_info['previousClose'])
        fx_curr = float(usdcnh.fast_info['lastPrice'])
        fx_pct = (fx_curr - fx_prev) / fx_prev if fx_prev > 0 else 0.0
    except Exception as e:
        debug_log.append(f"获取汇率(雅虎)失败: {e}")
        fx_pct = 0.0

    return current_price, latest_nav, nav_date, xop_pct, fx_pct, nav_data, debug_log

# --- 执行计算与渲染 ---
current_price, latest_nav, nav_date, xop_pct, fx_pct, nav_data, debug_log = get_market_data()

# 如果有错误，精准打印出来让我们看清是哪里断了
if debug_log:
    st.error("⚠️ 获取部分数据时遇到阻力，具体排雷信息如下：")
    for err in debug_log:
        st.write(f"- {err}")

# 只要最核心的场内价格和净值拿到了，就把看板强行渲染出来
if current_price > 0 and latest_nav > 0:
    # 核心推演：0.94 系数护体
    iopv_est = latest_nav * (1 + (xop_pct * 0.94)) * (1 + fx_pct)
    premium_rate = (current_price / iopv_est) - 1

    st.subheader("📊 核心指标")
    col1, col2, col3, col4 = st.columns(4)
    
    col1.metric("场内实时价格", f"¥{current_price:.4f}")
    col2.metric(f"官方净值 ({nav_date})", f"¥{latest_nav:.4f}")
    col3.metric("IOPV 估算值 (0.94系数)", f"¥{iopv_est:.4f}")
    
    if premium_rate < 0:
        col4.metric("实时折溢价率", f"{premium_rate * 100:.2f}%", "折价安全区", delta_color="inverse")
    else:
        col4.metric("实时折溢价率", f"{premium_rate * 100:.2f}%", "溢价风险区", delta_color="normal")

    st.markdown("---")
    st.subheader("📈 底层资产波动 (国际源)")
    col_a, col_b = st.columns(2)
    col_a.metric("标普油气 XOP", f"{xop_pct * 100:.2f}%")
    col_b.metric("USD/CNH 汇率", f"{fx_pct * 100:.2f}%")

if nav_data is not None:
        st.markdown("---")
        st.subheader("📋 详细历史数据")
        display_df = nav_data.tail(10).sort_values(by='净值日期', ascending=False)
        
        # 穿上防弹衣：只提取实际存在的列，防止 KeyError
        safe_cols = [c for c in ['净值日期', '单位净值', '累计净值', '日增长率'] if c in display_df.columns]
        display_df = display_df[safe_cols]
        
        st.dataframe(display_df, use_container_width=True)
