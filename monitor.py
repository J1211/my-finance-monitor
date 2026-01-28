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
    .stAlert { padding: 10px; }
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

st.sidebar.markdown("---")
st.sidebar.header("🎯 个人追踪目标")
target_name = st.sidebar.text_input("关注板块名称", "例如：中概互联网 AI")
target_sector_status = st.sidebar.radio("该板块拥挤度评分", ["冷清/低配", "标配", "极其拥挤"])

# --- 3. 健壮的数据抓取函数 ---

@st.cache_data(ttl=3600)
def fetch_data():
    end = datetime.now()
    start = end - timedelta(days=400)
    
    # A. FRED 数据
    tips_raw = fred.get_series('DFII10', start, end)
    spread_raw = fred.get_series('BAMLH0A0HYM2', start, end)
    tips = tips_raw.ffill().dropna()
    spread = spread_raw.ffill().dropna()
    
    # B. Yahoo Finance 数据
    tickers = {"DXY": "DX-Y.NYB", "Copper": "HG=F", "Gold": "GC=F", "HKD": "HKD=X"}
    raw_df = yf.download(list(tickers.values()), start=start, end=end, progress=False)
    
    if isinstance(raw_df.columns, pd.MultiIndex):
        price_df = raw_df['Close'].ffill().dropna()
    else:
        price_df = raw_df.ffill().dropna()
        
    return tips, price_df, spread

# --- 4. 逻辑执行 ---

try:
    tips_ser, price_df, spread_ser = fetch_data()

    # 安全提取
    curr_tips = float(tips_ser.iloc[-1])
    prev_tips = float(tips_ser.iloc[-5])
    curr_dxy = float(price_df["DX-Y.NYB"].iloc[-1])
    prev_dxy = float(price_df["DX-Y.NYB"].iloc[-5])
    curr_spread = float(spread_ser.iloc[-1])
    prev_spread = float(spread_ser.iloc[-5])
    curr_hkd = float(price_df["HKD=X"].iloc[-1])
    
    # 铜金比
    cg_series = (price_df["HG=F"] / price_df["GC=F"]).dropna()
    curr_cg = float(cg_series.iloc[-1])
    ma200_cg_ser = cg_series.rolling(200).mean().dropna()
    ma200_cg = float(ma200_cg_ser.iloc[-1]) if not ma200_cg_ser.empty else curr_cg

    # --- 5. GSMI 评分算法 ---
    s_tips = 20 if curr_tips < 1.0 else (10 if curr_tips <= 2.0 else 0)
    s_dxy = 20 if curr_dxy < 100 else (10 if curr_dxy <= 105 else 0)
    s_cash = 30 if fms_cash > 5.0 else (15 if fms_cash >= 4.0 else 0)
    s_spread = 20 if curr_spread < 350 else (10 if curr_spread <= 500 else 0)
    s_cg = 10 if curr_cg > ma200_cg else 0
    gsmi_total = s_tips + s_dxy + s_cash + s_spread + s_cg

    # --- 6. UI 展示 ---

    # 顶部概览
    c_score, c_radar = st.columns([2, 1])
    with c_score:
        fig = go.Figure(go.Indicator(
            mode = "gauge+number", value = gsmi_total,
            title = {'text': f"GSMI 环境总分 (更新: {datetime.now().strftime('%m-%d')})", 'font': {'size': 20}},
            gauge = {
                'axis': {'range': [0, 100]}, 'bar': {'color': "#00ffcc"},
                'steps': [
                    {'range': [0, 40], 'color': "#441111"},
                    {'range': [40, 60], 'color': "#444411"},
                    {'range': [60, 80], 'color': "#114411"},
                    {'range': [80, 100], 'color': "#006644"}]
            }
        ))
        fig.update_layout(height=350, margin=dict(l=30, r=30, t=50, b=20), paper_bgcolor="#0e1117", font={'color': "white"})
        st.plotly_chart(fig, use_container_width=True)

    with c_radar:
        st.subheader("🚨 战术预警灯")
        status_map = {"冷清/低配": "🟢 低位安全", "标配": "🟡 中性观望", "极其拥挤": "🔴 警惕踩踏"}
        st.markdown(f"**关注目标: {target_name if target_name else '未设置'}**")
        st.title(status_map[target_sector_status])
        st.warning(f"全球最拥挤交易: **{fms_crowded}**")
        st.caption(f"FMS 调查日期: {fms_date}")

    # 分层详情
    st.markdown("---")
    t1, t2, t3, t4 = st.tabs(["💧 流动性 (Liquidity)", "🧠 情绪 (Sentiment)", "🏗️ 现实 (Reality)", "📈 执行确认 (Execution)"])

    with t1:
        col1, col2 = st.columns(2)
        col1.metric("10Y TIPS (实际利率)", f"{curr_tips:.2f}%", f"{curr_tips-prev_tips:.4f}", delta_color="inverse")
        col1.write("📊 **标准：** <1% 甜点区 (20分) | 1-2% 中性 (10分) | >2% 危险 (0分)")
        
        col2.metric("美元指数 (DXY)", f"{curr_dxy:.2f}", f"{curr_dxy-prev_dxy:.2f}", delta_color="inverse")
        col2.write("📊 **标准：** <100 爆发区 (20分) | 100-105 平衡 (10分) | >105 危险 (0分)")
        st.line_chart(price_df["DX-Y.NYB"].tail(90))

    with t2:
        m1, m2 = st.columns(2)
        m1.metric("FMS 机构现金水平", f"{fms_cash}%", delta="反向看多" if fms_cash > 5 else "反向减仓" if fms_cash < 4 else "中性")
        m1.write("📊 **标准：** >5% 底部信号 (30分) | 4-5% 中性 (15分) | <4% 顶部预警 (0分)")
        st.info(f"当前最拥挤交易：{fms_crowded}。大资金倾向于从拥挤处撤离，流向低配/冷清板块。")

    with t3:
        r1, r2 = st.columns(2)
        r1.metric("高收益债信用利差", f"{curr_spread:.0f} bps", f"{curr_spread-prev_spread:.0f}", delta_color="inverse")
        r1.write("📊 **标准：** <350 安全 (20分) | 350-500 警戒 (10分) | >500 危险 (0分)")
        
        r2.metric("铜金比趋势", f"{curr_cg:.4f}", f"{curr_cg > ma200_cg}")
        r2.write("📊 **标准：** >200日均线 扩张 (10分) | <200日均线 萎缩 (0分)")
        
        fig_cg = go.Figure()
        fig_cg.add_trace(go.Scatter(x=cg_series.index[-120:], y=cg_series.values[-120:], name="铜金比", line=dict(color='#00ffcc')))
        fig_cg.add_trace(go.Scatter(x=ma200_cg_ser.index[-120:], y=ma200_cg_ser.values[-120:], name="200MA", line=dict(dash='dash', color='white')))
        fig_cg.update_layout(height=300, template="plotly_dark", margin=dict(l=10, r=10, t=10, b=10))
        st.plotly_chart(fig_cg, use_container_width=True)

    with t4:
        e1, e2 = st.columns(2)
        e1.metric("港元汇率 (USD/HKD)", f"{curr_hkd:.4f}", 
                  delta="流出" if curr_hkd > 7.84 else ("流入" if curr_hkd < 7.78 else "平稳"))
        e1.write("📊 **标准：** 7.75 强力吸金 | 7.85 资金撤离")
        
        st.write("---")
        st.subheader("🛠️ 最终决策逻辑确认")
        n_flow = st.select_slider("A股资金流 (北向/主力)", ["大幅流出", "平稳", "大幅流入"], value="平稳")
        s_flow = st.select_slider("港股资金流 (南向/港元汇率)", ["大幅流出", "平稳", "大幅流入"], value="平稳")
        
        # 决策逻辑增强
        if gsmi_total >= 80 and n_flow == "大幅流入":
            st.success(f"🌟 **强烈推荐入场:** 环境总分极高 ({gsmi_total}) 且资金流共振。目标 [{target_name}] 胜率极大。")
        elif gsmi_total >= 60 and n_flow == "大幅流入":
            st.success(f"✅ **右侧确认:** 宏观环境转好，资金已开始实操买入。")
        elif gsmi_total >= 60 and n_flow == "大幅流出":
            st.warning(f"⚠️ **诱多警告:** 宏观分高但 A 股资金在撤离。可能是利好不涨，警惕陷阱。")
        elif gsmi_total < 40 and n_flow == "大幅流入":
            st.info(f"📉 **反弹性质:** 环境依然恶劣，此时流入多为短期抄底或护盘，不建议重仓。")
        elif gsmi_total < 40:
            st.error(f"❌ **防御模式:** 环境总分极低 ({gsmi_total})，建议持币观望，保护本金。")
        else:
            st.write("👉 请根据 GSMI 总分与实际资金流向的背离关系做出判断。")

except Exception as e:
    st.error(f"数据处理异常: {e}")

st.markdown("---")
st.caption("GSMI 逻辑系统 | 40% 流动性 + 30% 情绪 + 30% 现实。请定期更新侧边栏 FMS 数据。")
