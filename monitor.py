import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timedelta
from fredapi import Fred

# --- 1. 界面配置与美化 ---
st.set_page_config(page_title="GSMI | 精密宏观监控面板", layout="wide")

st.markdown("""
    <style>
    .main { background-color: #0e1117; }
    div[data-testid="stMetricValue"] { font-size: 32px; font-weight: bold; color: #00ffcc; }
    .standard-text { color: #aaa; font-size: 14px; margin-top: -10px; margin-bottom: 10px; font-weight: bold; }
    </style>
    """, unsafe_allow_html=True)

st.title("🏹 GSMI 全球聪明钱精密监控面板")

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

    tips = fred.get_series('DFII10', start, end).ffill().dropna()
    spread = fred.get_series('BAMLH0A0HYM2', start, end).ffill().dropna()
    dxy = safe_get_yf("DX-Y.NYB")
    copper = safe_get_yf("HG=F")
    gold = safe_get_yf("GC=F")
    hkd = safe_get_yf("HKD=X")
    hsi = safe_get_yf("^HSI")
    as300 = safe_get_yf("000300.SS")
    
    return tips, dxy, copper, gold, spread, hkd, hsi, as300

def get_val(ser, pos=-1, default=0.0):
    if ser is None or len(ser) == 0: return default
    try:
        return float(ser.iloc[pos])
    except: return default

# --- 4. 核心评分引擎 (线性插值逻辑) ---

def score_linear(val, min_val, max_val, max_score, reverse=False):
    """
    val: 当前值
    min_val: 对应分数为 0 (或 100) 的边界
    max_val: 对应分数为 100 (或 0) 的边界
    max_score: 该项指标的总权重分
    reverse: 如果为True，值越大分数越低
    """
    if not reverse:
        score = (val - min_val) / (max_val - min_val) * max_score
    else:
        score = (max_val - val) / (max_val - min_val) * max_score
    return max(0, min(max_score, score))

# --- 5. 逻辑执行 ---

try:
    tips_ser, dxy_ser, copper_ser, gold_ser, spread_ser, hkd_ser, hsi_ser, as300_ser = fetch_macro_data()

    # 1. 流动性评分 (TIPS & DXY)
    curr_tips = get_val(tips_ser)
    # TIPS: 0.5% (25分) -> 2.5% (0分)
    s_tips = score_linear(curr_tips, 0.5, 2.5, 25, reverse=True)
    
    curr_dxy = get_val(dxy_ser)
    # DXY: 98 (20分) -> 108 (0分)
    s_dxy = score_linear(curr_dxy, 98, 108, 20, reverse=True)

    # 2. 情绪评分 (FMS Cash)
    # Cash: 3.5% (0分) -> 6.0% (25分)
    s_cash = score_linear(fms_cash, 3.5, 6.0, 25, reverse=False)

    # 3. 现实评分 (Spread & Copper/Gold)
    curr_spread = get_val(spread_ser)
    # Spread: 300bps (15分) -> 600bps (0分)
    s_spread = score_linear(curr_spread, 300, 600, 15, reverse=True)

# 铜金比趋势评分
    if not copper_ser.empty and not gold_ser.empty:
        cg_ratio = (copper_ser / gold_ser).dropna()
        curr_cg = get_val(cg_ratio)
        ma200_cg_ser = cg_ratio.rolling(200).mean().dropna()
        ma200_cg = get_val(ma200_cg_ser, -1, curr_cg)
        
        # 基础分：高于200MA得10分
        s_cg_base = 10 if curr_cg > ma200_cg else 0
        
        # 动能分：近5日均值对比（修正此处报错）
        if len(cg_ratio) > 10:
            prev_cg_avg = cg_ratio.iloc[-10:-5].mean() # 直接取均值，不再传给 get_val
            s_cg_momo = 5 if curr_cg > prev_cg_avg else 0
        else:
            s_cg_momo = 0
            
        s_cg = s_cg_base + s_cg_momo
    else:
        curr_cg, ma200_cg, s_cg = 0.0, 0.0, 0

    gsmi_total = s_tips + s_dxy + s_cash + s_spread + s_cg

    # --- 6. UI 展示 ---

    c_score, c_radar = st.columns([2, 1])
    with c_score:
        market_time = dxy_ser.index[-1].strftime('%m-%d %H:%M')
        fig = go.Figure(go.Indicator(
            mode = "gauge+number", value = gsmi_total,
            title = {'text': f"GSMI 精密总分 (最后行情: {market_time})", 'font': {'size': 20}},
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
    tabs = st.tabs(["💧 流动性 (45分)", "🧠 情绪 (25分)", "🏗️ 现实 (30分)", "📉 执行确认"])

    with tabs[0]:
        col1, col2 = st.columns(2)
        with col1:
            st.metric("10Y TIPS (实际利率)", f"{curr_tips:.2f}%", f"得分: {s_tips:.1f}/25")
            st.markdown('<p class="standard-text">线性评分: 0.5%(满分) -> 2.5%(0分)</p>', unsafe_allow_html=True)
            st.area_chart(tips_ser.tail(90), height=200)
        with col2:
            st.metric("美元指数 (DXY)", f"{curr_dxy:.2f}", f"得分: {s_dxy:.1f}/20")
            st.markdown('<p class="standard-text">线性评分: 98(满分) -> 108(0分)</p>', unsafe_allow_html=True)
            st.area_chart(dxy_ser.tail(90), height=200)

    with tabs[1]:
        m1, m2 = st.columns(2)
        with m1:
            st.metric("FMS 机构现金水平", f"{fms_cash}%", f"得分: {s_cash:.1f}/25")
            st.markdown('<p class="standard-text">线性评分: 6.0%(满分) -> 3.5%(0分)</p>', unsafe_allow_html=True)
        with m2: 
            st.info(f"月更调查日期: {fms_date}\n\n当前市场情绪得分占比反映了机构‘潜在买入购买力’。")

    with tabs[2]:
        r1, r2 = st.columns(2)
        with r1:
            st.metric("高收益债利差", f"{curr_spread:.0f} bps", f"得分: {s_spread:.1f}/15")
            st.markdown('<p class="standard-text">线性评分: 300bps(满分) -> 600bps(0分)</p>', unsafe_allow_html=True)
        with r2:
            st.metric("铜金比趋势", f"{curr_cg:.4f}", f"得分: {s_cg:.1f}/15")
            st.markdown('<p class="standard-text">规则: >200MA(10分) + 动能向上(5分)</p>', unsafe_allow_html=True)
        
        fig_cg = go.Figure()
        fig_cg.add_trace(go.Scatter(x=cg_ratio.index[-120:], y=cg_ratio.values[-120:], name="铜金比", line=dict(color='#00ffcc')))
        fig_cg.add_trace(go.Scatter(x=ma200_cg_ser.index[-120:], y=ma200_cg_ser.values[-120:], name="200MA", line=dict(dash='dash', color='white')))
        fig_cg.update_layout(height=300, template="plotly_dark", margin=dict(l=10, r=10, t=10, b=10))
        st.plotly_chart(fig_cg, use_container_width=True)

    with tabs[3]:
        # (保持原有的港股流动性与执行确认逻辑...)
        st.subheader("🌉 港股与跨境流动性确认")
        curr_hkd = get_val(hkd_ser)
        e1, e2 = st.columns(2)
        with e1:
            fx_tag = "吸金" if curr_hkd < 7.78 else ("失血" if curr_hkd > 7.84 else "平稳")
            st.metric("港元汇率 (USD/HKD)", f"{curr_hkd:.4f}", fx_tag)
        
        with e2:
            st.markdown(f"🔍 [点击查看 AASTOCKS 大市沽空比率](http://www.aastocks.com/tc/stocks/market/shortselling/securities-eligible.aspx)")
            hk_short_ratio = st.slider("手动录入：大市沽空比率 (%)", 5.0, 35.0, 16.5, 0.1)
        
        if not as300_ser.empty and not hsi_ser.empty:
            comb = pd.concat([as300_ser, hsi_ser], axis=1).ffill().bfill().tail(20)
            comb.columns = ["AS300", "HSI"]
            norm = (comb / comb.iloc[0]) * 100
            gap = float(norm["HSI"].iloc[-1] - norm["AS300"].iloc[-1])
            
            st.write(f"📊 相对强度对比：近20日 HSI vs AS300 动能差: {gap:+.2f}%")
            
            # 自动决策建议
            st.markdown("---")
            st.subheader("🤖 GSMI 系统自动决策建议")
            if gsmi_total >= 70:
                st.success(f"✅ **环境极其安全** | 总分 {gsmi_total:.1f}。建议积极寻找买点。")
            elif gsmi_total <= 40:
                st.error(f"❌ **环境极其危险** | 总分 {gsmi_total:.1f}。建议空仓或对冲。")
            else:
                st.warning(f"⚖️ **环境中性磨底** | 总分 {gsmi_total:.1f}。轻仓博弈，等待趋势确认。")

except Exception as e:
    st.error(f"发生错误: {e}")

st.markdown("---")
st.caption("GSMI 精密评分版 | 逻辑：25% TIPS + 20% DXY + 25% FMS + 15% Spread + 15% Copper/Gold。")


