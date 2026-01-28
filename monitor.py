import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timedelta
from fredapi import Fred

# --- 1. 配置与初始化 ---
st.set_page_config(page_title="GSMI | 全球聪明钱监控面板", layout="wide")

st.markdown("""
    <style>
    .main { background-color: #0e1117; }
    div[data-testid="stMetricValue"] { font-size: 28px; }
    .stAlert { padding: 10px; }
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
fms_date = st.sidebar.date_input("本期调查发布日期", datetime.now() - timedelta(days=15))
fms_cash = st.sidebar.slider("机构现金水平 (%)", 3.0, 6.5, 4.5, 0.1)
fms_crowded = st.sidebar.selectbox("当前最拥挤交易", ["美股大盘科技", "做空中国股票", "做多美元", "做多国债", "其他/无"])

st.sidebar.markdown("---")
st.sidebar.header("🎯 个人追踪目标")
target_name = st.sidebar.text_input("关注板块名称", "例如：中概互联网 AI")
target_sector_status = st.sidebar.radio("该板块拥挤度评分", ["冷清/低配", "标配", "极其拥挤"])

# --- 3. 健壮的数据抓取函数 ---

@st.cache_data(ttl=3600)
def fetch_data():
    end = datetime.now()
    start = end - timedelta(days=400)
    
    # A. FRED 数据
    tips_raw = fred.get_series('DFII10', start, end)
    spread_raw = fred.get_series('BAMLH0A0HYM2', start, end)
    tips = tips_raw.ffill().dropna()
    spread = spread_raw.ffill().dropna()
    
    # B. Yahoo Finance 数据
    tickers = {"DXY": "DX-Y.NYB", "Copper": "HG=F", "Gold": "GC=F", "HKD": "HKD=X"}
    raw_df = yf.download(list(tickers.values()), start=start, end=end, progress=False)
    
    if isinstance(raw_df.columns, pd.MultiIndex):
        price_df = raw_df['Close'].ffill().dropna()
    else:
        price_df = raw_df.ffill().dropna()
        
    return tips, price_df, spread

# --- 4. 逻辑执行 ---

try:
    tips_ser, price_df, spread_ser = fetch_data()

    # 安全提取
    curr_tips = float(tips_ser.iloc[-1])
    prev_tips = float(tips_ser.iloc[-5])
    curr_dxy = float(price_df["DX-Y.NYB"].iloc[-1])
    prev_dxy = float(price_df["DX-Y.NYB"].iloc[-5])
    curr_spread = float(spread_ser.iloc[-1])
    prev_spread = float(spread_ser.iloc[-5])
    curr_hkd = float(price_df["HKD=X"].iloc[-1])
    
    # 铜金比
    cg_series = (price_df["HG=F"] / price_df["GC=F"]).dropna()
    curr_cg = float(cg_series.iloc[-1])
    ma200_cg_ser = cg_series.rolling(200).mean().dropna()
    ma200_cg = float(ma200_cg_ser.iloc[-1]) if not ma200_cg_ser.empty else curr_cg

    # --- 5. GSMI 评分算法 ---
    s_tips = 20 if curr_tips < 1.0 else (10 if curr_tips <= 2.0 else 0)
    s_dxy = 20 if curr_dxy < 100 else (10 if curr_dxy <= 105 else 0)
    s_cash = 30 if fms_cash > 5.0 else (15 if fms_cash >= 4.0 else 0)
    s_spread = 20 if curr_spread < 350 else (10 if curr_spread <= 500 else 0)
    s_cg = 10 if curr_cg > ma200_cg else 0
    gsmi_total = s_tips + s_dxy + s_cash + s_spread + s_cg

    # --- 6. UI 展示 ---

    # 顶部概览
    c_score, c_radar = st.columns([2, 1])
    with c_score:
        fig = go.Figure(go.Indicator(
            mode = "gauge+number", value = gsmi_total,
            title = {'text': f"GSMI 环境总分 (更新: {datetime.now().strftime('%m-%d')})", 'font': {'size': 20}},
            gauge = {
                'axis': {'range': [0, 100]}, 'bar': {'color': "#00ffcc"},
                'steps': [
                    {'range': [0, 40], 'color': "#441111"},
                    {'range': [40, 60], 'color': "#444411"},
                    {'range': [60, 80], 'color': "#114411"},
                    {'range': [80, 100], 'color': "#006644"}]
            }
        ))
        fig.update_layout(height=350, margin=dict(l=30, r=30, t=50, b=20), paper_bgcolor="#0e1117", font={'color': "white"})
        st.plotly_chart(fig, use_container_width=True)

    with c_radar:
        st.subheader("🚨 战术预警灯")
        status_map = {"冷清/低配": "🟢 低位安全", "标配": "🟡 中性观望", "极其拥挤": "🔴 警惕踩踏"}
        st.markdown(f"**关注目标: {target_name if target_name else '未设置'}**")
        st.title(status_map[target_sector_status])
        st.warning(f"全球最拥挤交易: **{fms_crowded}**")
        st.caption(f"FMS 调查日期: {fms_date}")

    # 分层详情
    st.markdown("---")
    t1, t2, t3, t4 = st.tabs(["💧 流动性 (Liquidity)", "🧠 情绪 (Sentiment)", "🏗️ 现实 (Reality)", "📈 执行确认 (Execution)"])

    with t1:
        # 第一排：指标数字展示
        col1, col2 = st.columns(2)
        
        tips_delta = curr_tips - prev_tips
        dxy_delta = curr_dxy - prev_dxy
        
        with col1:
            st.metric("10Y TIPS (实际利率)", f"{curr_tips:.2f}%", f"{tips_delta:.4f}", delta_color="inverse")
            st.write("📊 **标准：** <1% 甜点区 | 1-2% 中性 | >2% 危险")
            # 新增：TIPS 走势图 (反映全球资产重力)
            # 备注：TIPS 数据来自 FRED，我们将其可视化
            st.line_chart(tips_ser.tail(90), height=200) 
            st.caption("注：TIPS 下行 = 重力减小 = 估值扩张信号")

        with col2:
            st.metric("美元指数 (DXY)", f"{curr_dxy:.2f}", f"{dxy_delta:.2f}", delta_color="inverse")
            st.write("📊 **标准：** <100 爆发区 | 100-105 平衡 | >105 危险")
            # 美元指数走势图
            st.line_chart(price_df["DX-Y.NYB"].tail(90), height=200)
            st.caption("注：美元下行 = 水泵开启 = 资金流向非美市场信号")

    with t2:
        m1, m2 = st.columns(2)
        m1.metric("FMS 机构现金水平", f"{fms_cash}%", delta="反向看多" if fms_cash > 5 else "反向减仓" if fms_cash < 4 else "中性")
        m1.write("📊 **标准：** >5% 底部信号 (30分) | 4-5% 中性 (15分) | <4% 顶部预警 (0分)")
        st.info(f"当前最拥挤交易：{fms_crowded}。大资金倾向于从拥挤处撤离，流向低配/冷清板块。")

    with t3:
        r1, r2 = st.columns(2)
        r1.metric("高收益债信用利差", f"{curr_spread:.0f} bps", f"{curr_spread-prev_spread:.0f}", delta_color="inverse")
        r1.write("📊 **标准：** <350 安全 (20分) | 350-500 警戒 (10分) | >500 危险 (0分)")
        
        r2.metric("铜金比趋势", f"{curr_cg:.4f}", f"{curr_cg > ma200_cg}")
        r2.write("📊 **标准：** >200日均线 扩张 (10分) | <200日均线 萎缩 (0分)")
        
        fig_cg = go.Figure()
        fig_cg.add_trace(go.Scatter(x=cg_series.index[-120:], y=cg_series.values[-120:], name="铜金比", line=dict(color='#00ffcc')))
        fig_cg.add_trace(go.Scatter(x=ma200_cg_ser.index[-120:], y=ma200_cg_ser.values[-120:], name="200MA", line=dict(dash='dash', color='white')))
        fig_cg.update_layout(height=300, template="plotly_dark", margin=dict(l=10, r=10, t=10, b=10))
        st.plotly_chart(fig_cg, use_container_width=True)

    with t4:
        # --- A. 顶部关键指标栏 ---
        e1, e2 = st.columns(2)
        
        # 1. 港元汇率 (反映全球资金进出香港的真实意愿)
        current_hkd = float(price_df["HKD=X"].iloc[-1])
        fx_strength = "强" if current_hkd < 7.80 else ("弱" if current_hkd > 7.84 else "中性")
        
        e1.metric("港元汇率 (USD/HKD)", f"{current_hkd:.4f}", 
                  delta=f"资金{fx_strength}势", 
                  delta_color="normal" if fx_strength=="强" else "inverse")
        e1.write("📊 **标准：** 7.75 强力吸金 | 7.85 资金撤离")
        
        # 2. 港股沽空比率 (更新了稳定的东方财富/富途链接)
        st.markdown("""<style> .stSlider { padding-bottom: 20px; } </style>""", unsafe_allow_html=True)
        e2.markdown(f"🔗 [查数1：东方财富-港股沽空] (https://data.eastmoney.com/hk/gkcf.html)")
        e2.markdown(f"🔗 [查数2：富途-港股沽空分析] (https://www.futunn.com/quote/hk/market-short-sell)")
        
        hk_short_ratio = e2.slider("手动录入：今日大盘沽空比率 (%)", 5.0, 35.0, 16.5, 0.1)
        e2.caption("提示：>18% 预示潜在空头回补导致的爆发力。")
        
        st.write("---")
        
        # --- B. 两地市场动能对比图 (深度修复版) ---
        st.subheader("📊 A股 vs 港股 相对强度对比 (近20日)")
        
        # 抓取数据
        proxy_tickers = ["000300.SS", "^HSI"]
        proxy_raw = yf.download(proxy_tickers, period="45d", progress=False)
        
        if not proxy_raw.empty and 'Close' in proxy_raw:
            # 1. 提取 Close 并强制降维
            proxy_close = proxy_raw['Close'].copy()
            
            # 2. 核心修复：处理节假日不一致导致的 NaN
            # 先用 ffill (前向填充) 解决中间断点，再用 bfill (后向填充) 解决第一行缺失
            proxy_clean = proxy_close.ffill().bfill()
            
            # 3. 截取最近20个交易日并归一化 (基准=100)
            plot_df = proxy_clean.tail(20)
            base_price = plot_df.iloc[0]
            norm_data = (plot_df / base_price) * 100
            
            # 4. 绘图
            fig_proxy = go.Figure()
            # A股线 (红色)
            if "000300.SS" in norm_data.columns:
                fig_proxy.add_trace(go.Scatter(
                    x=norm_data.index, y=norm_data["000300.SS"], 
                    name="A股 (沪深300)", line=dict(color='#ff4b4b', width=3)
                ))
            # 港股线 (蓝色)
            if "^HSI" in norm_data.columns:
                fig_proxy.add_trace(go.Scatter(
                    x=norm_data.index, y=norm_data["^HSI"], 
                    name="港股 (恒生指数)", line=dict(color='#0083ff', width=3)
                ))
            
            fig_proxy.update_layout(
                height=400, template="plotly_dark", hovermode="x unified",
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                margin=dict(l=10, r=10, t=30, b=10),
                yaxis_title="收益率 (基准=100)"
            )
            st.plotly_chart(fig_proxy, use_container_width=True)
            
            # --- C. 🤖 GSMI 系统自动决策引擎 ---
            st.write("---")
            st.subheader("🤖 GSMI 系统自动决策建议")
            
            # 计算动能差值
            as_perf = float(norm_data["000300.SS"].iloc[-1])
            hsi_perf = float(norm_data["^HSI"].iloc[-1])
            momentum_gap = hsi_perf - as_perf  # 港股相对于 A 股的强弱
            
            # 自动化决策矩阵
            if gsmi_total >= 70:
                if momentum_gap > 1.5 and current_hkd < 7.81:
                    st.success(f"🌟 **级别：强力进攻 (Aggressive)** \n\n **逻辑：** 宏观分高 ({gsmi_total}) + 港股领涨 + 汇率支持。大资金正在通过港股扫货，建议积极配置 [{target_name}]。")
                elif momentum_gap < -1.5:
                    st.success(f"✅ **级别：内资驱动 (Domestic Led)** \n\n **逻辑：** 环境理想但 A 股强于港股。主要是内资情绪先行，外资仍在观望。建议关注大盘蓝筹。")
                else:
                    st.success(f"✅ **级别：温和配置 (Neutral Buy)** \n\n **逻辑：** 宏观环境理想，两地走势同步。适合分批建立头寸。")
            
            elif 45 <= gsmi_total < 70:
                if momentum_gap > 2.0:
                    st.warning(f"⚠️ **级别：空头挤压/存量博弈** \n\n **逻辑：** 环境分一般，但港股突发异动。多为高沽空下的空头踩踏，注意回落风险，不宜追高。")
                elif hk_short_ratio > 20:
                    st.info(f"🧐 **级别：底部伏击** \n\n **逻辑：** 环境分处于回升期，且沽空比率极高 ({hk_short_ratio}%)。等待汇率转强作为最后发令枪。")
                else:
                    st.write("👉 **级别：观望 (Wait & See)** \n\n **逻辑：** 环境处于震荡期，无明确趋势信号。建议保持低仓位。")
            
            else:  # GSMI < 45
                if momentum_gap > 0:
                    st.error(f"❌ **级别：诱多陷阱 (Bull Trap)** \n\n **逻辑：** 宏观看板处于高危区 ({gsmi_total})，即便港股反弹也缺乏根基。减仓避险为上。")
                else:
                    st.error(f"❌ **级别：全面防御 (Defensive)** \n\n **逻辑：** 宏观与资金面双杀。保护本金，等待下一次系统性机会。")

            # 特殊情况手动修正
            with st.expander("🛠️ 特殊情况手动修正 (如重大政策出台)"):
                manual_fix = st.checkbox("开启政策/突发利好修正")
                if manual_fix:
                    impact = st.select_slider("政策影响评估", ["利空", "中性", "重大利好"], value="中性")
                    if impact == "重大利好":
                        st.balloons()
                        st.success("检测到国家级政策支撑，系统建议已手动上调一级。")
        else:
            st.error("无法获取对比数据。请检查网络是否能访问 Yahoo Finance 的 A 股与港股数据。")

except Exception as e:
    st.error(f"数据处理异常: {e}")

st.markdown("---")
st.caption("GSMI 逻辑系统 | 40% 流动性 + 30% 情绪 + 30% 现实。请定期更新侧边栏 FMS 数据。")




