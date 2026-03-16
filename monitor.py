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

# --- 2. 侧边栏配置 (先定义变量防止NameError) ---
st.sidebar.header("🛠️ 核心参数配置")
target_name = st.sidebar.text_input("关注板块名称", "中概科技龙头")
target_status = st.sidebar.radio("该板块目前拥挤度", ["冷清/低配", "标配", "极其拥挤"])

# --- 月度手动更新区 ---
DEFAULT_FMS_CASH = 4.4  
DEFAULT_FMS_DATE = datetime(2026, 3, 13) 
crowded_options = ["美股大盘科技", "做多美元", "做空中国股票", "做多国债", "做多黄金", "其他"]
current_most_crowded = "做多黄金" 

st.sidebar.markdown("---")
st.sidebar.header("🗳️ BofA FMS 机构调查")
fms_cash = st.sidebar.slider("机构现金水平 (%)", 3.0, 6.5, DEFAULT_FMS_CASH, 0.1)
fms_date = st.sidebar.date_input("调查发布日期", DEFAULT_FMS_DATE)
fms_crowded = st.sidebar.selectbox(
    "当前最拥挤交易", 
    options=crowded_options, 
    index=crowded_options.index(current_most_crowded)
)

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

    # 抓取数据
    try:
        tips = fred.get_series('DFII10', start, end)
        spread = fred.get_series('BAMLH0A0HYM2', start, end)
        assets = fred.get_series('WALCL', start, end)
        tga = fred.get_series('WTREGEN', start, end)
        rrp = fred.get_series('RRPONTSYD', start, end)
    except:
        tips = spread = assets = tga = rrp = pd.Series()
    
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
    
    if not df.empty:
        df['nl'] = (df['assets'] - df['tga'] - df['rrp']) / 1000000
        df['cg_ratio'] = df['copper'] / df['gold']
    
    return df

def calculate_history(df, fms_val):
    if df.empty: return df
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
        s_cg = ((10 if df['cg_ratio'].iloc[i] > cg_ma200.iloc[i] else 0) if i > 200 else 0) + \
               (5 if df['cg_ratio'].iloc[i] > df['cg_ratio'].iloc[i-10:i-5].mean() else 0)
        # 6. Spread (10)
        s_spread = score_linear(df['spread'].iloc[i], 300, 600, 10, reverse=True)
        
        gsmi_history.append(s_nl + s_tips + s_dxy + s_cash + s_cg + s_spread)
    
    df['gsmi_score'] = gsmi_history
    return df

# --- 4. 逻辑执行 ---

try:
    df_raw = fetch_and_sync_data()
    
    # 【安全检查 1】如果 DataFrame 为空
    if df_raw.empty:
        st.error("❌ 无法获取完整宏观数据，请检查 API Key 或重试。")
        st.stop()
    
    df = calculate_history(df_raw, fms_cash)
    
    # 【安全检查 2】如果计算后仍无有效行
    if len(df) < 1:
        st.error("❌ 数据量不足以支持计算。")
        st.stop()

    latest = df.iloc[-1]
    gsmi_total = latest.get('gsmi_score', 0)

    # 提取显示用的最新单项分
    nl_ma4_last = df['nl'].rolling(20).mean().iloc[-1]
    s_nl_latest = (15 if latest['nl'] > nl_ma4_last else 0) + (10 if len(df)>6 and latest['nl'] > df['nl'].iloc[-6] else 0)
    cg_ma200_last = df['cg_ratio'].rolling(200).mean().iloc[-1]
    s_cg_latest = (10 if latest['cg_ratio'] > cg_ma200_last else 0) + (5 if len(df)>10 and latest['cg_ratio'] > df['cg_ratio'].iloc[-10:-5].mean() else 0)

    # --- 5. UI 展示 ---
    c1, c2 = st.columns([2, 1])
    with c1:
        fig_g = go.Figure(go.Indicator(
            mode = "gauge+number", value = gsmi_total if not np.isnan(gsmi_total) else 0,
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
        st.title(t_map.get(target_status, "🟡 中性观望"))
        st.warning(f"FMS 最拥挤交易: {fms_crowded}")

    st.markdown("---")
    tabs = st.tabs(["💧 流动性水源", "🧠 情绪与购买力", "🏗️ 现实与防线", "📊 系统验证与确认"])

    with tabs[0]:
        st.subheader("🏦 核心流动性水源 (NL + TIPS + DXY)")
        q1, q2, q3, q4 = st.columns(4)
        q1.markdown('<div class="quadrant-box">🔵 <b>25分: NL扩张期</b><br>🚀 进攻</div>', unsafe_allow_html=True)
        q2.markdown('<div class="quadrant-box">🟡 <b>15分: NL滞涨期</b><br>⚠️ 警惕</div>', unsafe_allow_html=True)
        q3.markdown('<div class="quadrant-box">🟠 <b>10分: NL修复期</b><br>🔍 观察</div>', unsafe_allow_html=True)
        q4.markdown('<div class="quadrant-box">🔴 <b>0分: NL衰退期</b><br>🛑 空仓</div>', unsafe_allow_html=True)

        m1, m2, m3 = st.columns(3)
        m1.metric("净流动性 (NL)", f"${latest['nl']:.2f}T", f"评分: {s_nl_latest}/25")
        m2.metric("10Y TIPS", f"{latest['tips']:.2f}%", f"评分: {score_linear(latest['tips'],0.5,2.5,20,True):.1f}/20")
        m3.metric("美元指数 (DXY)", f"{latest['dxy']:.2f}", f"评分: {score_linear(latest['dxy'],98,108,15,True):.1f}/15")
        
        fig_nl = go.Figure()
        fig_nl.add_trace(go.Scatter(x=df.index, y=df['nl'], name="净流动性(T)", line=dict(color='#00ffcc', width=3)))
        fig_nl.add_trace(go.Scatter(x=df.index, y=df['tips'], name="TIPS (%)", line=dict(color='#FF3131', dash='dot'), yaxis="y2"))
        fig_nl.update_layout(height=350, template="plotly_dark", yaxis=dict(title="NL (T)"), yaxis2=dict(overlaying="y", side="right", showgrid=False))
        st.plotly_chart(fig_nl, use_container_width=True)

    with tabs[1]:
        st.subheader("🧠 情绪与购买力 (BTC 28日情绪分布)")
        e1, e2 = st.columns([1, 2])
        with e1:
            st.metric("FMS 机构现金水平", f"{fms_cash}%", f"得分: {score_linear(fms_cash,3.5,6.0,15):.1f}/15")
            st.write("---")
            if len(df) > 28:
                btc_ret = df['btc'].pct_change() * 100
                last_28d = btc_ret.tail(28)
                pos_days = len(last_28d[last_28d > 0])
                neg_days = len(last_28d[last_28d < 0])
                st.write("**BTC 28日情绪扫描**")
                st.caption(f"📈 上涨天数: {pos_days} | 📉 下跌天数: {neg_days}")
                if pos_days >= 18: st.success("🔥 投机情绪极度活跃")
                elif neg_days >= 18: st.error("❄️ 流动性极度低迷")
                else: st.info("⚖️ 风险偏好震荡中")
            else: st.info("正在积累 BTC 情绪数据...")
        
        with e2:
            if len(df) > 28:
                colors = ['#00ffcc' if x > 0 else '#FF3131' for x in last_28d]
                fig_btc_dist = go.Figure(go.Bar(x=last_28d.index, y=last_28d.values, marker_color=colors))
                fig_btc_dist.update_layout(height=250, template="plotly_dark", title="BTC 28日波动脉搏 (%)", margin=dict(l=10, r=10, t=40, b=10))
                st.plotly_chart(fig_btc_dist, use_container_width=True)
            
        st.write("**BTC 120日宏观趋势 (金丝雀价格线)**")
        st.line_chart(df['btc'].tail(120), height=200)

    with tabs[2]:
        st.subheader("🏗️ 现实增长与信用防线")
        r1, r2 = st.columns(2)
        r1.metric("铜金比趋势", f"{latest['cg_ratio']:.4f}", f"评分: {s_cg_latest}/15")
        r2.metric("高收益债利差", f"{latest['spread']:.0f} bps", f"评分: {score_linear(latest['spread'],300,600,10,True):.1f}/10")
        st.area_chart(df['cg_ratio'].tail(120), height=250)

    with tabs[3]:
        st.subheader("📊 系统有效性验证 (GSMI vs Nasdaq 周度版)")
        
        # 这里的 W-FRI 是关键：重采样到每周五，解决频率错位
        df_weekly = df.resample('W-FRI').last().dropna(subset=['gsmi_score', 'qqq'])
        
        if not df_weekly.empty and len(df_weekly) > 1:
            norm_qqq = (df_weekly['qqq'] / df_weekly['qqq'].iloc[0]) * 100
            fig_v = go.Figure()
            fig_v.add_trace(go.Scatter(x=df_weekly.index, y=df_weekly['gsmi_score'], name="GSMI 每周五评分", line=dict(color='#00ffcc', width=4), mode='lines+markers'))
            fig_v.add_trace(go.Scatter(x=df_weekly.index, y=norm_qqq, name="纳指 QQQ (归一化)", line=dict(color='#FFD700', dash='dot'), yaxis="y2"))
            fig_v.update_layout(height=400, template="plotly_dark", yaxis=dict(title="GSMI 分数", range=[0,100]), yaxis2=dict(overlaying="y", side="right", showgrid=False))
            st.plotly_chart(fig_v, use_container_width=True)
            
            # 周五实战提醒
            if datetime.now().weekday() == 4:
                st.info("💡 **周五实战提醒：**\n当前 GSMI 已包含今晨更新的 NL 数据，而 QQQ 仍为昨夜收盘价。")
        else:
            st.warning("数据积累中，暂无法生成周度对比图...")
        
        st.markdown("---")
        st.subheader("🌉 最后执行确认")
        hk1, hk2 = st.columns(2)
        with hk1:
            st.metric("港元汇率 (USD/HKD)", f"{latest['hkd']:.4f}", "吸金" if latest['hkd'] < 7.80 else "失血")
            if len(df) > 20:
                hsi_perf = (latest['hsi']/df['hsi'].iloc[-20] - 1)*100
                as300_perf = (latest['as300']/df['as300'].iloc[-20] - 1)*100
                st.write(f"📊 20日动能差 HSI vs AS300: {hsi_perf - as300_perf:+.2f}%")
        with hk2:
            st.markdown(f"🔍 [AASTOCKS 沽空比率](http://www.aastocks.com/tc/stocks/market/shortselling/securities-eligible.aspx)")
            st.markdown(f"🔍 [MacroMicro 中国信贷脉冲](https://www.macromicro.me/collections/31/cn-finance-relative/35559/china-credit-impulse-index)")
            st.slider("手动录入：大市沽空比率 (%)", 5.0, 35.0, 16.5, 0.1)

except Exception as e:
    st.error(f"发生索引错误: {e}。通常由于数据抓取不足导致，请尝试刷新。")

st.markdown("---")
st.caption("GSMI Tactical | 45% 核心货币 (NL+TIPS) + 15% 全球汇率 (DXY) + 15% 机构情绪 (FMS) + 25% 宏观现实 (CuAu+Spread)")
