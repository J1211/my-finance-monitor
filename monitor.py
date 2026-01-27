import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timedelta
from fredapi import Fred

# --- 1. 配置与初始化 ---
st.set_page_config(page_title="全球大资金流向监控表", layout="wide")
st.title("🏹 全球大资金偏好逻辑链监控面板")

# 侧边栏配置
st.sidebar.header("⚙️ 配置中心")
if "fred_api_key" in st.secrets:
    fred_key = st.secrets["fred_api_key"]
else:
    fred_key = st.sidebar.text_input("输入你的 FRED API Key", type="password")
st.sidebar.caption("没有Key? 请去 fred.stlouisfed.org 免费申请")

if not fred_key:
    st.warning("👈 请在侧边栏输入 FRED API Key 以激活宏观看板。")
    st.stop()

fred = Fred(api_key=fred_key)

# --- 2. 数据获取函数 ---

@st.cache_data(ttl=3600) # 缓存一小时，避免重复请求
def get_macro_data():
    end = datetime.now()
    start = end - timedelta(days=120)
    
    # A. 实际利率 (10-Year TIPS)
    tips = fred.get_series('DFII10', start, end)
    
    # B. 美元指数 (DXY)
    # yfinance 有时会返回 MultiIndex, 使用 auto_adjust 确保列名简单
    dxy_df = yf.download("DX-Y.NYB", start=start, end=end, progress=False)
    dxy = dxy_df['Close'].iloc[:, 0] if isinstance(dxy_df['Close'], pd.DataFrame) else dxy_df['Close']
    
    # C. 行业强度指标
    copper_df = yf.download("HG=F", start=start, end=end, progress=False)
    copper = copper_df['Close'].iloc[:, 0] if isinstance(copper_df['Close'], pd.DataFrame) else copper_df['Close']
    
    gold_df = yf.download("GC=F", start=start, end=end, progress=False)
    gold = gold_df['Close'].iloc[:, 0] if isinstance(gold_df['Close'], pd.DataFrame) else gold_df['Close']
    
    # D. 信用利差
    hy_spread = fred.get_series('BAMLH0A0HYM2', start, end)
    
    return tips, dxy, copper, gold, hy_spread

# --- 3. 侧边栏：美银 FMS 调查手动更新 ---
st.sidebar.markdown("---")
st.sidebar.header("📊 美银基金经理调查 (FMS)")
fms_overweight = st.sidebar.text_input("FMS 看好板块", "新兴市场, 医疗")
fms_crowded = st.sidebar.text_input("FMS 最拥挤交易", "做多美股科技巨头")
fms_sentiment = st.sidebar.slider("机构整体情绪 (0-悲观, 10-乐观)", 0, 10, 5)

# --- 4. 执行数据获取与清洗 ---
try:
    tips, dxy, copper, gold, hy_spread = get_macro_data()

    # --- 5. 主面板展示 ---

    # 第一层：风险偏好改变
    st.header("第一层：风险偏好 (Global Liquidity)")
    col1, col2, col3 = st.columns(3)

    # 提取数值并强制转换，防止 TypeError
    current_tips = float(tips.iloc[-1])
    prev_tips = float(tips.iloc[-5]) # 一周前
    tips_delta = current_tips - prev_tips

    current_dxy = float(dxy.iloc[-1])
    prev_dxy = float(dxy.iloc[-5])
    dxy_delta = current_dxy - prev_dxy

    with col1:
        st.metric("10年期美债实际利率", f"{current_tips:.2f}%", f"{tips_delta:.4f}")
    with col2:
        st.metric("美元指数 (DXY)", f"{current_dxy:.2f}", f"{dxy_delta:.2f}")

    # 判断 Risk-On 逻辑
    risk_on = tips_delta < 0 and dxy_delta < 0
    with col3:
        if risk_on:
            st.success("核心信号：风险开启 (Risk-On) ✅")
        else:
            st.error("核心信号：风险规避 (Risk-Off) ❌")

    st.markdown("---")

    # 第二层：板块共识
    st.header("第二层：板块共识 (BofA Survey)")
    c1, c2, c3 = st.columns(3)
    c1.info(f"**大资金增持板块:** \n\n {fms_overweight}")
    c2.warning(f"**警惕拥挤交易:** \n\n {fms_crowded}")
    c3.metric("机构情绪得分", f"{fms_sentiment}/10", delta="中性" if 4<=fms_sentiment<=6 else "极端")

    st.markdown("---")

    # 第三层：行业强度验证
    st.header("第三层：宏观周期验证 (Industrial Strength)")
    col_a, col_b = st.columns(2)

    with col_a:
        # 铜金比计算
        cg_ratio = copper / gold
        st.subheader("铜金比 (经济增长预期)")
        fig_cg = go.Figure()
        fig_cg.add_trace(go.Scatter(x=cg_ratio.index, y=cg_ratio.values, name="Copper/Gold Ratio", line=dict(color='#00FFCC')))
        fig_cg.update_layout(height=400, template="plotly_dark")
        st.plotly_chart(fig_cg, use_container_width=True)

    with col_b:
        st.subheader("高收益债信用利差 (风险溢价)")
        fig_hy = go.Figure()
        fig_hy.add_trace(go.Scatter(x=hy_spread.index, y=hy_spread.values, name="HY Spread", line=dict(color='#FFCC00')))
        fig_hy.update_layout(height=400, template="plotly_dark")
        st.plotly_chart(fig_hy, use_container_width=True)

    st.markdown("---")

    # 第四层：入场参考
    st.header("第四层：中国市场资金流向 (Entry Reference)")
    col_x, col_y = st.columns(2)

    with col_x:
        st.subheader("MSCI中国主要指数 (MCHI)")
        mchi = yf.download("MCHI", period="60d", progress=False)['Close']
        st.line_chart(mchi)

    with col_y:
        st.subheader("中国互联网龙头 (KWEB)")
        kweb = yf.download("KWEB", period="60d", progress=False)['Close']
        st.line_chart(kweb)

    st.caption(f"最后更新时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | 数据源: FRED, Yahoo Finance")

except Exception as e:
    st.error(f"数据处理出错: {e}")

    st.info("提示：如果是KeyError 'Close'，通常是网络连接Yahoo Finance失败，请检查网络或代理设置。")
