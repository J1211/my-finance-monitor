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
    div[data-testid="stMetricValue"] { font-size: 32px; font-weight: bold; color: #00ffcc; }
    .standard-text { color: #aaa; font-size: 14px; margin-top: -10px; margin-bottom: 10px; font-weight: bold; }
    .quadrant-box { padding: 10px; border-radius: 5px; border: 1px solid #333; background-color: #1a1c24; margin-bottom: 10px; min-height: 100px;}
    </style>
    """, unsafe_allow_html=True)

st.title("🏹 GSMI 全球聪明钱战术监控面板")

# --- 2. 侧边栏配置 (先定义所有变量) ---
st.sidebar.header("🛠️ 核心参数配置")

# A. 基础输入（先定义，防止 NameError）
target_name = st.sidebar.text_input("关注板块名称", "中概科技龙头")
target_status = st.sidebar.radio("该板块目前拥挤度", ["冷清/低配", "标配", "极其拥挤"])

st.sidebar.markdown("---")
st.sidebar.header("🗳️ BofA FMS 机构调查 (月更)")
fms_date = st.sidebar.date_input("调查发布日期", datetime.now() - timedelta(days=15))
fms_cash = st.sidebar.slider("机构现金水平 (%)", 3.0, 6.5, 4.5, 0.1)
fms_crowded = st.sidebar.selectbox("当前最拥挤交易", ["美股大盘科技", "做空中国股票", "做多美元", "做多国债", "其他/无"])

st.sidebar.markdown("---")
# B. FRED Key 检查
if "fred_api_key" in st.secrets:
    fred_key = st.secrets["fred_api_key"]
else:
    fred_key = st.sidebar.text_input("FRED API Key", type="password")

with st.sidebar.expander("📖 GSMI 评分规则细则"):
    st.write("""
    **1. 净流动性 (25分):** 
    - 高于4周均线 (+15)
    - 本周环比增加 (+10)
    **2. 实际利率 TIPS (20分):**
    - 0.5%(满分) -> 2.5%(0分) 线性
    **3. 美元指数 DXY (15分):**
    - 98(满分) -> 108(0分) 线性
    **4. FMS 机构现金 (15分):**
    - 6.0%(满分) -> 3.5%(0分) 线性
    **5. 铜金比趋势 (15分):**
    - 高于200日均线 (+10)
    - 近5日动能向上 (+5)
    **6. 信用利差 (10分):**
    - 300bps(满分) -> 600bps(0分) 线性
    """)

# 熔断机制：如果没有 Key，提示并停止
if not fred_key:
    st.warning("请在侧边栏配置 FRED API Key 以加载数据。")
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
            # 兼容 yfinance 的新旧版本列名
            data = df['Close'] if 'Close' in df.columns else df.iloc[:, 0]
            if isinstance(data, pd.DataFrame): data = data.iloc[:, 0]
            return data.ffill().dropna()
        except: return pd.Series()

    try:
        tips = fred.get_series('DFII10', start, end).ffill().dropna()
        spread = fred.get_series('BAMLH0A0HYM2', start, end).ffill().dropna()
    except:
        tips, spread = pd.Series(), pd.Series()

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
        df = pd.concat([assets, tga, rrp], axis=1)
        df.columns = ['assets', 'tga', 'rrp']
        df = df.ffill().dropna()
        df['net_liquidity'] = (df['assets'] - df['tga'] - df['rrp']) / 1000000
        df['assets_t'] = df['assets'] / 1000000
        return df
    except:
        return pd.DataFrame()

def get_val(obj, pos=-1, default=0.0):
    if obj is None: return default
    if isinstance(obj, (int, float)): return float(obj)
    if isinstance(obj, pd.Series):
        if obj.empty: return default
        try: return float(obj.iloc[pos])
        except: return default
    try: return float(obj)
    except: return default

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
        st.error("❌ 数据源响应异常。请确认网络环境或 FRED API Key。")
        st.stop()

    # 1. 净流动性评分 (25分)
    curr_nl = get_val(df_fed['net_liquidity'])
    ma4_nl = df_fed['net_liquidity'].rolling(20).mean().iloc[-1]
    prev_nl = df_fed['net_liquidity'].iloc[-6] 
    s_nl = (15 if curr_nl > ma4_nl else 0) + (10 if curr_nl > prev_nl else 0)

    # 其他指标评分
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

    # A. 日期核对
    with st.expander("📅 数据更新时间核对"):
        col_t1, col_t2, col_t3 = st.columns(3)
        col_t1.write(f"TIPS: {tips_ser.index[-1].strftime('%Y-%m-%d')}")
        col_t2.write(f"Fed Assets: {df_fed.index[-1].strftime('%Y-%m-%d')}")
        col_t3.write(f"Market: {dxy_ser.index[-1].strftime('%m-%d %H:%M')}")

    # B. 主仪表盘
    c_score, c_radar = st.columns([2, 1])
    with c_score:
        fig = go.Figure(go.Indicator(
            mode = "gauge+number", value = gsmi_total,
            title = {'text': f"GSMI 战术总分 (最后行情: {tips_ser.index[-1].strftime('%m-%d')})", 'font': {'size': 20}},
            gauge = {'axis': {'range': [0, 100]}, 'bar': {'color': "#00ffcc"},
                     'steps': [{'range': [0, 40], 'color': "#441111"}, {'range': [40, 60], 'color': "#444411"},
                               {'range': [60, 80], 'color': "#114411"}, {'range': [80, 100], 'color': "#006644"}]}
        ))
        fig.update_layout(height=350, margin=dict(l=30, r=30, t=50, b=20), paper_bgcolor="#0e1117", font={'color': "white"})
        st.plotly_chart(fig, use_container_width=True)

    with c_radar:
        st.subheader("🚨 实时战术预警")
        target_map = {"冷清/低配": "🟢 低位安全", "标配": "🟡 中性观望", "极其拥挤": "🔴 警惕踩踏"}
        st.markdown(f"**关注目标: {target_name}**")
        st.title(target_map[target_status])
        st.warning(f"FMS 最拥挤交易: {fms_crowded}")

    st.markdown("---")
    tabs = st.tabs(["💧 流动性水源", "🧠 情绪/购买力", "🏗️ 经济/现实", "📉 执行确认"])

    with tabs[0]:
        st.subheader("🏦 净流动性 (NL) 四象限监控")
        q1, q2, q3, q4 = st.columns(4)
        q1.markdown('<div class="quadrant-box"><b>🔵 25分: 扩张期</b><br>水位高+放水中<br>🚀 <b>进攻</b></div>', unsafe_allow_html=True)
        q2.markdown('<div class="quadrant-box"><b>🟡 15分: 滞涨期</b><br>水位高+放水慢<br>⚠️ <b>警惕</b></div>', unsafe_allow_html=True)
        q3.markdown('<div class="quadrant-box"><b>🟠 10分: 修复期</b><br>水位低+放水启<br>🔍 <b>观察</b></div>', unsafe_allow_html=True)
        q4.markdown('<div class="quadrant-box"><b>🔴 0分: 衰退期</b><br>水位低+漏水中<br>🛑 <b>空仓</b></div>', unsafe_allow_html=True)

        m1, m2, m3 = st.columns(3)
        m1.metric("净流动性 (NL)", f"${curr_nl:.2f}T", f"评分: {s_nl}/25")
        m2.metric("比特币 (BTC)", f"${get_val(btc_ser)/1000:.1f}k", f"周变化: {(get_val(btc_ser)/get_val(btc_ser, -7)-1)*100:+.1f}%")
        m3.metric("逆回购 (RRP)", f"${df_fed['rrp'].iloc[-1]/1000000:.2f}T", "流动性缓冲垫")

        fig_nl = go.Figure()
        fig_nl.add_trace(go.Scatter(x=df_fed.index, y=df_fed['net_liquidity'], name="净流动性(T)", line=dict(color='#00ffcc', width=3)))
        fig_nl.add_trace(go.Scatter(x=btc_ser.index, y=btc_ser.values/10000, name="BTC价格(x10k)", line=dict(color='#ffd700', dash='dot'), yaxis="y2"))
        fig_nl.update_layout(height=400, template="plotly_dark", hovermode="x unified",
                             yaxis=dict(title="净流动性(T)", side="left"),
                             yaxis2=dict(title="BTC(x10k)", side="right", overlaying="y", showgrid=False))
        st.plotly_chart(fig_nl, use_container_width=True)

    with tabs[1]:
        col_1, col_2 = st.columns(2)
        with col_1:
            st.metric("10Y TIPS (实际利率)", f"{get_val(tips_ser):.2f}%", f"得分: {s_tips:.1f}/20")
            st.area_chart(tips_ser.tail(90), height=200)
        with col_2:
            st.metric("FMS 机构现金水平", f"{fms_cash}%", f"得分: {s_cash:.1f}/15")
            st.info(f"FMS 最后更新: {fms_date}")

    with tabs[2]:
        r1, r2 = st.columns(2)
        r1.metric("美元指数 (DXY)", f"{get_val(dxy_ser):.2f}", f"得分: {s_dxy:.1f}/15")
        r2.metric("铜金比趋势", f"{curr_cg:.4f}", f"得分: {s_cg:.1f}/15")
        st.write("---")
        st.metric("高收益债利差", f"{get_val(spread_ser):.0f} bps", f"得分: {s_spread:.1f}/10")

    with tabs[3]:
        st.subheader("🌉 跨境流动性确认")
        hkd_val = get_val(hkd_ser)
        st.metric("港元汇率 (USD/HKD)", f"{hkd_val:.4f}", "吸金" if hkd_val < 7.80 else "失血")
        if not as300_ser.empty and not hsi_ser.empty:
            norm = (pd.concat([as300_ser, hsi_ser], axis=1).tail(20)).apply(lambda x: x/x.iloc[0]*100)
            st.write(f"📊 动能差 HSI vs AS300: {float(norm.iloc[-1,1]-norm.iloc[-1,0]):+.2f}%")

        st.markdown("---")
        if gsmi_total >= 75: st.success(f"🌟 **环境极其安全** | 总分 {gsmi_total:.1f}")
        elif gsmi_total <= 40: st.error(f"⚠️ **风险极高** | 总分 {gsmi_total:.1f}")
        else: st.warning(f"⚖️ **中性区域** | 总分 {gsmi_total:.1f}")

except Exception as e:
    st.error(f"系统运行错误: {e}")

st.caption("GSMI Tactical Version | 45% 流动性 + 25% 现实 + 15% 情绪 + 15% 汇率。数据仅供参考。")
