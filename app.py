import streamlit as st
import akshare as ak
import pandas as pd
from datetime import datetime

# --- 页面基础设置 ---
st.set_page_config(page_title="华宝油气(162411)实时监控", page_icon="🛢️", layout="wide")
st.title("🛢️ 华宝油气 LOF (162411) 实时折溢价监控")

# --- 侧边栏：控制面板 ---
with st.sidebar:
    st.header("⚙️ 控制面板")
    if st.button("🔄 手动刷新数据"):
        st.cache_data.clear()
    st.markdown("---")
    st.write("💡 **底层逻辑说明**：")
    st.write("已引入 **0.94** 的仓位系数，对冲暂停申购下的现金拖累，让估值更精准。")

# --- 核心数据获取模块 (带缓存机制防止请求过频) ---
@st.cache_data(ttl=60) # 缓存 60 秒
def get_market_data():
    try:
        # 1. 获取 162411 场内实时行情
        fund_data = ak.fund_etf_spot_em()
        fund_162411 = fund_data[fund_data['代码'] == '162411'].iloc[0]
        current_price = fund_162411['最新价']
        
        # 2. 获取官方最新净值 (T-1或T-2)
        nav_data = ak.fund_open_fund_info_em(symbol="162411", indicator="单位净值走势")
        latest_nav = nav_data.iloc[-1]['单位净值']
        nav_date = nav_data.iloc[-1]['净值日期']
        
        # 3. 获取美股 XOP 盘前/实时涨跌幅 (此处以 akshare 美股接口为例，需确保接口畅通)
        # 注：为了代码稳健运行，这里模拟抓取结构，实战中可根据接口调整
        us_stock = ak.stock_us_spot_em()
        xop_row = us_stock[us_stock['代码'] == 'XOP']
        xop_pct = xop_row.iloc[0]['涨跌幅'] / 100 if not xop_row.empty else 0.0
        
        # 4. 获取美元离岸人民币汇率 (USD/CNH) 涨跌幅
        fx_data = ak.fx_spot_quote()
        usd_cnh_row = fx_data[fx_data['货币对'] == '美元/离岸人民币']
        fx_pct = usd_cnh_row.iloc[0]['涨跌幅'] / 100 if not usd_cnh_row.empty else 0.0
        
        return current_price, latest_nav, nav_date, xop_pct, fx_pct
    except Exception as e:
        return None, None, None, None, None

# --- 执行计算与渲染 ---
current_price, latest_nav, nav_date, xop_pct, fx_pct = get_market_data()

if current_price is not None:
    # 执行我们推演的 0.94 系数硬核公式
    iopv_est = latest_nav * (1 + (xop_pct * 0.94)) * (1 + fx_pct)
    premium_rate = (current_price / iopv_est) - 1

    st.subheader("📊 核心指标")
    col1, col2, col3, col4 = st.columns(4)
    
    col1.metric("场内实时价格", f"¥{current_price:.4f}")
    col2.metric(f"官方净值 ({nav_date})", f"¥{latest_nav:.4f}")
    col3.metric("IOPV 估算值 (0.94系数)", f"¥{iopv_est:.4f}")
    
    # 折溢价红绿灯变色逻辑
    if premium_rate < 0:
        col4.metric("实时折溢价率", f"{premium_rate * 100:.2f}%", "折价安全区", delta_color="inverse")
    else:
        col4.metric("实时折溢价率", f"{premium_rate * 100:.2f}%", "溢价风险区", delta_color="normal")

    st.markdown("---")
    st.subheader("📈 底层资产波动")
    col_a, col_b = st.columns(2)
    col_a.metric("标普油气 XOP 实时变化", f"{xop_pct * 100:.2f}%")
    col_b.metric("USD/CNH 汇率变化", f"{fx_pct * 100:.2f}%")
else:
    st.error("⚠️ 数据接口请求失败，请点击左侧栏手动刷新，或检查 akshare 网络连接。")
