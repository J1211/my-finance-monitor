import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timedelta
from fredapi import Fred

# --- 1. 界面配置 ---
st.set_page_config(page_title="GSMI Tactical | 宏观流动性监控", layout="wide")

st.markdown("""
    <style>
    .main { background-color: #0e1117; }
    div[data-testid="stMetricValue"] { font-size: 30px; font-weight: bold; color: #00ffcc; }
    .standard-text { color: #aaa; font-size: 14px; margin-top: -10px; margin-bottom: 10px; font-weight: bold; }
    .quadrant-box { padding: 12px; border-radius: 5px; border: 1px solid #333; background-color: #1a1c24; text-align: center; min-height: 60px;}
    </style>
    """, unsafe_allow_html=True)

st.title("🏹 GSMI 全球聪明钱战术监控面板")

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
    **1. 净流动性 (25分):**  
    高于4周均线(+15) / 环比增加(+10)  
    
    **2. 实际利率 TIPS (20分):**  
    0.5%(满分) -> 2.5%(0分) 线性  
    
    **3. 美元指数 DXY (15分):**  
    98(满分) -> 108(0分) 线性  
    
    **4. FMS 机构现金 (15分):**  
    6.0%(满分) -> 3.5%(0分) 线性  
    
    **5. 铜金比趋势 (15分):**  
    高于200日线(+10) / 近5日向上(+5)  
    
    **6. 信用利差 (10分):**  
    300bps(满分) -> 600bps(0分) 线性
    """)

if not fred_key:
    st.warning("请在侧边栏配置 FRED API Key。")
    st.stop()

fred = Fred(api_key=fred_key)

# --- 3. 数据抓取与辅助函数 ---

@st.cache_data(ttl=3600)
def fetch_macro_data():
    end = datetime.now()
    start = end - timedelta(days=500)
    
    def safe_get_yf(ticker):
        try:
            df = yf.download(ticker, start=start, end=end, progress=False)
            if df.empty: return pd.Series()
            data = df['Close'] if 'Close' in df.columns else df.iloc[:, 0]
            if isinstance(data, pd.DataFrame): data = data.iloc[:, 0]
            return data.ffill().dropna()
        except: return pd.Series()

    try:
        tips = fred.get_series('DFII10', start, end).ffill().dropna()
        spread = fred.get_series('BAMLH0A0HYM2', start, end).ffill().dropna()
    except: tips, spread = pd.Series(), pd.Series()

    dxy = safe_get_yf("DX-Y.NYB")
    copper = safe_get_yf("HG=F")
    gold = safe_get_yf("GC=F")
    hkd = safe_get_yf("HKD=X")
    hsi = safe_get_yf("^HSI")
    as300 = safe_get_yf("000300.SS")
    btc = safe_get_yf("BTC-USD")
    return tips, dxy, copper, gold, spread, hkd, hsi, as300, btc

@st.cache_data(ttl=3600)
def fetch_fed_liquidity():
    end = datetime.now()
    start = end - timedelta(days=500)
    try:
        assets = fred.get_series('WALCL', start, end)
        tga = fred.get_series('WTREGEN', start, end)
        rrp = fred.get_series('RRPONTSYD', start, end)
        df = pd.concat([assets, tga, rrp], axis=1).ffill().dropna()
        df.columns = ['assets', 'tga', 'rrp']
        df['net_liquidity'] = (df['assets'] - df['tga'] - df['rrp']) / 1000000
        df['assets_t'] = df['assets'] / 1000000
        return df
    except: return pd.DataFrame()

def get_val(obj, pos=-1, default=0.0):
    if obj is None: return default
    if isinstance(obj, (int, float)): return float(obj)
    if isinstance(obj, pd.Series):
        if obj.empty: return default
        try: return float(obj.iloc[pos])
        except: return default
    return default

def score_linear(val, min_val, max_val, max_score, reverse=False):
    if not reverse:
        score = (val - min_val) / (max_val - min_val) * max_score
    else:
        score = (max_val - val) / (max_val - min_val) * max_score
    return max(0, min(max_score, score))

# --- 4. 逻辑执行 ---

try:
    tips_ser, dxy_ser, copper_ser, gold_ser, spread_ser, hkd_ser, hsi_ser, as300_ser, btc_ser = fetch_macro_data()
    df_fed = fetch_fed_liquidity()

    if tips_ser.empty or dxy_ser.empty or df_fed.empty:
        st.error("数据抓取不完整，请检查 Key 或刷新。")
        st.stop()

    # 1. NL 评分
    curr_nl = get_val(df_fed['net_liquidity'])
    ma4_nl = df_fed['net_liquidity'].rolling(20).mean().iloc[-1]
    prev_nl = df_fed['net_liquidity'].iloc[-6]
    s_nl = (15 if curr_nl > ma4_nl else 0) + (10 if curr_nl > prev_nl else 0)

    # 其他评分
    s_tips = score_linear(get_val(tips_ser), 0.5, 2.5, 20, reverse=True)
    s_dxy = score_linear(get_val(dxy_ser), 98, 108, 15, reverse=True)
    s_cash = score_linear(fms_cash, 3.5, 6.0, 15, reverse=False)
    s_spread = score_linear(get_val(spread_ser), 300, 600, 10, reverse=True)

    if not copper_ser.empty and not gold_ser.empty:
        cg_ratio = (copper_ser / gold_ser).dropna()
        curr_cg = get_val(cg_ratio)
        ma200_cg = get_val(cg_ratio.rolling(200).mean())
        s_cg = (10 if curr_cg > ma200_cg else 0) + (5 if len(cg_ratio)>10 and curr_cg > cg_ratio.iloc[-10:-5].mean() else 0)
    else: s_cg = 0

    gsmi_total = s_nl + s_tips + s_dxy + s_cash + s_cg + s_spread

    # --- 5. UI 展示 ---
    c1, c2 = st.columns([2, 1])
    with c1:
        fig = go.Figure(go.Indicator(
            mode = "gauge+number", value = gsmi_total,
            title = {'text': f"GSMI 战术总分 (最后行情: {tips_ser.index[-1].strftime('%m-%d')})", 'font': {'size': 20}},
            gauge = {'axis': {'range': [0, 100]}, 'bar': {'color': "#00ffcc"},
                     'steps': [{'range': [0, 40], 'color': "#441111"}, {'range': [40, 60], 'color': "#444411"},
                               {'range': [60, 80], 'color': "#114411"}, {'range': [80, 100], 'color': "#006644"}]}
        ))
        fig.update_layout(height=350, margin=dict(l=30, r=30, t=50, b=20), paper_bgcolor="#0e1117", font={'color': "white"})
        st.plotly_chart(fig, use_container_width=True)

    with c2:
        st.subheader("🚨 实时战术预警")
        t_map = {"冷清/低配": "🟢 低位安全", "标配": "🟡 中性观望", "极其拥挤": "🔴 警惕踩踏"}
        st.markdown(f"**关注目标: {target_name}**")
        st.title(t_map[target_status])
        st.warning(f"FMS 最拥挤交易: {fms_crowded}")

    st.markdown("---")
    tabs = st.tabs(["💧 流动性水源 (宏观三要素)", "🧠 情绪与购买力", "🏗️ 现实与防线", "📉 执行确认"])

    with tabs[0]:
        st.subheader("🏦 核心流动性 (NL + TIPS + DXY)")
        # NL 四象限简洁说明
        q1, q2, q3, q4 = st.columns(4)
        q1.markdown('<div class="quadrant-box">🔵 <b>25分: 扩张期</b> (水位高+放水中) 🚀 进攻</div>', unsafe_allow_html=True)
        q2.markdown('<div class="quadrant-box">🟡 <b>15分: 滞涨期</b> (水位高+放水慢) ⚠️ 警惕</div>', unsafe_allow_html=True)
        q3.markdown('<div class="quadrant-box">🟠 <b>10分: 修复期</b> (水位低+放水启) 🔍 观察</div>', unsafe_allow_html=True)
        q4.markdown('<div class="quadrant-box">🔴 <b>0分: 衰退期</b> (水位低+漏水中) 🛑 空仓</div>', unsafe_allow_html=True)

        m1, m2, m3 = st.columns(3)
        m1.metric("净流动性 (NL)", f"${curr_nl:.2f}T", f"评分: {s_nl}/25")
        m2.metric("10Y TIPS (实际利率)", f"{get_val(tips_ser):.2f}%", f"评分: {s_tips:.1f}/20")
        m3.metric("美元指数 (DXY)", f"{get_val(dxy_ser):.2f}", f"评分: {s_dxy:.1f}/15")
        
        # NL 图表
        fig_nl = go.Figure()
        fig_nl.add_trace(go.Scatter(x=df_fed.index, y=df_fed['net_liquidity'], name="净流动性(T)", line=dict(color='#00ffcc', width=3)))
        fig_nl.add_trace(go.Scatter(x=tips_ser.index, y=tips_ser.values, name="TIPS (%)", line=dict(color='#FF3131', dash='dot'), yaxis="y2"))
        fig_nl.update_layout(height=350, template="plotly_dark", hovermode="x unified",
                             legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                             yaxis=dict(title="净流动性(T)", side="left"),
                             yaxis2=dict(title="TIPS(%)", side="right", overlaying="y", showgrid=False))
        st.plotly_chart(fig_nl, use_container_width=True)

    with tabs[1]:
        st.subheader("🧠 情绪与购买力监控")
        e1, e2 = st.columns(2)
        with e1:
            st.metric("FMS 机构现金水平", f"{fms_cash}%", f"得分: {s_cash:.1f}/15")
            st.area_chart(dxy_ser.tail(90), height=200) # 用DXY做情绪背景
        with e2:
            st.metric("比特币 (BTC) - 金丝雀", f"${get_val(btc_ser)/1000:.1f}k", f"周: {(get_val(btc_ser)/get_val(btc_ser, -7)-1)*100:+.1f}%")
            st.line_chart(btc_ser.tail(90), height=200)

    with tabs[2]:
        st.subheader("🏗️ 现实增长与信用防线")
        r1, r2 = st.columns(2)
        with r1:
            st.metric("铜金比趋势", f"{curr_cg:.4f}", f"得分: {s_cg:.1f}/15")
            if not copper_ser.empty: st.area_chart(cg_ratio.tail(120), height=200)
        with r2:
            st.metric("高收益债利差", f"{get_val(spread_ser):.0f} bps", f"得分: {s_spread:.1f}/10")
            st.line_chart(spread_ser.tail(120), height=200)

    with tabs[3]:
        st.subheader("🌉 跨境执行确认")
        hk1, hk2 = st.columns(2)
        with hk1:
            hkd_val = get_val(hkd_ser)
            st.metric("港元汇率 (USD/HKD)", f"{hkd_val:.4f}", "吸金" if hkd_val < 7.80 else "失血")
        with hk2:
            hk_short = st.slider("手动录入：大市沽空比率 (%)", 5.0, 35.0, 16.5, 0.1)

        if not as300_ser.empty and not hsi_ser.empty:
            norm = (pd.concat([as300_ser, hsi_ser], axis=1).tail(20)).apply(lambda x: x/x.iloc[0]*100)
            st.write(f"📊 动能对比 HSI vs AS300: {float(norm.iloc[-1,1]-norm.iloc[-1,0]):+.2f}%")
            
        st.markdown("---")
        if gsmi_total >= 75: st.success(f"🚀 **环境极其安全** | 总分 {gsmi_total:.1f}")
        elif gsmi_total <= 40: st.error(f"⚠️ **风险极高** | 总分 {gsmi_total:.1f}")
        else: st.warning(f"⚖️ **中性区域** | 总分 {gsmi_total:.1f}")

except Exception as e:
    st.error(f"系统错误: {e}")

st.caption("GSMI Tactical | 数据源: FRED, yfinance. (Fed Assets 周期性延迟同步)")
