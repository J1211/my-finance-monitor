import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timedelta
from fredapi import Fred

# --- 1. 配置与初始化 ---
st.set_page_config(page_title="GSMI | 全球聪明钱监控面板", layout="wide")

# 自定义 CSS：加粗数字，调整布局
st.markdown("""
    <style>
    .main { background-color: #0e1117; }
    div[data-testid="stMetricValue"] { font-size: 32px; font-weight: bold; color: #00ffcc; }
    .stTabs [data-baseweb="tab-list"] { gap: 20px; }
    .stTabs [data-baseweb="tab"] { height: 50px; white-space: pre-wrap; font-size: 16px; }
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
target_status = st.sidebar.radio("板块拥挤度", ["冷清/低配", "标配", "极其拥挤"])

# --- 3. 稳健的数据抓取函数 ---

@st.cache_data(ttl=3600)
def fetch_data():
    end = datetime.now()
    start = end - timedelta(days=400)
    
    # A. FRED 数据 (分步抓取，强制填充)
    tips = fred.get_series('DFII10', start, end).ffill().dropna()
    spread = fred.get_series('BAMLH0A0HYM2', start, end).ffill().dropna()
    
    # B. Yahoo Finance 数据 (单列抓取，防止互相干扰)
    def get_yf_data(ticker):
        try:
            data = yf.download(ticker, start=start, end=end, progress=False)
            if isinstance(data.columns, pd.MultiIndex):
                return data['Close'].iloc[:, 0].ffill()
            return data['Close'].ffill()
        except:
            return pd.Series()

    dxy = get_yf_data("DX-Y.NYB")
    copper = get_yf_data("HG=F")
    gold = get_yf_data("GC=F")
    hkd = get_yf_data("HKD=X")
    hsi = get_yf_data("^HSI")
    as300 = get_yf_data("000300.SS")
    
    return tips, dxy, copper, gold, spread, hkd, hsi, as300

# --- 4. 逻辑执行 ---

try:
    tips_ser, dxy_ser, copper_ser, gold_ser, spread_ser, hkd_ser, hsi_ser, as300_ser = fetch_data()

    # 提取最新值 (确保是数字)
    curr_tips = float(tips_ser.iloc[-1])
    prev_tips = float(tips_ser.iloc[-5])
    curr_dxy = float(dxy_ser.iloc[-1])
    prev_dxy = float(dxy_ser.iloc[-5])
    curr_spread = float(spread_ser.iloc[-1])
    prev_spread = float(spread_ser.iloc[-5])
    curr_hkd = float(hkd_ser.iloc[-1])
    
    # 铜金比 200MA 逻辑
    cg_ratio = (copper_ser / gold_ser).dropna()
    curr_cg = float(cg_ratio.iloc[-1])
    ma200_cg = float(cg_ratio.rolling(200).mean().dropna().iloc[-1])

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
            mode = "gauge+number", value = gsmi_total,
            title = {'text': f"GSMI 总分: {datetime.now().strftime('%m-%d')}", 'font': {'size': 20}},
            gauge = {'axis': {'range': [0, 100]}, 'bar': {'color': "#00ffcc"},
                     'steps': [{'range': [0, 40], 'color': "#441111"}, {'range': [40, 60], 'color': "#444411"},
                               {'range': [60, 80], 'color': "#114411"}, {'range': [80, 100], 'color': "#006644"}]}
        ))
        fig.update_layout(height=350, margin=dict(l=30, r=30, t=50, b=20), paper_bgcolor="#0e1117", font={'color': "white"})
        st.plotly_chart(fig, use_container_width=True)

    with c_radar:
        st.subheader("🚨 战术预警灯")
        status_map = {"冷清/低配": "🟢 低位安全", "标配": "🟡 中性观望", "极其拥挤": "🔴 警惕踩踏"}
        st.markdown(f"**目标: {target_name}**")
        st.title(status_map[target_status])
        st.warning(f"最拥挤交易: {fms_crowded}")

    st.markdown("---")
    t1, t2, t3, t4 = st.tabs(["💧 流动性", "🧠 情绪", "🏗️ 现实", "📈 执行确认"])

    with t1:
        col1, col2 = st.columns(2)
        col1.metric("10Y TIPS (实际利率)", f"{curr_tips:.2f}%", f"{curr_tips-prev_tips:.4f}", delta_color="inverse")
        col1.area_chart(tips_ser.tail(60), height=200)
        
        col2.metric("美元指数 (DXY)", f"{curr_dxy:.2f}", f"{curr_dxy-prev_dxy:.2f}", delta_color="inverse")
        col2.area_chart(dxy_ser.tail(60), height=200)
        st.write("📊 **标准：** TIPS <1% 且 DXY <100 为双绿 Risk-On 模式。")

    with t2:
        st.metric("FMS 机构现金水平", f"{fms_cash}%", delta="看多信号" if fms_cash > 5 else "风险信号" if fms_cash < 4 else "中性")
        st.info(f"发布日期: {fms_date}。当前最拥挤: {fms_crowded}。建议避开拥挤区，寻找低配区的补涨机会。")

    with t3:
        r1, r2 = st.columns(2)
        r1.metric("高收益债利差", f"{curr_spread:.0f} bps", f"{curr_spread-prev_spread:.0f}", delta_color="inverse")
        r2.metric("铜金比趋势", f"{curr_cg:.4f}", "高于200MA" if curr_cg > ma200_cg else "低于200MA")
        
        fig_cg = go.Figure()
        fig_cg.add_trace(go.Scatter(x=cg_ratio.index[-120:], y=cg_ratio.values[-120:], name="铜金比", line=dict(color='#00ffcc')))
        fig_cg.add_trace(go.Scatter(x=cg_ratio.index[-120:], y=cg_ratio.rolling(200).mean().values[-120:], name="200MA", line=dict(dash='dash', color='white')))
        fig_cg.update_layout(height=300, template="plotly_dark")
        st.plotly_chart(fig_cg, use_container_width=True)

    with t4:
        e1, e2 = st.columns(2)
        e1.metric("港元汇率", f"{curr_hkd:.4f}", delta="资金流向中性" if 7.78 < curr_hkd < 7.82 else "异动")
        
        # 沽空比率链接修复
        e2.markdown("**🔍 查数通道 (看“全市场沽空占比”)：**")
        e2.markdown("[1. 新浪财经 (最直接)](https://stock.finance.sina.com.cn/hkstock/quotes/shm.php)")
        e2.markdown("[2. 东方财富 (更详细)](https://data.eastmoney.com/hk/gkcf.html)")
        hk_short_ratio = e2.slider("手动录入：当日全市场沽空比 (%)", 5.0, 30.0, 16.5, 0.1)
        
        st.write("---")
        st.subheader("📊 A股 vs 港股 相对强度 (近20日)")
        # 动能图表修复
        combined = pd.concat([hsi_ser, as300_ser], axis=1).ffill().bfill().tail(20)
        combined.columns = ["HSI", "AS300"]
        norm_combined = (combined / combined.iloc[0]) * 100
        st.line_chart(norm_combined)
        
        # 🤖 自动决策建议
        hsi_p = norm_combined["HSI"].iloc[-1]
        as_p = norm_combined["AS300"].iloc[-1]
        gap = hsi_p - as_p
        
        if gsmi_total >= 70:
            if gap > 1.5 and curr_hkd < 7.81:
                st.success(f"🌟 **级别：强力进攻** | 宏观分高 ({gsmi_total}) + 港股领涨 + 汇率转强。外资正在暴力扫货。")
            else:
                st.success(f"✅ **级别：温和配置** | 宏观分支持，建议分批布局 [{target_name}]。")
        elif gsmi_total < 40:
            st.error(f"❌ **级别：全面防御** | 环境恶劣，警惕任何反弹陷阱。")
        else:
            st.warning("👉 **级别：观望** | 环境分中性，等待趋势明朗。")

except Exception as e:
    st.error(f"数据加载失败: {e}")
