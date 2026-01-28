import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timedelta
from fredapi import Fred

# --- 1. 配置与初始化 ---
st.set_page_config(page_title="GSMI | 全球聪明钱监控面板", layout="wide")

# 强制深色风格自定义 CSS
st.markdown("""
    <style>
    .main { background-color: #0e1117; }
    div[data-testid="stMetricValue"] { font-size: 28px; }
    </style>
    """, unsafe_allow_html=True)

st.title("🏹 全球聪明钱指数 (GSMI) 投资前瞻看板")

# --- 2. 侧边栏：参数输入与 FMS 配置 ---
st.sidebar.header("🛠️ 核心参数配置")

# API Key 处理
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

# --- 3. 数据抓取与处理函数 ---

@st.cache_data(ttl=3600)
def fetch_data():
    end = datetime.now()
    # 抓取一年数据以计算200日均线
    start = end - timedelta(days=365)
    
    # FRED 数据
    tips = fred.get_series('DFII10', start, end)
    spread = fred.get_series('BAMLH0A0HYM2', start, end)
    
    # Yahoo Finance 数据
    tickers = {
        "DXY": "DX-Y.NYB",
        "Copper": "HG=F",
        "Gold": "GC=F",
        "HKD": "HKD=X"
    }
    df = yf.download(list(tickers.values()), start=start, end=end, progress=False)['Close']
    
    return tips, df, spread

try:
    tips_ser, price_df, spread_ser = fetch_data()

    # --- 4. GSMI 评分引擎算法 ---
    
    # A. 流动性分 (40分)
    current_tips = float(tips_ser.iloc[-1])
    score_tips = 20 if current_tips < 1.0 else (10 if current_tips <= 2.0 else 0)
    
    current_dxy = float(price_df["DX-Y.NYB"].iloc[-1])
    score_dxy = 20 if current_dxy < 100 else (10 if current_dxy <= 105 else 0)
    
    # B. 机构情绪分 (30分)
    score_cash = 30 if fms_cash > 5.0 else (15 if fms_cash >= 4.0 else 0)
    
    # C. 经济现实分 (30分)
    current_spread = float(spread_ser.iloc[-1])
    score_spread = 20 if current_spread < 350 else (10 if current_spread <= 500 else 0)
    
    # 铜金比与200日均线
    cg_ratio = price_df["HG=F"] / price_df["GC=F"]
    current_cg = cg_ratio.iloc[-1]
    ma200_cg = cg_ratio.rolling(200).mean().iloc[-1]
    score_cg = 10 if current_cg > ma200_cg else 0
    
    gsmi_total = score_tips + score_dxy + score_cash + score_spread + score_cg

    # --- 5. UI 顶部概览区 ---
    col_score, col_radar = st.columns([2, 1])
    
    with col_score:
        fig_gauge = go.Figure(go.Indicator(
            mode = "gauge+number",
            value = gsmi_total,
            title = {'text': "GSMI 全球聪明钱环境总分"},
            gauge = {
                'axis': {'range': [0, 100]},
                'bar': {'color': "#00ffcc"},
                'steps': [
                    {'range': [0, 40], 'color': "#550000"},
                    {'range': [40, 60], 'color': "#555500"},
                    {'range': [60, 80], 'color': "#005500"},
                    {'range': [80, 100], 'color': "#00aa00"}
                ]
            }
        ))
        fig_gauge.update_layout(height=350, margin=dict(l=20, r=20, t=50, b=20))
        st.plotly_chart(fig_gauge, use_container_width=True)

    with col_radar:
        st.subheader("🚨 战术预警灯")
        status_colors = {"冷清/低配": "🟢 低位安全", "标配": "🟡 中性观望", "极其拥挤": "🔴 极度拥挤/警惕踩踏"}
        st.markdown(f"**关注板块状态：**")
        st.title(status_colors[target_sector_status])
        st.info(f"FMS 最拥挤交易: \n\n **{fms_crowded}**")
        st.caption(f"数据发布日期: {fms_date}")

    st.markdown("---")

    # --- 6. 分层详细监控 ---
    tab1, tab2, tab3, tab4 = st.tabs(["💧 流动性层", "🧠 情绪层", "🏗️ 现实层", "📉 执行确认"])

    with tab1:
        c1, c2 = st.columns(2)
        tips_delta = current_tips - tips_ser.iloc[-5]
        dxy_delta = current_dxy - price_df["DX-Y.NYB"].iloc[-5]
        
        c1.metric("10Y TIPS (实际利率)", f"{current_tips:.2f}%", f"{tips_delta:.4f}", delta_color="inverse")
        c1.caption("标准: <1% 甜点区 | >2% 危险区")
        
        c2.metric("美元指数 (DXY)", f"{current_dxy:.2f}", f"{dxy_delta:.2f}", delta_color="inverse")
        c2.caption("标准: <100 爆发区 | >105 危险区")
        
        st.line_chart(price_df["DX-Y.NYB"].tail(60))

    with tab2:
        m1, m2 = st.columns(2)
        m1.metric("FMS 现金水平", f"{fms_cash}%", delta="反向看多" if fms_cash > 5 else "反向警告" if fms_cash < 4 else "中性")
        m2.write(f"**本月大资金偏好：** 正在从 {fms_crowded} 寻找下一站。")
        # 这里可以加入更多手动录入的 FMS 细节描述

    with tab3:
        r1, r2 = st.columns(2)
        spread_delta = current_spread - spread_ser.iloc[-5]
        r1.metric("高收益债信用利差", f"{current_spread:.0f} bps", f"{spread_delta:.0f}", delta_color="inverse")
        r1.caption("标准: <350 安全 | >500 危险")
        
        cg_delta = current_cg - cg_ratio.iloc[-5]
        r2.metric("铜金比 (相对均线)", f"{current_cg:.4f}", f"{cg_delta:.4f}")
        r2.write("🟢 扩张期" if current_cg > ma200_cg else "🔴 萎缩期")
        
        fig_cg = go.Figure()
        fig_cg.add_trace(go.Scatter(x=cg_ratio.index[-120:], y=cg_ratio.values[-120:], name="铜金比"))
        fig_cg.add_trace(go.Scatter(x=cg_ratio.index[-120:], y=cg_ratio.rolling(200).mean().values[-120:], name="200日均线", line=dict(dash='dash')))
        st.plotly_chart(fig_cg, use_container_width=True)

    with tab4:
        e1, e2 = st.columns(2)
        current_hkd = float(price_df["HKD=X"].iloc[-1])
        e1.metric("港元汇率 (USD/HKD)", f"{current_hkd:.4f}", 
                  delta="资金流出" if current_hkd > 7.83 else ("资金流入" if current_hkd < 7.78 else "平稳"))
        e1.caption("7.75 强方限制 | 7.85 弱方限制")
        
        st.write("**资金流手动确认 (建议参考北向/南向每日累计数据):**")
        north_flow = st.select_slider("北向资金 (近5日趋势)", ["大幅流出", "小幅流出", "持平", "小幅流入", "大幅流入"], value="持平")
        south_flow = st.select_slider("南向资金 (近5日趋势)", ["大幅流出", "小幅流出", "持平", "小幅流入", "大幅流入"], value="持平")
        
        if north_flow == "大幅流入" and gsmi_total > 60:
            st.success("✅ 宏观与 A 股资金流共振，入场时机成熟")
        elif current_hkd > 7.84:
            st.error("⚠️ 港元汇率触及弱方，警惕港股失血风险")

except Exception as e:
    st.error(f"面板运行异常: {e}")
    st.info("排查建议：检查 FRED API Key 是否正确，或网络是否能访问 Yahoo Finance。")

st.markdown("---")
st.caption(f"GSMI 指引：0-40 防御 | 40-60 观察 | 60-80 乐观 | 80-100 全面看多。 投资有风险，决策需谨慎。")
