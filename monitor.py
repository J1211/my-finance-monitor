import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timedelta
from fredapi import Fred

# --- 1. 配置与初始化 ---
st.set_page_config(page_title="GSMI | 全球聪明钱监控面板", layout="wide")

st.markdown("""
    <style>
    .main { background-color: #0e1117; }
    div[data-testid="stMetricValue"] { font-size: 28px; }
    </style>
    """, unsafe_allow_html=True)

st.title("🏹 全球聪明钱指数 (GSMI) 投资前瞻看板")

# --- 2. 侧边栏配置 ---
st.sidebar.header("🛠️ 核心参数配置")

if "fred_api_key" in st.secrets:
    fred_key = st.secrets["fred_api_key"]
else:
    fred_key = st.sidebar.text_input("FRED API Key", type="password")

if not fred_key:
    st.warning("请在侧边栏配置 FRED API Key。")
    st.stop()

fred = Fred(api_key=fred_key)

st.sidebar.markdown("---")
st.sidebar.header("🗳️ BofA FMS 机构调查 (月更)")
fms_date = st.sidebar.date_input("本期调查发布日期", datetime.now() - timedelta(days=15))
fms_cash = st.sidebar.slider("机构现金水平 (%)", 3.0, 6.5, 4.5, 0.1)
fms_crowded = st.sidebar.selectbox("当前最拥挤交易", ["美股大盘科技", "做空中国股票", "做多美元", "做多国债", "其他/无"])
target_sector_status = st.sidebar.radio("关注板块拥挤度", ["冷清/低配", "标配", "极其拥挤"])

# --- 3. 健壮的数据抓取函数 ---

@st.cache_data(ttl=3600)
def fetch_data():
    end = datetime.now()
    # 抓取400天数据确保200日均线计算准确
    start = end - timedelta(days=400)
    
    # A. FRED 数据 (清洗 NaN)
    tips_raw = fred.get_series('DFII10', start, end)
    spread_raw = fred.get_series('BAMLH0A0HYM2', start, end)
    
    tips = tips_raw.ffill().dropna()
    spread = spread_raw.ffill().dropna()
    
    # B. Yahoo Finance 数据
    tickers = {
        "DXY": "DX-Y.NYB",
        "Copper": "HG=F",
        "Gold": "GC=F",
        "HKD": "HKD=X"
    }
    
    raw_df = yf.download(list(tickers.values()), start=start, end=end, progress=False)
    
    if raw_df.empty:
        st.error("无法从 Yahoo Finance 获取数据，请检查网络连接或代理设置。")
        st.stop()
        
    # 处理 MultiIndex 并提取 Close
    if isinstance(raw_df.columns, pd.MultiIndex):
        price_df = raw_df['Close'].ffill().dropna()
    else:
        price_df = raw_df.ffill().dropna()
        
    return tips, price_df, spread

# --- 4. 逻辑执行 ---

try:
    tips_ser, price_df, spread_ser = fetch_data()

    # 安全提取最新值
    curr_tips = float(tips_ser.iloc[-1])
    prev_tips = float(tips_ser.iloc[-5])
    
    curr_dxy = float(price_df["DX-Y.NYB"].iloc[-1])
    prev_dxy = float(price_df["DX-Y.NYB"].iloc[-5])
    
    curr_spread = float(spread_ser.iloc[-1])
    prev_spread = float(spread_ser.iloc[-5])
    
    curr_hkd = float(price_df["HKD=X"].iloc[-1])
    
    # 铜金比计算
    cg_series = (price_df["HG=F"] / price_df["GC=F"]).dropna()
    curr_cg = float(cg_series.iloc[-1])
    prev_cg = float(cg_series.iloc[-5])
    ma200_cg_ser = cg_series.rolling(200).mean().dropna()
    
    if ma200_cg_ser.empty:
        st.warning("数据量不足以计算200日均线，评分将受影响。")
        ma200_cg = curr_cg
    else:
        ma200_cg = float(ma200_cg_ser.iloc[-1])

    # --- 5. GSMI 评分算法 ---
    
    s_tips = 20 if curr_tips < 1.0 else (10 if curr_tips <= 2.0 else 0)
    s_dxy = 20 if curr_dxy < 100 else (10 if curr_dxy <= 105 else 0)
    s_cash = 30 if fms_cash > 5.0 else (15 if fms_cash >= 4.0 else 0)
    s_spread = 20 if curr_spread < 350 else (10 if curr_spread <= 500 else 0)
    s_cg = 10 if curr_cg > ma200_cg else 0
    
    gsmi_total = s_tips + s_dxy + s_cash + s_spread + s_cg

    # --- 6. UI 展示 ---

    # 顶部仪表盘
    c_score, c_radar = st.columns([2, 1])
    with c_score:
        fig = go.Figure(go.Indicator(
            mode = "gauge+number",
            value = gsmi_total,
            domain = {'x': [0, 1], 'y': [0, 1]},
            title = {'text': "GSMI 环境总分", 'font': {'size': 24}},
            gauge = {
                'axis': {'range': [0, 100], 'tickwidth': 1},
                'bar': {'color': "#00ffcc"},
                'steps': [
                    {'range': [0, 40], 'color': "#3d0000"},
                    {'range': [40, 60], 'color': "#3d3d00"},
                    {'range': [60, 80], 'color': "#003d00"},
                    {'range': [80, 100], 'color': "#006600"}
                ]
            }
        ))
        fig.update_layout(height=350, margin=dict(l=30, r=30, t=50, b=20), paper_bgcolor="#0e1117", font={'color': "white"})
        st.plotly_chart(fig, use_container_width=True)

    with c_radar:
        st.subheader("🚨 战术预警灯")
        status_map = {"冷清/低配": "🟢 低位安全", "标配": "🟡 中性观望", "极其拥挤": "🔴 警惕踩踏"}
        st.markdown(f"**关注板块:**")
        st.title(status_map[target_sector_status])
        st.warning(f"最拥挤交易: **{fms_crowded}**")
        st.caption(f"FMS 数据更新于: {fms_date}")

    # 分层详情
    st.markdown("---")
    t1, t2, t3, t4 = st.tabs(["💧 流动性", "🧠 情绪", "🏗️ 现实", "📈 执行"])

    with t1:
        col1, col2 = st.columns(2)
        col1.metric("10Y TIPS (实际利率)", f"{curr_tips:.2f}%", f"{curr_tips-prev_tips:.4f}", delta_color="inverse")
        col2.metric("美元指数 (DXY)", f"{curr_dxy:.2f}", f"{curr_dxy-prev_dxy:.2f}", delta_color="inverse")
        st.line_chart(price_df["DX-Y.NYB"].tail(90))

    with t2:
        m1, m2 = st.columns(2)
        m1.metric("FMS 现金水平", f"{fms_cash}%", delta="看多信号" if fms_cash > 5 else "警示信号" if fms_cash < 4 else "中性")
        st.info(f"当机构现金 > 5% 时，市场往往处于底部区域；当现金 < 4% 时，市场动力可能衰竭。")

    with t3:
        r1, r2 = st.columns(2)
        r1.metric("信用利差 (HY Spread)", f"{curr_spread:.0f} bps", f"{curr_spread-prev_spread:.0f}", delta_color="inverse")
        r2.metric("铜金比趋势", f"{curr_cg:.4f}", f"{curr_cg-prev_cg:.4f}")
        
        # 铜金比图表
        fig_cg = go.Figure()
        fig_cg.add_trace(go.Scatter(x=cg_series.index[-120:], y=cg_series.values[-120:], name="铜金比", line=dict(color='#00ffcc')))
        fig_cg.add_trace(go.Scatter(x=ma200_cg_ser.index[-120:], y=ma200_cg_ser.values[-120:], name="200日均线", line=dict(dash='dash', color='white')))
        fig_cg.update_layout(height=300, template="plotly_dark", margin=dict(l=10, r=10, t=10, b=10))
        st.plotly_chart(fig_cg, use_container_width=True)

    with t4:
        e1, e2 = st.columns(2)
        e1.metric("港元汇率 (USD/HKD)", f"{curr_hkd:.4f}", 
                  delta="流出" if curr_hkd > 7.84 else ("流入" if curr_hkd < 7.76 else "平稳"))
        
        st.write("---")
        st.write("**资金流手动验证 (North/South Flow):**")
        n_flow = st.select_slider("北向资金 (外资进 A 股)", ["流出", "平稳", "流入"], value="平稳")
        s_flow = st.select_slider("南向资金 (内资进港股)", ["流出", "平稳", "流入"], value="平稳")
        
        if gsmi_total > 60 and n_flow == "流入":
            st.success("🎯 信号共振：环境分高 + 资金流向确认，建议积极配置。")

except Exception as e:
    st.error(f"发生错误: {e}")
    st.info("排查建议：1. 检查 API Key；2. 检查网络（Yahoo Finance 可能需要科学上网）；3. 刷新网页重试。")

st.markdown("---")
st.caption("评分体系：流动性 (40%) + 情绪 (30%) + 现实 (30%) = GSMI 100分。数据仅供参考，不构成投资建议。")
