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

# --- 2. 侧边栏配置 ---
st.sidebar.header("🛠️ 核心参数配置")
target_name = st.sidebar.text_input("关注板块名称", "中概科技龙头")
target_status = st.sidebar.radio("该板块目前拥挤度", ["冷清/低配", "标配", "极其拥挤"])

# --- 月度手动更新区 ---
DEFAULT_FMS_CASH = 3.6  
DEFAULT_FMS_DATE = datetime(2026, 7, 15) 
crowded_options = ["美股大盘科技", "做多美元", "做空中国股票", "做多国债", "做多黄金", "做多半导体"]
current_most_crowded = "做多半导体" 

st.sidebar.markdown("---")
st.sidebar.header("🗳️ BofA FMS 机构调查")
fms_cash = st.sidebar.slider("机构现金水平 (%)", 3.0, 6.5, DEFAULT_FMS_CASH, 0.1)
fms_date = st.sidebar.date_input("调查发布日期", DEFAULT_FMS_DATE)
fms_crowded = st.sidebar.selectbox("当前最拥挤交易", options=crowded_options, index=crowded_options.index(current_most_crowded))

st.sidebar.markdown("---")
st.sidebar.header("🏦 财政部 TGA 预测配置")
tga_target = st.sidebar.number_input("本季末 TGA 余额目标 (十亿$)", value=950, step=50)

st.sidebar.markdown("---")
with st.sidebar.expander("📖 GSMI 评分规则细则"):
    st.markdown("""
    **1. 核心货币 (45分):**  
    - NL > 4周均线 (+15)  
    - NL 本周环比增加 (+10)  
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

if "fred_api_key" in st.secrets:
    fred_key = st.secrets["fred_api_key"]
else:
    fred_key = st.sidebar.text_input("FRED API Key", type="password")

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

def get_tga_forecast(curr_tga_billion, target_val):
    today = datetime.now()
    m, d = today.month, today.day
    msg, risk = "⚪ 【平稳周期】目前无重大税收节点，重点关注目标回归。", "Normal"
    if m == 4 and 10 <= d <= 22: msg, risk = "🚨 【年度吸水期】个人税高峰，NL面临强压。", "High"
    elif m in [6, 9, 12] and 12 <= d <= 20: msg, risk = "🟠 【季中吸水期】企业预缴税，NL承压。", "High"
    elif 13 <= d <= 18: msg, risk = "🟢 【利息释放期】国债付息，利好流动性修复。", "Low"
    elif 1 <= d <= 5: msg, risk = "🔵 【财政支出期】月初支出高峰，水源背景偏暖。", "Low"
    gap = target_val - curr_tga_billion
    return msg, gap, risk

@st.cache_data(ttl=3600)
def fetch_and_sync_data():
    end = datetime.now()
    start = end - timedelta(days=500)
    
    def safe_get_yf(ticker):
        try:
            df = yf.download(ticker, start=start, end=end, progress=False)
            if df is None or df.empty: return pd.Series(dtype='float64')
            data = df['Close'].iloc[:, 0] if isinstance(df.columns, pd.MultiIndex) else df['Close']
            return data.ffill()
        except: return pd.Series(dtype='float64')

    data_dict = {}
    try:
        data_dict['tips'] = fred.get_series('DFII10', start, end)
        data_dict['spread'] = fred.get_series('BAMLH0A0HYM2', start, end)
        data_dict['assets'] = fred.get_series('WALCL', start, end)
        data_dict['tga'] = fred.get_series('WTREGEN', start, end)
        data_dict['rrp'] = fred.get_series('RRPONTSYD', start, end)
    except: pass

    dxy_raw = safe_get_yf("DX-Y.NYB")
    if dxy_raw.empty or dxy_raw.iloc[-1] < 50:
        uup = safe_get_yf("UUP")
        data_dict['dxy'] = uup * 3.68 if not uup.empty else pd.Series(dtype='float64')
    else: data_dict['dxy'] = dxy_raw

    data_dict['copper'] = safe_get_yf("HG=F")
    data_dict['gold'] = safe_get_yf("GC=F")
    data_dict['hkd'] = safe_get_yf("HKD=X")
    data_dict['hsi'] = safe_get_yf("^HSI")
    data_dict['as300'] = safe_get_yf("000300.SS")
    data_dict['btc'] = safe_get_yf("BTC-USD")
    data_dict['qqq'] = safe_get_yf("QQQ")
    data_dict['chinext'] = safe_get_yf("399006.SZ") # 创业板指作为 RS 基准

    df = pd.DataFrame(data_dict).ffill().dropna()
    if not df.empty:
        df['nl'] = (df['assets'] - df['tga'] - df['rrp']) / 1000000
        df['cg_ratio'] = df['copper'] / df['gold']
    return df

def calculate_history(df, fms_val):
    if df.empty: return df
    if 'spread' in df.columns and df['spread'].max() < 50:
        df['spread'] = df['spread'] * 100

    gsmi_history = []
    nl_ma4 = df['nl'].rolling(20).mean()
    cg_ma200 = df['cg_ratio'].rolling(200).mean()
    
    for i in range(len(df)):
        if i < 20:
            gsmi_history.append(np.nan)
            continue
        s_nl = (15 if df['nl'].iloc[i] > nl_ma4.iloc[i] else 0) + (10 if df['nl'].iloc[i] > df['nl'].iloc[i-5] else 0)
        s_tips = score_linear(df['tips'].iloc[i], 0.5, 2.5, 20, reverse=True)
        s_dxy = score_linear(df['dxy'].iloc[i], 98, 108, 15, reverse=True)
        s_fms = score_linear(fms_val, 3.5, 6.0, 15, reverse=False)
        s_cg = ((10 if df['cg_ratio'].iloc[i] > cg_ma200.iloc[i] else 0) if i > 200 else 0) + (5 if df['cg_ratio'].iloc[i] > df['cg_ratio'].iloc[i-10:i-5].mean() else 0)
        s_spread = score_linear(df['spread'].iloc[i], 300, 600, 10, reverse=True)
        gsmi_history.append(s_nl + s_tips + s_dxy + s_fms + s_cg + s_spread)
    
    df['gsmi_score'] = gsmi_history
    return df

# --- 4. 执行逻辑 ---

try:
    df_raw = fetch_and_sync_data()
    if df_raw.empty:
        st.error("❌ 无法获取完整宏观数据，请检查 API Key 或网络。")
        st.stop()
        
    df = calculate_history(df_raw, fms_cash)
    latest = df.iloc[-1]
    gsmi_total = latest['gsmi_score']

    # 计算最新单项分
    nl_ma_last = df['nl'].rolling(20).mean().iloc[-1]
    s_nl_latest = (15 if latest['nl'] > nl_ma_last else 0) + (10 if latest['nl'] > df['nl'].iloc[-6] else 0)
    cg_ma_last = df['cg_ratio'].rolling(200).mean().iloc[-1]
    s_cg_latest = (10 if latest['cg_ratio'] > cg_ma_last else 0) + (5 if latest['cg_ratio'] > df['cg_ratio'].iloc[-10:-5].mean() else 0)

    # --- 5. UI 展示 ---
    c1, c2 = st.columns([2, 1])
    with c1:
        st.plotly_chart(go.Figure(go.Indicator(
            mode = "gauge+number", value = gsmi_total,
            title = {'text': f"GSMI 战术总分 ({df.index[-1].strftime('%m-%d')})", 'font': {'size': 20}},
            gauge = {'axis': {'range': [0, 100]}, 'bar': {'color': "#00ffcc"},
                     'steps': [{'range': [0, 40], 'color': "#441111"}, {'range': [40, 60], 'color': "#444411"},
                               {'range': [60, 80], 'color': "#114411"}, {'range': [80, 100], 'color': "#006644"}]}
        )).update_layout(height=350, margin=dict(l=30, r=30, t=50, b=20), paper_bgcolor="#0e1117", font={'color': "white"}), use_container_width=True)

    with c2:
        st.subheader("🚨 实时战术预警")
        t_map = {"冷清/低配": "🟢 低位安全", "标配": "🟡 中性观望", "极其拥挤": "🔴 警惕踩踏"}
        st.markdown(f"**关注目标: {target_name}**")
        st.title(t_map.get(target_status, "🟡 中性观望"))
        st.warning(f"FMS 最拥挤交易: {fms_crowded}")

    st.markdown("---")
    tabs = st.tabs(["💧 流动性水源", "🧠 情绪与购买力", "🏗️ 现实与防线", "🎯 Alpha 审计 (RS)", "📊 系统验证"])

    with tabs[0]:
        st.subheader("🏦 核心流动性水源 (NL + TIPS + DXY)")
        t_msg, t_gap, t_risk = get_tga_forecast(latest['tga']/1000, tga_target)
        if t_risk == "High": st.error(t_msg)
        elif t_risk == "Low": st.success(t_msg)
        else: st.info(t_msg)
        
        col_t1, col_t2, col_t3 = st.columns(3)
        col_t1.metric("当前 TGA 余额", f"${latest['tga']/1000:.1f}B")
        col_t2.metric("季末目标位", f"${tga_target}B")
        col_t3.metric("目标回归缺口", f"{t_gap:+.1f}B", delta_color="normal" if t_gap < 0 else "inverse")

        st.write("---")
        q1, q2, q3, q4 = st.columns(4)
        q1.markdown('<div class="quadrant-box">🔵 <b>25分: NL扩张期</b><br>🚀 进攻</div>', unsafe_allow_html=True)
        q2.markdown('<div class="quadrant-box">🟡 <b>15分: NL滞涨期</b><br>⚠️ 警惕</div>', unsafe_allow_html=True)
        q3.markdown('<div class="quadrant-box">🟠 <b>10分: NL修复期</b><br>🔍 观察</div>', unsafe_allow_html=True)
        q4.markdown('<div class="quadrant-box">🔴 <b>0分: NL衰退期</b><br>🛑 空仓</div>', unsafe_allow_html=True)

        m1, m2, m3 = st.columns(3)
        m1.metric("净流动性 (NL)", f"${latest['nl']:.2f}T", f"评分: {s_nl_latest}/25 | 周变: {latest['nl'] - df['nl'].iloc[-6]:+.3f}T")
        m2.metric("10Y TIPS", f"{latest['tips']:.2f}%", f"评分: {score_linear(latest['tips'],0.5,2.5,20,True):.1f}/20")
        m3.metric("美元指数 (DXY)", f"{latest['dxy']:.2f}", f"评分: {score_linear(latest['dxy'],98,108,15,True):.1f}/15")
        
        fig_nl = go.Figure()
        fig_nl.add_trace(go.Scatter(x=df.index, y=df['nl'], name="净流动性(T)", line=dict(color='#00ffcc', width=3)))
        fig_nl.add_trace(go.Scatter(x=df.index, y=df['tips'], name="TIPS (%)", line=dict(color='#FF3131', dash='dot'), yaxis="y2"))
        fig_nl.update_layout(height=350, template="plotly_dark", yaxis=dict(title="NL (T)"), yaxis2=dict(overlaying="y", side="right", showgrid=False))
        st.plotly_chart(fig_nl, use_container_width=True)

    with tabs[1]:
        st.subheader("🧠 情绪与购买力监控")
        e1, e2 = st.columns([1, 2])
        with e1:
            st.metric("FMS 机构现金", f"{fms_cash}%", f"得分: {score_linear(fms_cash,3.5,6.0,15):.1f}/15")
            st.write("---")
            btc_ret = df['btc'].pct_change() * 100
            last_28d = btc_ret.tail(28)
            pos_days = len(last_28d[last_28d > 0])
            st.write("**BTC 28日情绪扫描**")
            st.caption(f"📈 上涨天数: {pos_days} | 📉 下跌天数: {28-pos_days}")
            if pos_days >= 18: st.success("🔥 投机情绪极度活跃")
            elif pos_days <= 10: st.error("❄️ 流动性极度低迷")
            else: st.info("⚖️ 风险偏好震荡中")
        with e2:
            st.plotly_chart(go.Figure(go.Bar(x=last_28d.index, y=last_28d.values, marker_color=['#00ffcc' if x>0 else '#FF3131' for x in last_28d])).update_layout(height=250, template="plotly_dark", title="BTC 28日逐日波动脉搏 (%)", margin=dict(l=10, r=10, t=40, b=10)), use_container_width=True)
        st.write("**BTC 120日宏观趋势 (金丝雀价格线)**")
        st.line_chart(df['btc'].tail(120), height=200)

    with tabs[2]:
        st.subheader("🏗️ 现实增长与信用防线")
        r1, r2 = st.columns(2)
        with r1:
            cg_val = latest['cg_ratio']
            ma_val = df['cg_ratio'].rolling(200).mean().iloc[-1]
            cg_status = "🟠 低于均线 (重力压制)" if cg_val < ma_val else "🟢 高于均线 (动能扩张)"
            st.metric("铜金比趋势", f"{cg_val:.4f}", f"评分: {s_cg_latest}/15 | {cg_status}")
            fig_cg = go.Figure()
            fig_cg.add_trace(go.Scatter(x=df.index[-180:], y=df['cg_ratio'].tail(180), name="铜金比现状", line=dict(color='#00ffcc', width=3)))
            fig_cg.add_trace(go.Scatter(x=df.index[-180:], y=df['cg_ratio'].rolling(200).mean().tail(180), name="200MA (重力平衡线)", line=dict(color='orange', width=2, dash='dash')))
            fig_cg.update_layout(height=300, template="plotly_dark", margin=dict(l=10, r=10, t=10, b=10), legend=dict(orientation="h", y=1.02), yaxis=dict(tickformat=".4f"))
            st.plotly_chart(fig_cg, use_container_width=True)
        with r2:
            sp_val = latest['spread']
            sp_status = "🟢 地基稳固 (低于500)" if sp_val < 500 else "🚨 信用危机 (突破500)"
            st.metric("高收益债利差", f"{sp_val:.0f} bps", f"评分: {score_linear(sp_val,300,600,10,True):.1f}/10 | {sp_status}")
            fig_spread = go.Figure()
            fig_spread.add_trace(go.Scatter(x=df.index[-180:], y=df['spread'].tail(180), name="利差现状", line=dict(color='#00ffcc', width=3)))
            fig_spread.add_trace(go.Scatter(x=df.index[-180:], y=[500]*180, name="500bps (生存警戒线)", line=dict(color='orange', width=2, dash='dash')))
            fig_spread.update_layout(height=300, template="plotly_dark", margin=dict(l=10, r=10, t=10, b=10), legend=dict(orientation="h", y=1.02))
            st.plotly_chart(fig_spread, use_container_width=True)

    with tabs[3]:
        st.subheader("🎯 Alpha 审计 (Relative Strength)")
        st.caption("逻辑：剥离大盘 Beta，寻找真正的领头羊。基准：创业板指 (159915.SZ)")
        
        # 允许用户输入想要审计的标的
        audit_ticker = st.text_input("输入要审计的 ETF 代码 (如 561980.SS 或 159848.SZ)", "561980.SS")
        
        if audit_ticker:
            try:
                # 抓取审计标的数据
                audit_data = yf.download(audit_ticker, start=df.index[0], end=df.index[-1], progress=False)
                if not audit_data.empty:
                    audit_close = audit_data['Close'].iloc[:, 0] if isinstance(audit_data.columns, pd.MultiIndex) else audit_data['Close']
                    # 对齐基准数据 (创业板指)
                    rs_df = pd.DataFrame({'target': audit_close, 'base': df['chinext']}).ffill().dropna()
                    rs_ratio = rs_df['target'] / rs_df['base']
                    
                    # 计算 RS 均线
                    rs_20ma = rs_ratio.rolling(20).mean()
                    rs_250ma = rs_ratio.rolling(250).mean()
                    
                    # 计算斜率
                    curr_rs = rs_ratio.iloc[-1]
                    prev_rs = rs_ratio.iloc[-6] # 5天前
                    rs_slope = (curr_rs / prev_rs - 1) * 100
                    
                    # UI 展示
                    col_rs1, col_rs2 = st.columns(2)
                    with col_rs1:
                        rs_status = "🔥 强 Alpha (加速中)" if curr_rs > rs_20ma.iloc[-1] else "❄️ 弱 Beta (掉队中)"
                        st.metric(f"{audit_ticker} 相对强度", f"{curr_rs:.6f}", f"5日斜率: {rs_slope:+.2f}%")
                        st.write(f"**当前状态：{rs_status}**")
                    
                    fig_rs = go.Figure()
                    fig_rs.add_trace(go.Scatter(x=rs_ratio.index[-250:], y=rs_ratio.values[-250:], name="RS 曲线", line=dict(color='#00ffcc', width=3)))
                    fig_rs.add_trace(go.Scatter(x=rs_20ma.index[-250:], y=rs_20ma.values[-250:], name="RS 20MA (战术线)", line=dict(color='white', width=1, dash='dot')))
                    fig_rs.add_trace(go.Scatter(x=rs_250ma.index[-250:], y=rs_250ma.values[-250:], name="RS 250MA (战略线)", line=dict(color='orange', width=2, dash='dash')))
                    fig_rs.update_layout(height=400, template="plotly_dark", title=f"{audit_ticker} vs 创业板指 RS 审计", legend=dict(orientation="h", y=1.1))
                    st.plotly_chart(fig_rs, use_container_width=True)
                    st.info("💡 判据：RS 曲线在 250MA (橙色线) 之上代表长周期反转；在 20MA (白色点线) 之上代表短周期爆发。")
            except Exception as e:
                st.warning(f"无法审计该标的: {e}")

    with tabs[4]:
        st.subheader("📊 系统验证 (GSMI vs Nasdaq 周度版)")
        df_w = df.resample('W-FRI').last().dropna(subset=['gsmi_score', 'qqq'])
        norm_q = (df_w['qqq'] / df_w['qqq'].iloc[0]) * 100
        fig_v = go.Figure()
        fig_v.add_trace(go.Scatter(x=df_w.index, y=df_w['gsmi_score'], name="GSMI 评分", line=dict(color='#00ffcc', width=4), mode='lines+markers'))
        fig_v.add_trace(go.Scatter(x=df_w.index, y=norm_q, name="QQQ (归一化)", line=dict(color='#FFD700', dash='dot'), yaxis="y2"))
        st.plotly_chart(fig_v.update_layout(height=400, template="plotly_dark", yaxis=dict(title="GSMI", range=[0,100]), yaxis2=dict(overlaying="y", side="right", showgrid=False)), use_container_width=True)
        
        st.write("---")
        st.subheader("🌉 最后执行确认")
        hk1, hk2 = st.columns(2)
        with hk1:
            st.metric("港元汇率 (USD/HKD)", f"{latest['hkd']:.4f}", "吸金" if latest['hkd'] < 7.80 else "失血")
            if len(df) > 20:
                hsi_perf = (latest['hsi']/df['hsi'].iloc[-20] - 1)*100
                as300_perf = (latest['as300']/df['as300'].iloc[-20] - 1)*100
                st.write(f"📊 20日动能差 HSI vs AS300: {hsi_perf - as300_perf:+.2f}%")
        with hk2:
            st.markdown(f"[沽空比](http://www.aastocks.com/tc/stocks/market/shortselling/securities-eligible.aspx) | [信贷脉冲](https://www.macromicro.me/collections/31/cn-finance-relative/35559/china-credit-impulse-index) | [M1-M2剪刀差](https://www.macromicro.me/charts/260/cn-china-m1-m2)")
            st.slider("手动录入：大市沽空比率 (%)", 5.0, 35.0, 16.5, 0.1)

except Exception as e:
    st.error(f"系统错误: {e}")

st.markdown("---")
st.caption("GSMI Tactical | 45% 核心货币 (NL+TIPS) + 15% 全球汇率 (DXY) + 15% 机构情绪 (FMS) + 25% 宏观现实 (CuAu+Spread)")
