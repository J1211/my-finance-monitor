import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timedelta
from fredapi import Fred

# --- 1. 界面配置 ---
st.set_page_config(page_title="GSMI Tactical | 宏观流动性雷达", layout="wide")

st.markdown("""
    <style>
    .main { background-color: #0e1117; }
    div[data-testid="stMetricValue"] { font-size: 32px; font-weight: bold; color: #00ffcc; }
    .standard-text { color: #aaa; font-size: 14px; margin-top: -10px; margin-bottom: 10px; font-weight: bold; }
    </style>
    """, unsafe_allow_html=True)

st.title("🏹 GSMI 全球聪明钱战术监控面板")

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
fms_date = st.sidebar.date_input("调查发布日期", datetime.now() - timedelta(days=15))
fms_cash = st.sidebar.slider("机构现金水平 (%)", 3.0, 6.5, 4.5, 0.1)
fms_crowded = st.sidebar.selectbox("当前最拥挤交易", ["美股大盘科技", "做空中国股票", "做多美元", "做多国债", "其他/无"])

st.sidebar.markdown("---")
st.sidebar.header("🎯 目标追踪")
target_name = st.sidebar.text_input("关注板块名称", "中概科技龙头")
target_status = st.sidebar.radio("该板块目前拥挤度", ["冷清/低配", "标配", "极其拥挤"])

# --- 3. 数据抓取与辅助函数 ---

@st.cache_data(ttl=3600)
def fetch_macro_data():
    end = datetime.now()
    start = end - timedelta(days=450)
    
    def safe_get_yf(ticker):
        try:
            df = yf.download(ticker, start=start, end=end, progress=False)
            if df.empty: return pd.Series()
            data = df['Close'] if 'Close' in df.columns else df
            if isinstance(data, pd.DataFrame):
                return data.iloc[:, 0].ffill().dropna()
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
    
    return tips, dxy, copper, gold, spread, hkd, hsi, as300

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

# --- 4. 评分引擎执行 ---

try:
    tips_ser, dxy_ser, copper_ser, gold_ser, spread_ser, hkd_ser, hsi_ser, as300_ser = fetch_macro_data()
    df_fed = fetch_fed_liquidity()

    if tips_ser.empty or dxy_ser.empty or df_fed.empty:
        st.error("❌ 核心数据抓取失败，请检查 API Key 或网络。")
        st.stop()

    # 1. 净流动性评分 (25分) - 及时性核心
    curr_nl = get_val(df_fed['net_liquidity'])
    ma4_nl = df_fed['net_liquidity'].rolling(20).mean().iloc[-1] # 4周均线
    prev_nl = df_fed['net_liquidity'].iloc[-6] # 约一周前
    
    s_nl_base = 15 if curr_nl > ma4_nl else 0  # 位置分
    s_nl_slope = 10 if curr_nl > prev_nl else 0 # 动能分（斜率向上）
    s_nl = s_nl_base + s_nl_slope

    # 2. TIPS 评分 (20分)
    # 0.5% (20分) -> 2.5% (0分)
    s_tips = score_linear(get_val(tips_ser), 0.5, 2.5, 20, reverse=True)

    # 3. DXY 评分 (15分)
    # 98 (15分) -> 108 (0分)
    s_dxy = score_linear(get_val(dxy_ser), 98, 108, 15, reverse=True)

    # 4. FMS Cash 评分 (15分)
    # 3.5% (0分) -> 6.0% (15分)
    s_cash = score_linear(fms_cash, 3.5, 6.0, 15, reverse=False)

    # 5. 铜金比趋势 (15分)
    if not copper_ser.empty and not gold_ser.empty:
        cg_ratio = (copper_ser / gold_ser).dropna()
        curr_cg = get_val(cg_ratio)
        ma200_cg = get_val(cg_ratio.rolling(200).mean())
        s_cg_base = 10 if curr_cg > ma200_cg else 0
        prev_cg_avg = float(cg_ratio.iloc[-10:-5].mean()) if len(cg_ratio)>10 else curr_cg
        s_cg_momo = 5 if curr_cg > prev_cg_avg else 0
        s_cg = s_cg_base + s_cg_momo
    else: s_cg = 0

    # 6. 利差评分 (10分)
    # 300bps (10分) -> 600bps (0分)
    s_spread = score_linear(get_val(spread_ser), 300, 600, 10, reverse=True)

    gsmi_total = s_nl + s_tips + s_dxy + s_cash + s_cg + s_spread

    # --- 5. UI 展示 ---

    with st.expander("📅 数据更新时间核对"):
        col_t1, col_t2, col_t3 = st.columns(3)
        col_t1.write(f"TIPS: {tips_ser.index[-1].strftime('%Y-%m-%d')}")
        col_t2.write(f"Fed Assets: {df_fed.index[-1].strftime('%Y-%m-%d')}")
        col_t3.write(f"DXY: {dxy_ser.index[-1].strftime('%m-%d %H:%M')}")

    c_score, c_radar = st.columns([2, 1])
    with c_score:
        fig = go.Figure(go.Indicator(
            mode = "gauge+number", value = gsmi_total,
            title = {'text': f"GSMI 战术总分 (25% NL + 20% TIPS)", 'font': {'size': 20}},
            gauge = {'axis': {'range': [0, 100]}, 'bar': {'color': "#00ffcc"},
                     'steps': [{'range': [0, 40], 'color': "#441111"}, {'range': [40, 60], 'color': "#444411"},
                               {'range': [60, 80], 'color': "#114411"}, {'range': [80, 100], 'color': "#006644"}]}
        ))
        fig.update_layout(height=350, margin=dict(l=30, r=30, t=50, b=20), paper_bgcolor="#0e1117", font={'color': "white"})
        st.plotly_chart(fig, use_container_width=True)

    with c_radar:
        st.subheader("🚨 实时战术预警")
        status_map = {"冷清/低配": "🟢 低位安全", "标配": "🟡 中性观望", "极其拥挤": "🔴 警惕踩踏"}
        st.markdown(f"**关注目标: {target_name}**")
        st.title(status_map[target_status])
        st.warning(f"FMS 最拥挤交易: {fms_crowded}")

    st.markdown("---")
    tabs = st.tabs(["💧 流动性水源 (45分)", "🧠 情绪/购买力 (15分)", "🏗️ 经济/现实 (25分)", "📉 执行确认"])

    with tabs[0]:
        st.subheader("🏦 核心：净流动性 & 扩缩表")
        m1, m2, m3 = st.columns(3)
        curr_a = df_fed['assets_t'].iloc[-1]
        m1.metric("美联储总资产", f"${curr_a:.2f}T", f"周变动: {curr_a - df_fed['assets_t'].iloc[-8]:+.3f}T")
        m2.metric("净流动性", f"${curr_nl:.2f}T", f"得分: {s_nl:.1f}/25")
        m3.metric("逆回购 (RRP)", f"${df_fed['rrp'].iloc[-1]/1000000:.2f}T", "流动性缓冲区")
        
        fig_fed = go.Figure()
        fig_fed.add_trace(go.Scatter(x=df_fed.index, y=df_fed['assets_t'], name="总资产(QT)", line=dict(color='#666', dash='dash')))
        fig_fed.add_trace(go.Scatter(x=df_fed.index, y=df_fed['net_liquidity'], name="净流动性", line=dict(color='#00ffcc', width=3), yaxis="y2"))
        fig_fed.update_layout(height=350, template="plotly_dark", hovermode="x unified",
                              yaxis=dict(title="总资产(T)", side="left"),
                              yaxis2=dict(title="净流动性(T)", side="right", overlaying="y", showgrid=False))
        st.plotly_chart(fig_fed, use_container_width=True)

        st.write("---")
        col1, col2 = st.columns(2)
        with col1:
            st.metric("10Y TIPS (实际利率)", f"{get_val(tips_ser):.2f}%", f"得分: {s_tips:.1f}/20")
            st.area_chart(tips_ser.tail(60), height=180)
        with col2:
            st.metric("美元指数 (DXY)", f"{get_val(dxy_ser):.2f}", f"得分: {s_dxy:.1f}/15")
            st.area_chart(dxy_ser.tail(60), height=180)

    with tabs[1]:
        st.metric("FMS 机构现金水平", f"{fms_cash}%", f"得分: {s_cash:.1f}/15")
        st.info(f"FMS 调查发布于 {fms_date}。注：月更指标，反映大趋势底部而非日内波动。")

    with tabs[2]:
        r1, r2 = st.columns(2)
        r1.metric("铜金比趋势", f"{curr_cg:.4f}", f"得分: {s_cg:.1f}/15")
        r2.metric("高收益债利差", f"{get_val(spread_ser):.0f} bps", f"得分: {s_spread:.1f}/10")
        if not copper_ser.empty:
            st.area_chart((copper_ser/gold_ser).tail(120), height=250)

    with tabs[3]:
        st.subheader("🌉 跨境流动性确认")
        hkd_val = get_val(hkd_ser)
        st.metric("港元汇率 (USD/HKD)", f"{hkd_val:.4f}", "吸金" if hkd_val < 7.80 else "失血")
        st.markdown(f"🔍 [点击查看 信贷脉冲指数](https://www.macromicro.me/collections/31/cn-finance-relative/35559/china-credit-impulse-index)")
        if not as300_ser.empty and not hsi_ser.empty:
            norm = (pd.concat([as300_ser, hsi_ser], axis=1).tail(20)).apply(lambda x: x/x.iloc[0]*100)
            st.write(f"📊 HSI vs AS300 动能差: {float(norm.iloc[-1,1]-norm.iloc[-1,0]):+.2f}%")

        st.markdown("---")
        if gsmi_total >= 75: st.success(f"🚀 **强烈看多** | 总分 {gsmi_total:.1f}。钱多且便宜。")
        elif gsmi_total <= 40: st.error(f"⚠️ **风险警示** | 总分 {gsmi_total:.1f}。流动性正在撤离。")
        else: st.warning(f"⚖️ **中性震荡** | 总分 {gsmi_total:.1f}。等待方向确认。")

except Exception as e:
    st.error(f"运行出错: {e}")

st.caption("GSMI Tactical | 核心计分：NetLiquidity(25) + TIPS(20) + DXY(15) + FMS(15) + CuAu(15) + Spread(10)")

