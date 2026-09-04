import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime, timedelta
from fredapi import Fred

# --- 1. 界面配置与核心人格 ---
st.set_page_config(page_title="GSMI Tactical | 首席风险官决策系统", layout="wide")

st.markdown("""
    <style>
    .main { background-color: #0e1117; }
    div[data-testid="stMetricValue"] { font-size: 26px; font-weight: bold; color: #00ffcc; }
    .standard-text { color: #aaa; font-size: 14px; margin-top: -10px; margin-bottom: 10px; font-weight: bold; }
    .quadrant-box { padding: 10px; border-radius: 5px; border: 1px solid #333; background-color: #1a1c24; text-align: center; min-height: 60px;}
    </style>
    """, unsafe_allow_html=True)

st.title("🏹 GSMI 全球聪明钱监控与验证系统")

# --- 动态 GSMI 战术状态机 ---
# 必须在算出 df 和 latest 变量之后调用
# 🚨 在此处打下空间锚点，预留给后面的状态机
status_placeholder = st.empty()

# --- 2. 侧边栏配置 ---
st.sidebar.header("🛠️ 核心参数配置")
target_name = st.sidebar.text_input("关注板块名称", "中国 AI 物理基建")
target_status = st.sidebar.radio("该板块目前拥挤度", ["冷清/低配", "标配", "极其拥挤"])

# --- 月度手动更新区 (FMS 调查) ---
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

if "fred_api_key" in st.secrets:
    fred_key = st.secrets["fred_api_key"]
else:
    fred_key = st.sidebar.text_input("FRED API Key", type="password")

if not fred_key:
    st.warning("⚠️ 请在侧边栏配置 FRED API Key。")
    st.stop()

fred = Fred(api_key=fred_key)

# --- 3. 核心审计函数 ---

def score_linear(val, min_val, max_val, max_score, reverse=False):
    if not reverse:
        score = (val - min_val) / (max_val - min_val) * max_score
    else:
        score = (max_val - val) / (max_val - min_val) * max_score
    return max(0, min(max_score, score))

def get_tga_forecast(curr_tga_billion, target_val):
    today = datetime.now()
    m, d = today.month, today.day
    msg, risk = "⚪ 【平稳周期】关注目标回归。", "Normal"
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
    status_report = {}
    
    # 1. 抓取 FRED (带 30 天容错与底层降级逻辑)
    fred_map = {
        'tips': 'DFII10', 'spread': 'BAMLH0A0HYM2', 'assets': 'WALCL',
        'tga': 'WTREGEN', 'rrp': 'RRPONTSYD', 'sofr': 'SOFR',
        'iorb': 'IORB', 'us2y': 'DGS2', 
        'term_premium': 'THREEFYTP10'  # 替换为美联储官方每日高频模型，防断更
    }
    data_dict = {}
    for key, fid in fred_map.items():
        try:
            # 物理溯源：提取时向左多捞 30 天，防止某些宏观数据存在发布黑洞
            s = fred.get_series(fid, start - timedelta(days=30), end)
            if not s.empty:
                data_dict[key] = s
                status_report[f"FRED:{key}"] = "✅"
            else:
                status_report[f"FRED:{key}"] = "❌ (Empty)"
        except Exception:
            # 如果 THREEFYTP10 偶尔抽风，备用回退到原 ACMTP10
            if key == 'term_premium':
                try:
                    s_fallback = fred.get_series('ACMTP10', start - timedelta(days=30), end)
                    if not s_fallback.empty:
                        data_dict[key] = s_fallback
                        status_report[f"FRED:{key}"] = "✅ (ACM)"
                        continue
                except: pass
            status_report[f"FRED:{key}"] = "❌"

    # 2. 抓取 Yahoo Finance (自动降维防护)
    def safe_get_yf(ticker, name):
        try:
            df = yf.download(ticker, start=start - timedelta(days=10), end=end, progress=False)
            if df is None or df.empty: 
                status_report[name] = "❌"
                return pd.Series(dtype='float64')
            data = df['Close'].iloc[:, 0] if isinstance(df.columns, pd.MultiIndex) else df['Close']
            status_report[name] = "✅"
            return data
        except:
            status_report[name] = "❌"
            return pd.Series(dtype='float64')

    yf_dict = {
        'dxy': safe_get_yf("DX-Y.NYB", "DXY"),
        'copper': safe_get_yf("HG=F", "Copper"),
        'gold': safe_get_yf("GC=F", "Gold"),
        'hkd': safe_get_yf("HKD=X", "HKD"),
        'hsi': safe_get_yf("^HSI", "HSI"),
        'as300': safe_get_yf("000300.SS", "AS300"),
        'btc': safe_get_yf("BTC-USD", "BTC"),
        'qqq': safe_get_yf("QQQ", "QQQ"),
        'chinext': safe_get_yf("159915.SZ", "ChiNext"),
        'move': safe_get_yf("^MOVE", "MOVE")
    }

    # --- 核心物理重构：7x24 全天候聚合 (Outer Join) ---
    all_series = {**data_dict, **yf_dict}
    # pandas DataFrame 接收字典时，会自动求取所有索引的并集，释放周末时间维度
    df = pd.DataFrame(all_series)
    
   # 清洗时间戳时区，强制对齐绝对时间
    df.index = pd.to_datetime(df.index).tz_localize(None)
    
    # 🚨 核心修复：强制时间熵减，恢复时间轴单调递增排列，否则无法切片
    df = df.sort_index() 
    
    # 按照严格请求时间范围切割，切除向左多捞的数据
    df = df.loc[start.replace(tzinfo=None):end.replace(tzinfo=None)]
    
    # 物理静默：周末或节假日没有交易的数据，继承前一个交易日的重力状态
    df = df.ffill()
    
    # 只清除在系统最开始连 QQQ 和 BTC 都没有的无效死数据
    df = df.dropna(subset=['qqq', 'btc'], how='all')
    
    # 二次合成衍生物理指标
    if not df.empty:
        df['nl'] = (df.get('assets', 0) - df.get('tga', 0).fillna(0) - df.get('rrp', 0).fillna(0)) / 1000000
        if 'copper' in df.columns and 'gold' in df.columns:
            df['cg_ratio'] = df['copper'] / df['gold']
        if 'sofr' in df.columns and 'iorb' in df.columns:
            df['sofr_spread'] = (df['sofr'] - df['iorb']) * 100
            
    return df, status_report

def calculate_history(df, fms_val):
    if df.empty: return df
    if 'spread' in df.columns and df['spread'].max() < 50: df['spread'] = df['spread'] * 100

    gsmi_history = []
    nl_ma4 = df['nl'].rolling(20).mean()
    
    for i in range(len(df)):
        if i < 20: gsmi_history.append(np.nan); continue
        s_nl = (15 if df['nl'].iloc[i] > nl_ma4.iloc[i] else 0) + (10 if df['nl'].iloc[i] > df['nl'].iloc[i-5] else 0)
        s_tips = score_linear(df['tips'].iloc[i], 0.5, 2.5, 20, reverse=True)
        s_dxy = score_linear(df['dxy'].iloc[i], 98, 108, 15, reverse=True)
        s_fms = score_linear(fms_val, 3.5, 6.0, 15, reverse=False)
        s_cg = (10 if df['cg_ratio'].iloc[i] > df['cg_ratio'].rolling(200).mean().iloc[i] else 0) + (5 if df['cg_ratio'].iloc[i] > df['cg_ratio'].iloc[i-10:i-5].mean() else 0)
        s_spread = score_linear(df['spread'].iloc[i], 300, 600, 10, reverse=True)
        gsmi_history.append(s_nl + s_tips + s_dxy + s_fms + s_cg + s_spread)
    
    df['gsmi_score'] = gsmi_history
    return df

# --- 4. 执行逻辑 ---

try:
    df_raw, report = fetch_and_sync_data()
    
    with st.expander("🛠️ 系统数据源健康审计", expanded=False):
        cols = st.columns(4)
        for i, (name, status) in enumerate(report.items()):
            cols[i % 4].write(f"{name}: {status}")

    if df_raw.empty:
        st.error("🚨 核心数据链路断裂。请检查 FRED API Key 或网络。")
        st.stop()
        
    df = calculate_history(df_raw, fms_cash)
    latest = df.iloc[-1]

    # --- 动态 GSMI 战术状态机 (注入顶部锚点) ---
    try:
        latest_date = df.index[-1].strftime('%Y.%m.%d')
        current_gsmi = latest['gsmi_score']
        
        # 防止数据量不够导致 nan 崩溃
        if pd.isna(current_gsmi):
            status_placeholder.warning("⚠️ 数据回溯期不足 20 天，无法计算 GSMI 重力。")
        else:
            if current_gsmi < 40:
                zone, action, icon = "窒息区", "严禁盲目抄底 | 强制维持 50% 现金对冲", "🚨"
            elif current_gsmi < 60:
                zone, action, icon = "重力震荡区", "严格控制仓位 | 在 200MA 下方寻找左侧吸气", "⚠️"
            else:
                zone, action, icon = "水源扩张区", "流动性充裕 | 对‘非你不可’标的执行右侧主攻", "🟢"

            # 逆向注入到顶部的 status_placeholder 中
            status_placeholder.markdown(f"""
            <div style='padding: 10px; border-radius: 5px; border: 1px solid #444; background-color: #1a1c24; margin-bottom: 20px;'>
                <h4 style='margin:0; color: #eee;'>
                    {icon} {latest_date} 战时状态 | 当前 GSMI: <strong>{current_gsmi:.1f} ({zone})</strong> 
                </h4>
                <p style='margin: 5px 0 0 0; font-size: 14px; color: #aaa; font-weight: bold;'>
                    ⚡ 战术执行指令：{action}
                </p>
            </div>
            """, unsafe_allow_html=True)

    except Exception as e:
        # 如果再次失败，强制吐出真实错误日志，绝不吞噬异常
        status_placeholder.error(f"🚨 状态机加载发生物理断裂: {e}")
    
    # 变量初始化
    nl_ma_last = df['nl'].rolling(20).mean().iloc[-1]
    s_nl_latest = (15 if latest['nl'] > nl_ma_last else 0) + (10 if latest['nl'] > df['nl'].iloc[-6] else 0)
    s_cg_latest = (10 if latest['cg_ratio'] > df['cg_ratio'].rolling(200).mean().iloc[-1] else 0) + (5 if latest['cg_ratio'] > df['cg_ratio'].iloc[-10:-5].mean() else 0)

    # --- 5. UI 展示 ---
    c1, c2 = st.columns([2, 1])
    with c1:
        st.plotly_chart(go.Figure(go.Indicator(
            mode = "gauge+number", value = latest['gsmi_score'],
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
        if 'sofr_spread' in latest:
            sofr_val = latest['sofr_spread']
            if sofr_val > 0: st.error(f"⚠️ 系统血压异常: SOFR-IORB {sofr_val:+.1f} bps")
            else: st.success(f"✅ 系统血压正常: SOFR-IORB {sofr_val:+.1f} bps")

    st.markdown("---")
    tabs = st.tabs(["💧 流动性水源", "🧠 情绪与购买力", "🏗️ 现实与防线", "🎯 Alpha 审计 (RS)", "🏛️ 债市审计", "📊 系统验证", "🛡️ 仓位风控"])
   
    with tabs[0]:
        st.subheader("🏦 核心流动性水源 (NL + TIPS + DXY)")
        t_msg, t_gap, t_risk = get_tga_forecast(latest['tga']/1000, tga_target)
        if t_risk == "High": st.error(t_msg)
        elif t_risk == "Low": st.success(t_msg)
        else: st.info(t_msg)
        
        col_t1, col_t2, col_t3 = st.columns(3)
        col_t1.metric("净流动性 (NL)", f"${latest['nl']:.2f}T", f"评分: {s_nl_latest}/25")
        col_t2.metric("10Y TIPS", f"{latest['tips']:.2f}%", f"评分: {score_linear(latest['tips'],0.5,2.5,20,True):.1f}/20")
        col_t3.metric("美元指数 (DXY)", f"{latest['dxy']:.2f}", f"评分: {score_linear(latest['dxy'],98,108,15,True):.1f}/15")
        
        fig_nl = go.Figure()
        fig_nl.add_trace(go.Scatter(x=df.index, y=df['nl'], name="净流动性(T)", line=dict(color='#00ffcc', width=3)))
        fig_nl.add_trace(go.Scatter(x=df.index, y=df['tips'], name="TIPS (%)", line=dict(color='#FF3131', dash='dot'), yaxis="y2"))
        fig_nl.update_layout(height=350, template="plotly_dark", yaxis=dict(title="NL (T)"), yaxis2=dict(overlaying="y", side="right", showgrid=False))
        st.plotly_chart(fig_nl, use_container_width=True)

    with tabs[1]:
        st.subheader("🧠 情绪与购买力监控")
        btc_ret = df['btc'].pct_change().dropna() * 100
        e1, e2 = st.columns([1, 2])
        with e1:
            st.metric("FMS 机构现金", f"{fms_cash}%", f"得分: {score_linear(fms_cash,3.5,6.0,15):.1f}/15")
            last_28d = btc_ret.tail(28)
            pos_days = len(last_28d[last_28d > 0])
            st.write(f"**BTC 28日情绪扫描**")
            st.caption(f"📈 上涨天数: {pos_days} | 📉 下跌天数: {len(last_28d)-pos_days}")
            if pos_days >= 18: st.success("🔥 投机情绪极度活跃")
            elif pos_days <= 10: st.error("❄️ 流动性极度低迷")
            else: st.info("⚖️ 风险偏好震荡中")
        with e2:
            st.plotly_chart(go.Figure(go.Bar(x=last_28d.index, y=last_28d.values, marker_color=['#00ffcc' if x>0 else '#FF3131' for x in last_28d])).update_layout(height=250, template="plotly_dark", margin=dict(l=10, r=10, t=40, b=10)), use_container_width=True)
        st.line_chart(df['btc'].tail(120), height=200)

    with tabs[2]:
        st.subheader("🏗️ 现实增长与信用防线")
        r1, r2 = st.columns(2)
        with r1:
            cg_val = latest['cg_ratio']
            st.metric("铜金比趋势", f"{cg_val:.4f}", f"评分: {s_cg_latest}/15")
            fig_cg = go.Figure()
            fig_cg.add_trace(go.Scatter(x=df.index[-180:], y=df['cg_ratio'].tail(180), name="铜金比", line=dict(color='#00ffcc', width=3)))
            fig_cg.add_trace(go.Scatter(x=df.index[-180:], y=df['cg_ratio'].rolling(200).mean().tail(180), name="200MA", line=dict(color='orange', width=2, dash='dash')))
            fig_cg.update_layout(height=300, template="plotly_dark", yaxis=dict(tickformat=".4f"))
            st.plotly_chart(fig_cg, use_container_width=True)
        with r2:
            sp_val = latest['spread']
            st.metric("高收益债利差", f"{sp_val:.0f} bps", f"评分: {score_linear(sp_val,300,600,10,True):.1f}/10")
            fig_spread = go.Figure()
            fig_spread.add_trace(go.Scatter(x=df.index[-180:], y=df['spread'].tail(180), name="利差", line=dict(color='#00ffcc', width=3)))
            fig_spread.add_trace(go.Scatter(x=df.index[-180:], y=[500]*180, name="500bps", line=dict(color='orange', width=2, dash='dash')))
            fig_spread.update_layout(height=300, template="plotly_dark")
            st.plotly_chart(fig_spread, use_container_width=True)

    with tabs[3]:
        st.subheader("🎯 Alpha 审计 (Relative Strength)")
        
        # --- 模块 1：战略资产猎杀雷达 (动态槽位) ---
        st.write("### 🦅 猎杀雷达：RS 拐点与 200MA 突破监测")
        
        # 预设的战略物理资产池
        default_snipers = ['COPX', 'URA', '159326.SZ', '159558.SZ', '512670.SS']
        sniper_cols = st.columns(5)
        sniper_tickers = []
        
        # 生成 5 个动态输入框
        for i in range(5):
            val = sniper_cols[i].text_input(f"猎杀槽位 {i+1}", default_snipers[i])
            if val:
                sniper_tickers.append(val.strip())
                
        benchmark_ticker = 'as300' # 默认 Beta 基准
        
        sniper_results = []
        for t in sniper_tickers:
            try:
                # 调取充足的历史数据以计算 200MA
                t_data = yf.download(t, start=df.index[0] - timedelta(days=300), end=df.index[-1], progress=False)
                if t_data.empty: 
                    sniper_results.append({"资产代码": t, "系统指令": "❌ 物理数据抓取为空", "RS前置斜率": "-", "RS当前斜率": "-", "当前价/200MA": "-", "量能倍率(VR)": "-"})
                    continue
                    
                t_close = t_data['Close'].iloc[:, 0] if isinstance(t_data.columns, pd.MultiIndex) else t_data['Close']
                t_vol = t_data['Volume'].iloc[:, 0] if isinstance(t_data.columns, pd.MultiIndex) else t_data['Volume']
                
                # 🚨 强制时区粉碎，确保跨国资产（美股/A股）时间轴能完美对齐
                t_close.index = pd.to_datetime(t_close.index).tz_localize(None)
                t_vol.index = pd.to_datetime(t_vol.index).tz_localize(None)
                
                # 计算 200MA (防范上市不足 200 天的新股)
                if len(t_close) < 200: 
                    sniper_results.append({"资产代码": t, "系统指令": "⚠️ 上市不足200天，无引力参考", "RS前置斜率": "-", "RS当前斜率": "-", "当前价/200MA": "-", "量能倍率(VR)": "-"})
                    continue
                ma200 = t_close.rolling(200).mean()
                
                # 1. 200MA 突破判定：今日站上且 3 日前在下方
                is_breakout = (t_close.iloc[-1] > ma200.iloc[-1]) and (t_close.iloc[-4] < ma200.iloc[-4])
                
                # 2. 量能燃料判定：VR > 1.5
                vr = t_vol.iloc[-1] / t_vol.iloc[-6:-1].mean()
                is_forceful = vr > 1.5
                
                # 3. RS 斜率拐点判定
                rs_df = pd.DataFrame({'target': t_close, 'base': df[benchmark_ticker]}).ffill().dropna()
                if len(rs_df) < 25: 
                    sniper_results.append({"资产代码": t, "系统指令": "⚠️ 动能对比数据不足", "RS前置斜率": "-", "RS当前斜率": "-", "当前价/200MA": "-", "量能倍率(VR)": "-"})
                    continue
                
                rs_curve = rs_df['target'] / rs_df['base']
                current_slope = (rs_curve.iloc[-1] / rs_curve.iloc[-10]) - 1
                prev_slope = (rs_curve.iloc[-10] / rs_curve.iloc[-20]) - 1
                
                # 由负转正
                rs_turned_positive = (prev_slope < 0) and (current_slope > 0)
                
                # 综合战术裁决
                if is_breakout and is_forceful and rs_turned_positive:
                    action = "🔥 猎杀确认 (全条件达成)"
                elif rs_turned_positive:
                    action = "🟡 RS 苏醒 (等待 200MA 突破)"
                elif is_breakout and not is_forceful:
                    action = "⚠️ 无量诱多 (VR不足)"
                else:
                    action = "❄️ 重力压制中 (蛰伏)"
                    
                sniper_results.append({
                    "资产代码": t,
                    "RS前置斜率": f"{prev_slope*100:.2f}%",
                    "RS当前斜率": f"{current_slope*100:.2f}%",
                    "当前价/200MA": f"{(t_close.iloc[-1]/ma200.iloc[-1]):.2f}",
                    "量能倍率(VR)": f"{vr:.2f}",
                    "系统指令": action
                })
            except Exception as e:
                # 绝对不静默：如果代码崩溃，把错误直接打印在面板上
                sniper_results.append({"资产代码": t, "系统指令": f"❌ 运算断裂", "RS前置斜率": "-", "RS当前斜率": "-", "当前价/200MA": "-", "量能倍率(VR)": "-"})

        if sniper_results:
            st.table(pd.DataFrame(sniper_results))
        else:
            st.info("雷达扫描中：未获取到标的物理数据。")
            
        st.write("---")
        
        # --- 模块 2：保留的原有单项深度动能扫描 (并恢复图表) ---
        st.write("### 🔍 单项深度动能扫描")
        audit_ticker = st.text_input("输入要详细审计的标的代码", "159326.SZ", key="single_audit")
        if audit_ticker:
            try:
                # 为了画出 250MA，这里强制往前多抓 350 天的数据
                a_data = yf.download(audit_ticker, start=df.index[0]-timedelta(days=350), end=df.index[-1], progress=False)
                if not a_data.empty:
                    a_close = a_data['Close'].iloc[:, 0] if isinstance(a_data.columns, pd.MultiIndex) else a_data['Close']
                    a_vol = a_data['Volume'].iloc[:, 0] if isinstance(a_data.columns, pd.MultiIndex) else a_data['Volume']
                    vr = a_vol.iloc[-1] / a_vol.iloc[-6:-1].mean()
                    
                    rs_df = pd.DataFrame({'target': a_close, 'base': df['as300']}).ffill().dropna()
                    rs_ratio = rs_df['target'] / rs_df['base']
                    curr_rs = rs_ratio.iloc[-1]
                    slope_single = (curr_rs / rs_ratio.iloc[-6] - 1) * 100
                    
                    # 输出核心指标
                    v1, v2, v3 = st.columns(3)
                    v1.metric("量能倍率 (VR)", f"{vr:.2f}", "🔥 爆发" if vr > 1.5 else "⚖️ 平稳")
                    v2.metric("相对强度 (RS)", f"{curr_rs:.6f}", f"5日斜率: {slope_single:+.2f}%")
                    v3.write(f"**审计判定：{'🔥 强 Alpha' if curr_rs > rs_ratio.rolling(20).mean().iloc[-1] else '❄️ 弱 Beta'}**")
                    
                    # 恢复 RS 物理曲线图表
                    fig_rs = go.Figure()
                    fig_rs.add_trace(go.Scatter(x=rs_ratio.index[-250:], y=rs_ratio.values[-250:], name="RS 曲线", line=dict(color='#00ffcc', width=3)))
                    fig_rs.add_trace(go.Scatter(x=rs_ratio.index[-250:], y=rs_ratio.rolling(20).mean().tail(250), name="20MA", line=dict(color='white', dash='dot')))
                    fig_rs.add_trace(go.Scatter(x=rs_ratio.index[-250:], y=rs_ratio.rolling(250).mean().tail(250), name="250MA", line=dict(color='orange', width=2, dash='dash')))
                    st.plotly_chart(fig_rs.update_layout(height=400, template="plotly_dark", legend=dict(orientation="h", y=1.1)), use_container_width=True)
            except Exception:
                st.warning("系统无法审计该标的，物理特征不匹配或数据抓取失败。")

    with tabs[4]:
        st.subheader("🏛️ 债市重力审计")
        b1, b2, b3 = st.columns(3)
        b1.metric("MOVE 指数", f"{latest.get('move', 0):.1f}", "🟡 警戒" if latest.get('move', 0) > 100 else "🟢 平稳")
        b2.metric("2Y 美债收益率", f"{latest.get('us2y', 0):.2f}%")
        b3.metric("10Y 期限溢价", f"{latest.get('term_premium', 0):.2f}")
        fig_bond = go.Figure()
        if 'us2y' in df.columns:
            fig_bond.add_trace(go.Scatter(x=df.index[-120:], y=df['us2y'].tail(120), name="2Y 收益率", line=dict(color='#FF3131', width=3)))
            fig_bond.add_trace(go.Scatter(x=df.index[-120:], y=df['us2y'].rolling(50).mean().tail(120), name="50MA", line=dict(color='white', dash='dot')))
        if 'move' in df.columns:
            fig_bond.add_trace(go.Scatter(x=df.index[-120:], y=df['move'].tail(120), name="MOVE (右轴)", line=dict(color='#00ffcc', width=2, dash='dash'), yaxis="y2"))
        st.plotly_chart(fig_bond.update_layout(height=450, template="plotly_dark", yaxis2=dict(overlaying="y", side="right", showgrid=False)), use_container_width=True)

    with tabs[5]:
        st.subheader("📊 系统验证")
        df_resample = df.copy()
        df_resample.index = pd.to_datetime(df_resample.index)
        df_w = df_resample.resample('W-FRI').last().dropna(subset=['gsmi_score', 'qqq'])
        if not df_w.empty:
            fig_v = go.Figure()
            fig_v.add_trace(go.Scatter(x=df_w.index, y=df_w['gsmi_score'], name="GSMI 评分", line=dict(color='#00ffcc', width=4), mode='lines+markers'))
            fig_v.add_trace(go.Scatter(x=df_w.index, y=(df_w['qqq']/df_w['qqq'].iloc[0])*100, name="QQQ (归一化)", line=dict(color='#FFD700', dash='dot'), yaxis="y2"))
            st.plotly_chart(fig_v.update_layout(height=400, template="plotly_dark", yaxis2=dict(overlaying="y", side="right", showgrid=False)), use_container_width=True)
        
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

    with tabs[6]:
        st.subheader("🛡️ CRO 仓位几何学与动态重力风控")
        st.markdown("基于 **ATR (真实波动)** 与 **生命周期匹配** 的头寸计算器。")
        
        # 风险参数面板
        r1, r2, r3 = st.columns(3)
        total_capital = r1.number_input("账户总本金 (¥/$)", value=1000000, step=100000)
        risk_tolerance = r2.number_input("单笔最大物理亏损容忍度 (%)", value=1.0, step=0.1, max_value=5.0)
        risk_multiplier = r3.number_input("止损宽度 (倍数 ATR)", value=2.0, step=0.1)
        
        st.write("---")
        
        c1, c2 = st.columns([1, 2])
        with c1:
            target_ticker = st.text_input("输入建仓资产代码 (如 159326.SZ)", value="159326.SZ")
        with c2:
            # 引入动态生命周期校验
            asset_stage = st.selectbox(
                "强制确认：该资产当前所处物理生命周期", 
                [
                    "A. 叙事孵化期 (无真实FCF, 高Capex烧钱)", 
                    "B. 物理碰撞期 (遭遇产能/良率瓶颈, 利润波动)", 
                    "C. 奇点兑现期 (物理瓶颈被击穿, 真实FCF爆发)", 
                    "D. 平庸公用事业期 (产能过剩, 沦为纯 Beta)"
                ],
                index=2 # 默认选项
            )
        
        if target_ticker:
            # 动态物理冲突审计
            try:
                current_tips = df['tips'].iloc[-1]
            except:
                current_tips = 2.0 # 容错默认值
                
            if "A. 叙事孵化" in asset_stage and current_tips > 2.1:
                st.warning(f"🚨 CRO 宏观冲突预警：当前处于高重力环境 (TIPS {current_tips:.2f}% > 2.1%)。高息将极大压制无自由现金流的叙事类资产估值。此笔交易属于高重力逆势博弈，建议进一步压缩单笔亏损容忍度。")
            elif "D. 平庸公用事业" in asset_stage and current_tips > 2.1:
                st.warning(f"⚠️ CRO Beta警报：当前重力偏高，缺乏高成长的公用事业资产易被抽水机效应错杀，请严格执行止损纪律。")
            elif "C. 奇点兑现" in asset_stage:
                st.success("✅ CRO 物理匹配：具备真实 FCF 的资产是高重力时代的优质收税人，准许按常规参数测算。")

            
            try:
                # 强制脱离主 df 依赖，独立捞取 150 天，确保绝对有 14 个有效交易日
                fetch_start = datetime.now() - timedelta(days=150)
                p_data = yf.download(target_ticker, start=fetch_start, end=datetime.now(), progress=False)
                
                if not p_data.empty:
                    # 🚨 核心修复：暴力清洗 Yahoo Finance 经常缺失的 High/Low 数据空洞
                    p_data = p_data.ffill().dropna()
                    
                    if len(p_data) < 15:
                        st.error(f"物理有效数据点仅剩 {len(p_data)} 天，不足以计算 14 日 ATR。该资产可能刚上市，或处于长期停牌状态。")
                    else:
                        close_col = p_data['Close'].iloc[:, 0] if isinstance(p_data.columns, pd.MultiIndex) else p_data['Close']
                        high_col = p_data['High'].iloc[:, 0] if isinstance(p_data.columns, pd.MultiIndex) else p_data['High']
                        low_col = p_data['Low'].iloc[:, 0] if isinstance(p_data.columns, pd.MultiIndex) else p_data['Low']
                        
                        # 强制时区对齐，防止索引错乱
                        close_col.index = pd.to_datetime(close_col.index).tz_localize(None)
                        high_col.index = pd.to_datetime(high_col.index).tz_localize(None)
                        low_col.index = pd.to_datetime(low_col.index).tz_localize(None)
                        
                        prev_close = close_col.shift(1)
                        tr1 = high_col - low_col
                        tr2 = (high_col - prev_close).abs()
                        tr3 = (low_col - prev_close).abs()
                        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
                        
                        atr = tr.rolling(14).mean().iloc[-1]
                        current_price = close_col.iloc[-1]
                        
                        if pd.isna(atr) or current_price == 0:
                            st.error("洗盘后仍然存在不可修复的价格黑洞，计算物理断裂。")
                        else:
                            stop_loss_distance = atr * risk_multiplier
                            hard_stop_price = current_price - stop_loss_distance
                            max_loss_amount = total_capital * (risk_tolerance / 100)
                            
                            shares_to_buy = int(max_loss_amount / stop_loss_distance)
                            if ".SZ" in target_ticker or ".SS" in target_ticker or ".HK" in target_ticker:
                                shares_to_buy = (shares_to_buy // 100) * 100
                                
                            total_exposure = shares_to_buy * current_price
                            exposure_pct = (total_exposure / total_capital) * 100
                            
                            if total_exposure > total_capital:
                                shares_to_buy = int(total_capital / current_price)
                                if ".SZ" in target_ticker or ".SS" in target_ticker or ".HK" in target_ticker:
                                    shares_to_buy = (shares_to_buy // 100) * 100
                                total_exposure = shares_to_buy * current_price
                                exposure_pct = (total_exposure / total_capital) * 100
                                st.info("💡 该资产极低波动，按风险模型计算已超总本金，强行截断至 100% 满仓限制。")
                            
                            st.write("### ⚙️ 战术执行参数")
                            metrics_cols = st.columns(4)
                            metrics_cols[0].metric("当前标的价", f"{current_price:.3f}")
                            metrics_cols[1].metric("14日物理波动 (ATR)", f"{atr:.3f}")
                            metrics_cols[2].metric("绝对止损线 (硬编码)", f"{hard_stop_price:.3f}", f"回撤 {risk_multiplier} 倍 ATR", delta_color="inverse")
                            metrics_cols[3].metric("最大允许亏损金额", f"{max_loss_amount:,.2f}")
                            
                            st.markdown(f"""
                            <div class='quadrant-box' style='background-color: #112211; border-color: #00ffcc;'>
                                <h3 style='color: #00ffcc; margin-bottom: 5px;'>🚀 最终物理买入指令</h3>
                                <p style='font-size: 18px; margin: 0;'>
                                    买入上限：<strong>{shares_to_buy:,} 股/份</strong> <br>
                                    资金占用：<strong>{total_exposure:,.2f} ({exposure_pct:.1f}%)</strong>
                                </p>
                            </div>
                            """, unsafe_allow_html=True)
                else:
                    st.error("数据抓取完全为空，请检查代码是否正确（如后缀 .SS/.SZ）。")
            except Exception as e:
                st.error(f"计算发生物理断裂: {e}")
# ==========================================
        # 追加模块：资产流体力学 (相关性维度坍塌检测)
        # ==========================================
        st.write("---")
        st.subheader("🕸️ 资产流体力学：组合维度坍塌检测")
        st.markdown("计算持仓池底层物理相关性。如果资产间相关系数 **> 0.8**，意味着你正在同一个雷区重复下注。")
        
        corr_input = st.text_input("输入当前持仓或拟建仓组合 (逗号分隔)", value="159326.SZ, 159516.SZ, COPX, URA, 162411.SZ")
        
        if corr_input:
            corr_tickers = [x.strip() for x in corr_input.split(",") if x.strip()]
            if len(corr_tickers) > 1:
                try:
                    # 抓取过去 60 天的收盘价来计算短期真实相关性
                    c_data = yf.download(corr_tickers, start=datetime.now() - timedelta(days=90), end=datetime.now(), progress=False)
                    
                    if not c_data.empty:
                        # 修复 Yahoo Finance 单/多标的返回结构的物理差异
                        if isinstance(c_data.columns, pd.MultiIndex):
                            c_close = c_data['Close']
                        else:
                            c_close = pd.DataFrame({corr_tickers[0]: c_data['Close']})
                            
                        # 物理清洗：时区对齐与空值过滤
                        c_close.index = pd.to_datetime(c_close.index).tz_localize(None)
                        c_close = c_close.ffill().dropna()
                        
                        # 计算每日收益率并得出相关性矩阵 (Pearson)
                        returns = c_close.pct_change().dropna()
                        corr_matrix = returns.corr()
                        
                        # 检测是否存在“维度坍塌” (相关性 > 0.8)
                        collapse_pairs = []
                        for i in range(len(corr_matrix.columns)):
                            for j in range(i+1, len(corr_matrix.columns)):
                                if corr_matrix.iloc[i, j] > 0.8:
                                    collapse_pairs.append(f"{corr_matrix.columns[i]} & {corr_matrix.columns[j]} (相关系数: {corr_matrix.iloc[i, j]:.2f})")
                        
                        if collapse_pairs:
                            st.error("🚨 致命风控警告：检测到组合维度坍塌！以下资产底层相关性极高，遭遇宏观重力抛售时将产生同向踩踏：")
                            for pair in collapse_pairs:
                                st.write(f"- {pair}")
                        else:
                            st.success("✅ 组合正交化良好：未检测到极度相关的资产对，防线具备物理层次。")
                        
                        # 渲染热力图
                        fig_corr = go.Figure(data=go.Heatmap(
                            z=corr_matrix.values,
                            x=corr_matrix.columns,
                            y=corr_matrix.columns,
                            colorscale='RdBu',
                            zmin=-1, zmax=1,
                            text=np.round(corr_matrix.values, 2),
                            texttemplate="%{text}",
                            hoverinfo="text"
                        ))
                        fig_corr.update_layout(
                            height=400, 
                            template="plotly_dark",
                            title="近 60 日底层物理相关系数矩阵 (-1 至 1)"
                        )
                        st.plotly_chart(fig_corr, use_container_width=True)
                except Exception as e:
                    st.warning(f"相关性计算发生断裂: {e}")
            else:
                st.info("至少需要输入 2 个标的才能计算相关性。")

except Exception as e:
    st.error(f"系统运行中发生错误: {e}")

st.markdown("---")
st.caption("GSMI Tactical | 45% 核心货币 + 15% 全球汇率 + 15% 机构情绪 + 25% 宏观现实")
