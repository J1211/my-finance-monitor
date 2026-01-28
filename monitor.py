import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timedelta
from fredapi import Fred
import requests
from bs4 import BeautifulSoup
import re

# --- 1. 界面配置与美化 ---
st.set_page_config(page_title="GSMI | 全球聪明钱监控面板", layout="wide")

st.markdown("""
    <style>
    .main { background-color: #0e1117; }
    div[data-testid="stMetricValue"] { font-size: 32px; font-weight: bold; color: #00ffcc; }
    .stTabs [data-baseweb="tab-list"] { gap: 20px; }
    .stTabs [data-baseweb="tab"] { height: 50px; font-size: 16px; }
    .standard-text { color: #888; font-size: 14px; margin-top: -10px; margin-bottom: 10px; }
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
fms_date = st.sidebar.date_input("调查发布日期", datetime.now() - timedelta(days=15))
fms_cash = st.sidebar.slider("机构现金水平 (%)", 3.0, 6.5, 4.5, 0.1)
fms_crowded = st.sidebar.selectbox("当前最拥挤交易", ["美股大盘科技", "做空中国股票", "做多美元", "做多国债", "其他/无"])

st.sidebar.markdown("---")
st.sidebar.header("🎯 目标追踪")
target_name = st.sidebar.text_input("关注板块名称", "中概 AI 龙头")
target_status = st.sidebar.radio("该板块目前拥挤度", ["冷清/低配", "标配", "极其拥挤"])

# --- 3. 数据抓取与安全提取函数 ---

@st.cache_data(ttl=3600)
def fetch_macro_data():
    end = datetime.now()
    start = end - timedelta(days=450)
    
    def safe_get_yf(ticker):
        try:
            df = yf.download(ticker, start=start, end=end, progress=False)
            if df.empty: return pd.Series()
            # 处理 MultiIndex
            data = df['Close'] if 'Close' in df.columns else df
            if isinstance(data, pd.DataFrame):
                return data.iloc[:, 0].ffill().dropna()
            return data.ffill().dropna()
        except:
            return pd.Series()

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
        if abs(pos) > len(ser): return float(ser.iloc[0])
        return float(ser.iloc[pos])
    except: return default

def scrape_sl886_short_ratio():
    """尝试从 sl886.com 抓取大市沽空比率"""
    url = "https://www.sl886.com/shortsell"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            # 寻找包含“大市沽空比率”或类似的文本
            text = soup.get_text()
            # 匹配百分比，通常紧跟在大市沽空比率后面
            match = re.search(r'大市沽空比率[:\s]*(\d+\.\d+)%', text)
            if match:
                return float(match.group(1))
    except:
        pass
    return None

# --- 4. 逻辑执行与评分算法 ---

try:
    tips_ser, dxy_ser, copper_ser, gold_ser, spread_ser, hkd_ser, hsi_ser, as300_ser = fetch_macro_data()

    curr_tips = get_val(tips_ser, -1)
    prev_tips = get_val(tips_ser, -5)
    curr_dxy = get_val(dxy_ser, -1)
    prev_dxy = get_val(dxy_ser, -5)
    curr_spread = get_val(spread_ser, -1)
    prev_spread = get_val(spread_ser, -5)
    curr_hkd = get_val(hkd_ser, -1)
    
    if not copper_ser.empty and not gold_ser.empty:
        cg_ratio = (copper_ser / gold_ser).dropna()
        curr_cg = get_val(cg_ratio, -1)
        ma200_cg_ser = cg_ratio.rolling(200).mean().dropna()
        ma200_cg = get_val(ma200_cg_ser, -1, curr_cg)
    else:
        curr_cg, ma200_cg = 0.0, 0.0

    # GSMI 评分
    s_tips = 20 if curr_tips < 1.0 else (10 if curr_tips <= 2.0 else 0)
    s_dxy = 20 if curr_dxy < 100 else (10 if curr_dxy <= 105 else 0)
    s_cash = 30 if fms_cash > 5.0 else (15 if fms_cash >= 4.0 else 0)
    s_spread = 20 if curr_spread < 350 else (10 if curr_spread <= 500 else 0)
    s_cg = 10 if curr_cg > ma200_cg and curr_cg > 0 else 0
    gsmi_total = s_tips + s_dxy + s_cash + s_spread + s_cg

    # --- 5. UI 展示 ---

    c_score, c_radar = st.columns([2, 1])
    with c_score:
        fig = go.Figure(go.Indicator(
            mode = "gauge+number", value = gsmi_total,
            title = {'text': f"GSMI 环境总分 ({datetime.now().strftime('%m-%d')})", 'font': {'size': 20}},
            gauge = {'axis': {'range': [0, 100]}, 'bar': {'color': "#00ffcc"},
                     'steps': [{'range': [0, 40], 'color': "#441111"}, {'range': [40, 60], 'color': "#444411"},
                               {'range': [60, 80], 'color': "#114411"}, {'range': [80, 100], 'color': "#006644"}]}
        ))
        fig.update_layout(height=350, margin=dict(l=30, r=30, t=50, b=20), paper_bgcolor="#0e1117", font={'color': "white"})
        st.plotly_chart(fig, use_container_width=True)

    with c_radar:
        st.subheader("🚨 战术预警灯")
        status_map = {"冷清/低配": "🟢 低位安全", "标配": "🟡 中性观望", "极其拥挤": "🔴 警惕踩踏"}
        st.markdown(f"**关注目标: {target_name}**")
        st.title(status_map[target_status])
        st.warning(f"最拥挤交易: {fms_crowded}")

    st.markdown("---")
    tabs = st.tabs(["💧 流动性", "🧠 情绪", "🏗️ 现实", "📉 执行确认"])

    with tabs[0]:
        col1, col2 = st.columns(2)
        with col1:
            st.metric("10Y TIPS (实际利率)", f"{curr_tips:.2f}%", f"{curr_tips-prev_tips:.4f}", delta_color="inverse")
            st.markdown('<p class="standard-text">📊 标准: <1% 甜点 (20分) | 1-2% 中性 (10分) | >2% 危险 (0分)</p>', unsafe_allow_html=True)
            if not tips_ser.empty: st.area_chart(tips_ser.tail(90), height=200)
        with col2:
            st.metric("美元指数 (DXY)", f"{curr_dxy:.2f}", f"{curr_dxy-prev_dxy:.2f}", delta_color="inverse")
            st.markdown('<p class="standard-text">📊 标准: <100 爆发 (20分) | 100-105 平衡 (10分) | >105 危险 (0分)</p>', unsafe_allow_html=True)
            if not dxy_ser.empty: st.area_chart(dxy_ser.tail(90), height=200)

    with tabs[1]:
        m1, m2 = st.columns(2)
        with m1:
            st.metric("FMS 机构现金水平", f"{fms_cash}%", delta="看多" if fms_cash > 5 else "警示" if fms_cash < 4 else "中性")
            st.markdown('<p class="standard-text">📊 标准: >5% 底部信号 (30分) | 4-5% 中性 (15分) | <4% 顶部预警 (0分)</p>', unsafe_allow_html=True)
        with m2: st.info(f"发布日期: {fms_date}。最拥挤交易: {fms_crowded}。")

    with tabs[2]:
        r1, r2 = st.columns(2)
        with r1:
            st.metric("高收益债利差", f"{curr_spread:.0f} bps", f"{curr_spread-prev_spread:.0f}", delta_color="inverse")
            st.markdown('<p class="standard-text">📊 标准: <350 安全 (20分) | 350-500 警戒 (10分) | >500 危险 (0分)</p>', unsafe_allow_html=True)
        with r2:
            st.metric("铜金比趋势", f"{curr_cg:.4f}", "高于200MA" if curr_cg > ma200_cg else "低于200MA")
            st.markdown('<p class="standard-text">📊 标准: >200日均线 扩张 (10分) | <200日均线 萎缩 (0分)</p>', unsafe_allow_html=True)
        if not cg_ratio.empty:
            fig_cg = go.Figure()
            fig_cg.add_trace(go.Scatter(x=cg_ratio.index[-120:], y=cg_ratio.values[-120:], name="铜金比", line=dict(color='#00ffcc')))
            fig_cg.add_trace(go.Scatter(x=ma200_cg_ser.index[-120:], y=ma200_cg_ser.values[-120:], name="200MA", line=dict(dash='dash', color='white')))
            fig_cg.update_layout(height=300, template="plotly_dark", margin=dict(l=10, r=10, t=10, b=10))
            st.plotly_chart(fig_cg, use_container_width=True)

    with tabs[3]:
        st.subheader("🌉 港股与跨境流动性确认")
        e1, e2 = st.columns(2)
        with e1:
            fx_tag = "吸金" if curr_hkd < 7.78 else ("失血" if curr_hkd > 7.84 else "平稳")
            st.metric("港元汇率 (USD/HKD)", f"{curr_hkd:.4f}", fx_tag, delta_color="normal" if curr_hkd < 7.80 else "inverse")
            st.markdown('<p class="standard-text">📊 标准: 7.75 强方限制 | 7.85 弱方限制</p>', unsafe_allow_html=True)
        
        with e2:
            # 尝试抓取 sl886
            sl_val = scrape_sl886_short_ratio()
            st.markdown(f"🔍 [点击查看 SL886 实时沽空比率](https://www.sl886.com/shortsell)")
            if sl_val:
                st.write(f"✅ 自动尝试抓取 SL886 成功: {sl_val}%")
                hk_short_ratio = st.slider("大盘沽空比率 (%)", 5.0, 35.0, sl_val, 0.1)
            else:
                st.warning("自动抓取 SL886 受阻，请点击上方链接并手动输入")
                hk_short_ratio = st.slider("手动录入：大盘沽空比率 (%)", 5.0, 35.0, 16.5, 0.1)
            st.caption("注: >18% 易触发空头挤压爆发")

        st.write("---")
        st.subheader("📊 A股 vs 港股 相对强度对比 (近20日)")
        if not as300_ser.empty and not hsi_ser.empty:
            comb = pd.concat([as300_ser, hsi_ser], axis=1).ffill().bfill().tail(20)
            comb.columns = ["AS300", "HSI"]
            norm = (comb / comb.iloc[0]) * 100
            y_min, y_max = norm.min().min(), norm.max().max()
            
            fig_dual = go.Figure()
            fig_dual.add_shape(type="line", x0=norm.index[0], x1=norm.index[-1], y0=100, y1=100, line=dict(color="white", width=1, dash="dot"))
            fig_dual.add_trace(go.Scatter(x=norm.index, y=norm["AS300"], name="A股 (沪深300)", line=dict(color='#FF3131', width=4)))
            fig_dual.add_trace(go.Scatter(x=norm.index, y=norm["HSI"], name="港股 (恒生指数)", line=dict(color='#00D4FF', width=4)))
            
            gap = float(norm["HSI"].iloc[-1] - norm["AS300"].iloc[-1])
            fig_dual.update_layout(height=450, template="plotly_dark", hovermode="x unified",
                                   yaxis=dict(title="收益率 (100=基准)", tickformat=".1f", dtick=2, range=[y_min-1, y_max+1]),
                                   legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
            fig_dual.add_annotation(x=norm.index[-1], y=norm["HSI"].iloc[-1], text=f" 动能差: {gap:+.2f}%", 
                                    showarrow=True, arrowhead=1, ax=40, ay=-30, bgcolor="#00D4FF", font=dict(color="black"))
            st.plotly_chart(fig_dual, use_container_width=True)
            
            st.write("---")
            st.subheader("🤖 系统决策建议")
            if gsmi_total >= 70:
                if gap > 1.5 and curr_hkd < 7.81:
                    st.success(f"🌟 **强力进攻** | GSMI={gsmi_total}, 港股领涨 ({gap:+.2f}%), 汇率支持。建议重仓 [{target_name}]。")
                else: st.success(f"✅ **温和配置** | 宏观分高，适合分批买入。")
            elif gsmi_total < 45: st.error(f"❌ **全面防御** | 环境分低 ({gsmi_total})。警惕风险。")
            else: st.warning(f"👉 **观望** | 环境中性。动能差: {gap:+.2f}%。")

except Exception as e:
    st.error(f"发生错误: {e}")
