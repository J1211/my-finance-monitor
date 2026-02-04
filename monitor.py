import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timedelta
from fredapi import Fred
import cot_reports as cot  # 新增：无需 Key 抓取 COT 数据

# --- 1. 界面配置 ---
st.set_page_config(page_title="GSMI | 全球聪明钱监控面板", layout="wide")

# (此处保持你原来的 CSS 样式不变...)

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

# (侧边栏其他调查参数保持不变...)

# --- 3. 数据抓取函数 (改用 cot_reports) ---

@st.cache_data(ttl=86400) # COT每周更新一次，缓存24小时
def fetch_cot_data():
    """修正后的 COT 数据抓取函数"""
    try:
        current_year = datetime.now().year
        frames = []
        
        # 抓取近 3 年数据（减少下载量，提高加载速度）
        for year in range(current_year - 2, current_year + 1):
            # 修正函数名：从 get_cot_year 改为 cot_year
            df_year = cot.cot_year(year, cot_report_type='legacy_fut')
            if df_year is not None:
                frames.append(df_year)
        
        if not frames:
            return pd.Series(), pd.Series()

        all_cot = pd.concat(frames)
        
        # 转换日期格式
        all_cot['As_of_Date_In_Form_YYMMDD'] = pd.to_datetime(
            all_cot['As_of_Date_In_Form_YYMMDD'], format='%y%m%d', errors='coerce'
        )
        all_cot.set_index('As_of_Date_In_Form_YYMMDD', inplace=True)
        all_cot.sort_index(inplace=True)

        # 准确的资产名称（CFTC 标准格式）
        gold_name = "GOLD - COMMODITY EXCHANGE INC."
        silver_name = "SILVER - COMMODITY EXCHANGE INC."
        
        def extract_net(asset_name):
            # 筛选特定品种
            asset_df = all_cot[all_cot['Market_and_Exchange_Names'].str.contains(asset_name, na=False, case=False)]
            if asset_df.empty:
                return pd.Series()
            # 计算净头寸 = 非商业多头 - 非商业空头
            net = asset_df['Noncommercial_Positions_Long_All'] - asset_df['Noncommercial_Positions_Short_All']
            return net

        return extract_net("GOLD"), extract_net("SILVER")
    except Exception as e:
        st.error(f"COT 数据解析失败: {e}")
        return pd.Series(), pd.Series()

@st.cache_data(ttl=3600)
def fetch_macro_data():
    end = datetime.now()
    start = end - timedelta(days=450)
    
    def safe_get_yf(ticker):
        try:
            df = yf.download(ticker, start=start, end=end, progress=False)
            if df.empty: return pd.Series()
            data = df['Close'] if 'Close' in df.columns else df
            if isinstance(data, pd.DataFrame): return data.iloc[:, 0].ffill().dropna()
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
    
    # 获取 COT 数据
    gold_cot_ser, silver_cot_ser = fetch_cot_data()
    
    return tips, dxy, copper, gold, spread, hkd, hsi, as300, gold_cot_ser, silver_cot_ser

# --- 4. 辅助函数 ---
def get_val(ser, pos=-1, default=0.0):
    if ser is None or len(ser) == 0: return default
    try: return float(ser.iloc[pos])
    except: return default

# 黄金 20 年极值参考 (根据历史数据：高点约 350k，低点约 0)
# 白银 20 年极值参考 (高点约 100k，低点约 -20k)
def get_percentile_fixed(val, asset="gold"):
    if asset == "gold":
        low, high = 0, 350000
    else:
        low, high = -20000, 100000
    pct = (val - low) / (high - low) * 100
    return max(0, min(100, pct))

# --- 5. 逻辑执行与 UI (重点修改 tabs[2]) ---

try:
    tips_ser, dxy_ser, copper_ser, gold_ser, spread_ser, hkd_ser, hsi_ser, as300_ser, g_cot, s_cot = fetch_macro_data()

    # (此处 GSMI 评分引擎代码保持不变...)

    st.markdown("---")
    tabs = st.tabs(["💧 流动性", "🧠 情绪", "🏗️ 现实", "📉 执行确认"])

    with tabs[2]:
        col_r1, col_r2 = st.columns(2)
        with col_r1:
            st.metric("高收益债利差", f"{get_val(spread_ser):.0f} bps")
        with col_r2:
            cg_ratio = (copper_ser / gold_ser).dropna()
            curr_cg = get_val(cg_ratio)
            ma200_cg = get_val(cg_ratio.rolling(200).mean())
            st.metric("铜金比趋势", f"{curr_cg:.4f}", "高于200MA" if curr_cg > ma200_cg else "低于200MA")

        st.write("---")
        st.subheader("🥇 贵金属大资金追踪 (COT Non-Commercial Net)")
        
        if not g_cot.empty and not s_cot.empty:
            c1, c2 = st.columns(2)
            
            # 黄金展示
            with c1:
                curr_g_cot = get_val(g_cot)
                g_pct = get_percentile_fixed(curr_g_cot, "gold")
                st.metric("黄金净头寸", f"{curr_g_cot/1000:.1f}k 手", f"估算20Y百分位: {g_pct:.1f}%")
                
                fig_g = go.Figure(go.Scatter(x=g_cot.index, y=g_cot.values, name="Gold Net", line=dict(color='#ffd700')))
                fig_g.update_layout(height=250, template="plotly_dark", margin=dict(l=0, r=0, t=0, b=0))
                st.plotly_chart(fig_g, use_container_width=True)
                if g_pct > 85: st.error("🚨 黄金拥挤度极高，警惕回调")
                elif g_pct < 15: st.success("✅ 黄金情绪极冷，具备反转潜力")

            # 白银展示
            with c2:
                curr_s_cot = get_val(s_cot)
                s_pct = get_percentile_fixed(curr_s_cot, "silver")
                st.metric("白银净头寸", f"{curr_s_cot/1000:.1f}k 手", f"估算20Y百分位: {s_pct:.1f}%")
                
                fig_s = go.Figure(go.Scatter(x=s_cot.index, y=s_cot.values, name="Silver Net", line=dict(color='#c0c0c0')))
                fig_s.update_layout(height=250, template="plotly_dark", margin=dict(l=0, r=0, t=0, b=0))
                st.plotly_chart(fig_s, use_container_width=True)
                if s_pct > 85: st.error("🚨 白银拥挤度极高")
                elif s_pct < 15: st.success("✅ 白银情绪极冷")
        else:
            st.warning("COT 数据源链接中，请稍候或刷新...")

    # (其他 Tabs 保持不变...)

except Exception as e:
    st.error(f"全局错误: {e}")

