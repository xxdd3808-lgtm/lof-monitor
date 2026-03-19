import streamlit as st
import akshare as ak
import pandas as pd
import yfinance as yf
from datetime import datetime
import pytz

# --- 页面基础设置 ---
st.set_page_config(page_title="华宝油气(162411)实时监控", page_icon="🛢️", layout="wide")
st.title("🛢️ 华宝油气 LOF (162411) 实时折溢价监控")

# --- 交易时段提示 (已恢复) ---
tz = pytz.timezone('Asia/Shanghai')
now = datetime.now(tz)
if now.hour < 9 or now.hour >= 15 or now.weekday() >= 5:
    st.warning("⏰ 当前非 A 股交易时段，场内价格为最近一个交易日的收盘价。")

# --- 侧边栏 ---
with st.sidebar:
    st.header("⚙️ 控制面板")
    if st.button("🔄 手动刷新数据"):
        st.cache_data.clear()
    st.markdown("---")
    st.write("💡 **底层逻辑**：")
    st.write("已引入 **0.94** 的仓位系数，对冲暂停申购下的现金拖累，让估值更贴近真实的内在价值。")
    st.write("🌐 **当前数据引擎**：")
    st.write("雅虎财经 (美股/汇率) + 腾讯/新浪接口 (A股)")

# --- 核心数据获取模块 (海外节点专用) ---
@st.cache_data(ttl=60)
def get_market_data():
    try:
        # 1. 场内实时价格 (腾讯接口)
        tx_data = ak.stock_zh_a_spot_tx()
        fund_162411 = tx_data[tx_data['代码'].astype(str).str.contains('162411')]
        current_price = float(fund_162411.iloc[0]['最新价']) if not fund_162411.empty else 0.0
        
        # 2. 官方最新净值 (新浪接口)
        nav_data = ak.fund_open_fund_info_sina(symbol="162411")
        latest_nav = float(nav_data.iloc[-1]['单位净值'])
        nav_date = str(nav_data.iloc[-1]['净值日期'])[:10]

        # 3. 美股 XOP 涨跌幅 (yfinance)
        xop = yf.Ticker("XOP")
        xop_prev = xop.fast_info['previousClose']
        xop_curr = xop.fast_info['lastPrice']
        xop_pct = (xop_curr - xop_prev) / xop_prev

        # 4. 离岸人民币汇率 (yfinance)
        usdcnh = yf.Ticker("USDCNH=X")
        fx_prev = usdcnh.fast_info['previousClose']
        fx_curr = usdcnh.fast_info['lastPrice']
        fx_pct = (fx_curr - fx_prev) / fx_prev

        return current_price, latest_nav, nav_date, xop_pct, fx_pct, nav_data
    except Exception as e:
        return None, None, None, None, None, None

# --- 执行计算与渲染 ---
current_price, latest_nav, nav_date, xop_pct, fx_pct, nav_data = get_market_data()

if current_price is not None and current_price > 0:
    # 核心推演：0.94 系数护体
    iopv_est = latest_nav * (1 + (xop_pct * 0.94)) * (1 + fx_pct)
    premium_rate = (current_price / iopv_est) - 1

    st.subheader("📊 核心指标")
    col1, col2, col3, col4 = st.columns(4)
    
    col1.metric("场内实时价格", f"¥{current_price:.4f}")
    col2.metric(f"官方净值 ({nav_date})", f"¥{latest_nav:.4f}")
    col3.metric("IOPV 估算值 (0.94系数)", f"¥{iopv_est:.4f}")
    
    # 折溢价红绿灯
    if premium_rate < 0:
        col4.metric("实时折溢价率", f"{premium_rate * 100:.2f}%", "折价安全区", delta_color="inverse")
    else:
        col4.metric("实时折溢价率", f"{premium_rate * 100:.2f}%", "溢价风险区", delta_color="normal")

    st.markdown("---")
    st.subheader("📈 底层资产波动 (国际源)")
    col_a, col_b = st.columns(2)
    col_a.metric("标普油气 XOP", f"{xop_pct * 100:.2f}%")
    col_b.metric("USD/CNH 汇率", f"{fx_pct * 100:.2f}%")

    # --- 详细数据表格 (已恢复) ---
    st.markdown("---")
    st.subheader("📋 详细历史数据")
    if nav_data is not None:
        # 取最近10天的净值数据倒序排列展示
        display_df = nav_data.tail(10).sort_values(by='净值日期', ascending=False)
        display_df = display_df[['净值日期', '单位净值', '累计净值', '日增长率']]
        st.dataframe(display_df, use_container_width=True)

else:
    st.error("⚠️ 国际数据源连接中，请稍后点击左侧『手动刷新数据』。")
