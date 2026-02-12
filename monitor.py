import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime, timedelta
from fredapi import Fred

# --- 1. 界面配置 ---
st.set_page_config(page_title="GSMI Tactical | 宏观精密监控", layout="wide")

st.markdown("""
    <style>
    .main { background-color: #0e1117; }
    div[data-testid="stMetricValue"] { font-size: 30px; font-weight: bold; color: #00ffcc; }
    .standard-text { color: #aaa; font-size: 14px; margin-top: -10px; margin-bottom: 10px; font-weight: bold; }
    .quadrant-box { padding: 12px; border-radius: 5px; border: 1px solid #333; background-color: #1a1c24; text-align: center; min-height: 70px;}
    </style>
    """, unsafe_allow_html=True)

st.title("🏹 GSMI 全球聪明钱监控与验证系统")

# --- 2. 侧边栏配置 ---
st.sidebar.header("🛠️ 核心参数配置")
target_name = st.sidebar.text_input("关注板块名称", "中概科技龙头")
target_status = st.sidebar.radio("该板块目前拥挤度", ["冷清/低配", "标配", "极其拥挤"])

st.sidebar.markdown("---")
st.sidebar.header("🗳️ BofA FMS 机构调查")
fms_date = st.sidebar.date_input("调查发布日期", datetime.now() - timedelta(days=15))
fms_cash = st.sidebar.slider("机构现金水平 (%)", 3.0, 6.5, 4.5, 0.1)
fms_crowded = st.sidebar.selectbox("当前最拥挤交易", ["美股大盘科技", "做空中国股票", "做多美元", "做多国债", "其他"])

st.sidebar.markdown("---")
if "fred_api_key" in st.secrets:
    fred_key = st.secrets["fred_api_key"]
else:
    fred_key = st.sidebar.text_input("FRED API Key", type="password")

with st.sidebar.expander("📖 GSMI 评分规则细则"):
    st.markdown("""
    **1. 核心货币 (45分):**  
    - NL > 4周均线 (+15)  
    - NL 环比增加 (+10)  
    - TIPS 0.5%->2.5% (20分线性)  
    
    **2. 全球汇率 (15分):**  
    - DXY 98->108 (15分线性)  
    
    **3. 机构情绪 (15分):**  
    - FMS 6.0%->3.5% (15分线性)  
    
    **4. 宏观现实 (25分):**  
    - 铜金比 > 200日线 (+10)  
    - 铜金比 近5日向上 (+5)  
    - 利差 300->600bps (10分线性)
    """)

if not fred_key:
    st.warning("请在侧边栏配置 FRED API Key。")
    st.stop()

fred = Fred(api_key=fred_key)

# --- 3. 数据处理函数 ---

def score_linear(val, min_val, max_val, max_score, reverse=False):
    if not reverse:
        score = (val - min_val) / (max_val - min_val) * max_score
    else:
        score = (max_val - val) / (max_val - min_val) * max_score
    return max(0, min(max_score, score))

@st.cache_data(ttl=3600)
def fetch_and_sync_data():
    end = datetime.now()
    start = end - timedelta(days=500)
    
    def safe_get_yf(ticker):
        try:
            df = yf.download(ticker, start=start, end=end, progress=False)
            if df.empty: return pd.Series()
            if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
            return df['Close'].ffill()
        except: return pd.Series()

    tips = fred.get_series('DFII10', start, end)
    spread = fred.get_series('BAMLH0A0HYM2', start, end)
    assets = fred.get_series('WALCL', start, end)
    tga = fred.get_series('WTREGEN', start, end)
    rrp = fred.get_series('RRPONTSYD', start, end)
    
    dxy = safe_get_yf("DX-Y.NYB")
    copper = safe_get_yf("HG=F")
    gold = safe_get_yf("GC=F")
    hkd = safe_get_yf("HKD=X")
    hsi = safe_get_yf("^HSI")
    as300 = safe_get_yf("000300.SS")
    btc = safe_get_yf("BTC-USD")
    qqq = safe_get_yf("QQQ")

    df = pd.DataFrame({
        'tips': tips, 'spread': spread, 'assets': assets, 'tga': tga, 'rrp': rrp,
        'dxy': dxy, 'copper': copper, 'gold': gold, 'hkd': hkd, 'hsi': hsi, 'as300': as300, 'btc': btc, 'qqq': qqq
    }).ffill().dropna()
    
    df['nl'] = (df['assets'] - df['tga'] - df['rrp']) / 1000000
    df['cg_ratio'] = df['copper'] / df['gold']
    
    return df

def calculate_history(df, fms_val):
    gsmi_history = []
    nl_ma4 = df['nl'].rolling(20).mean()
    cg_ma200 = df['cg_ratio'].rolling(200).mean()
    
    for i in range(len(df)):
        if i < 20:
            gsmi_history.append(np.nan)
            continue
        
        # 1. NL (25)
        s_nl = (15 if df['nl'].iloc[i] > nl_ma4.iloc[i] else 0) + (10 if df['nl'].iloc[i] > df['nl'].iloc[i-5] else 0)
        # 2. TIPS (20)
        s_tips = score_linear(df['tips'].iloc[i], 0.5, 2.5, 20, reverse=True)
        # 3. DXY (15)
        s_dxy = score_linear(df['dxy'].iloc[i], 98, 108, 15, reverse=True)
        # 4. FMS (15)
        s_cash = score_linear(fms_val, 3.5, 6.0, 15, reverse=False)
        # 5. CG (15)
        s_cg = (10 if df['cg_ratio'].iloc[i] > cg_ma200.iloc[i] else 0) if i > 200 else 0
        s_cg += 5 if df['cg_ratio'].iloc[i] > df['cg_ratio'].iloc[i-10:i-5].mean() else 0
        # 6. Spread (10)
        s_spread = score_linear(df['spread'].iloc[i], 300, 600, 10, reverse=True)
        
        gsmi_history.append(s_nl + s_tips + s_dxy + s_cash + s_cg + s_spread)
    
    df['gsmi_score'] = gsmi_history
    return df

# --- 4. 逻辑执行 ---

try:
    df_raw = fetch_and_sync_data()
    df = calculate_history(df_raw, fms_cash)
    latest = df.iloc[-1]
    gsmi_total = latest['gsmi_score']

    # --- 5. UI 展示 ---
    c1, c2 = st.columns([2, 1])
    with c1:
        fig_g = go.Figure(go.Indicator(
            mode = "gauge+number", value = gsmi_total,
            title = {'text': f"GSMI 战术总分 ({df.index[-1].strftime('%m-%d')})", 'font': {'size': 20}},
            gauge = {'axis': {'range': [0, 100]}, 'bar': {'color': "#00ffcc"},
                     'steps': [{'range': [0, 40], 'color': "#441111"}, {'range': [40, 60], 'color': "#444411"},
                               {'range': [60, 80], 'color': "#114411"}, {'range': [80, 100], 'color': "#006644"}]}
        ))
        fig_g.update_layout(height=350, margin=dict(l=30, r=30, t=50, b=20), paper_bgcolor="#0e1117", font={'color': "white"})
        st.plotly_chart(fig_g, use_container_width=True)

    with c2:
        st.subheader("🚨 实时战术预警")
        t_map = {"冷清/低配": "🟢 低位安全", "标配": "🟡 中性观望", "极其拥挤": "🔴 警惕踩踏"}
        st.markdown(f"**关注目标: {target_name}**")
        st.title(t_map[target_status])
        st.warning(f"FMS 最拥挤交易: {fms_crowded}")

    st.markdown("---")
    tabs = st.tabs(["💧 流动性水源 (宏观三要素)", "🧠 情绪与购买力", "🏗️ 现实与防线", "📈 系统验证与确认"])

    with tabs[0]:
        st.subheader("🏦 核心流动性水源 (NL + TIPS + DXY)")
        q1, q2, q3, q4 = st.columns(4)
        q1.markdown('<div class="quadrant-box">🔵 <b>25分: NL扩张期</b><br>(水位高+放水中) 🚀 进攻</div>', unsafe_allow_html=True)
        q2.markdown('<div class="quadrant-box">🟡 <b>15分: NL滞涨期</b><br>(水位高+放水慢) ⚠️ 警惕</div>', unsafe_allow_html=True)
        q3.markdown('<div class="quadrant-box">🟠 <b>10分: NL修复期</b><br>(水位低+放水启) 🔍 观察</div>', unsafe_allow_html=True)
        q4.markdown('<div class="quadrant-box">🔴 <b>0分: NL衰退期</b><br>(水位低+漏水中) 🛑 空仓</div>', unsafe_allow_html=True)

        m1, m2, m3 = st.columns(3)
        m1.metric("净流动性 (NL)", f"${latest['nl']:.2f}T", f"周变: {latest['nl'] - df['nl'].iloc[-6]:+.3f}T")
        m2.metric("10Y TIPS (实际利率)", f"{latest['tips']:.2f}%", f"评分: {score_linear(latest['tips'],0.5,2.5,20,True):.1f}/20")
        m3.metric("美元指数 (DXY)", f"{latest['dxy']:.2f}", f"评分: {score_linear(latest['dxy'],98,108,15,True):.1f}/15")
        
        fig_nl = go.Figure()
        fig_nl.add_trace(go.Scatter(x=df.index, y=df['nl'], name="净流动性(T)", line=dict(color='#00ffcc', width=3)))
        fig_nl.add_trace(go.Scatter(x=df.index, y=df['tips'], name="TIPS (%)", line=dict(color='#FF3131', dash='dot'), yaxis="y2"))
        fig_nl.update_layout(height=350, template="plotly_dark", yaxis=dict(title="NL (T)"), yaxis2=dict(overlaying="y", side="right", showgrid=False))
        st.plotly_chart(fig_nl, use_container_width=True)

    with tabs[1]:
        st.subheader("🧠 情绪与购买力监控")
        e1, e2 = st.columns(2)
        with e1:
            st.metric("FMS 机构现金水平", f"{fms_cash}%", f"得分: {score_linear(fms_cash,3.5,6.0,15):.1f}/15")
            st.area_chart(df['dxy'].tail(90), height=200) 
        with e2:
            st.metric("比特币 (BTC) - 金丝雀", f"${latest['btc']/1000:.1f}k", f"周: {(latest['btc']/df['btc'].iloc[-7]-1)*100:+.1f}%")
            st.line_chart(df['btc'].tail(90), height=200)

    with tabs[2]:
        st.subheader("🏗️ 现实增长与信用防线")
        r1, r2 = st.columns(2)
        with r1:
            st.metric("铜金比趋势", f"{latest['cg_ratio']:.4f}", "高于200MA" if latest['cg_ratio'] > df['cg_ratio'].rolling(200).mean().iloc[-1] else "低于200MA")
            st.area_chart(df['cg_ratio'].tail(120), height=200)
        with r2:
            st.metric("高收益债利差", f"{latest['spread']:.0f} bps", f"得分: {score_linear(latest['spread'],300,600,10,True):.1f}/10")
            st.line_chart(df['spread'].tail(120), height=200)

    with tabs[3]:
        st.subheader("📈 系统有效性验证 (GSMI vs Nasdaq)")
        plot_df = df.tail(120).copy()
        norm_qqq = (plot_df['qqq'] / plot_df['qqq'].iloc[0]) * 100
        fig_v = go.Figure()
        fig_v.add_trace(go.Scatter(x=plot_df.index, y=plot_df['gsmi_score'], name="GSMI 历史评分", line=dict(color='#00ffcc', width=3)))
        fig_v.add_trace(go.Scatter(x=plot_df.index, y=norm_qqq, name="纳指 QQQ (归一化)", line=dict(color='#FFD700', dash='dot'), yaxis="y2"))
        fig_v.update_layout(height=400, template="plotly_dark", yaxis=dict(title="GSMI 分数", range=[0,100]), yaxis2=dict(overlaying="y", side="right", showgrid=False))
        st.plotly_chart(fig_v, use_container_width=True)
        
        st.markdown("---")
        st.subheader("🌉 最后执行确认")
        hk1, hk2 = st.columns(2)
        with hk1:
            st.metric("港元汇率 (USD/HKD)", f"{latest['hkd']:.4f}", "吸金" if latest['hkd'] < 7.80 else "失血")
            st.write(f"📊 动能对比 HSI vs AS300: {float((latest['hsi']/df['hsi'].iloc[-20] - latest['as300']/df['as300'].iloc[-20])*100):+.2f}%")
        with hk2:
            st.markdown(f"🔍 [AASTOCKS 沽空比率](http://www.aastocks.com/tc/stocks/market/shortselling/securities-eligible.aspx)")
            st.markdown(f"🔍 [MacroMicro 中国信贷脉冲](https://www.macromicro.me/collections/31/cn-finance-relative/35559/china-credit-impulse-index)")
            st.slider("手动录入：大市沽空比率 (%)", 5.0, 35.0, 16.5, 0.1)

except Exception as e:
    st.error(f"系统运行错误: {e}")

st.markdown("---")
st.caption("GSMI Tactical | 45% 核心货币 (NL+TIPS) + 15% 全球汇率 (DXY) + 15% 机构情绪 (FMS) + 25% 宏观现实 (CuAu+Spread)")
