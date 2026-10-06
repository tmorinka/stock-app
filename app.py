import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import json
import os
import time
import unicodedata
from datetime import datetime, time as dtime, timezone, timedelta

# Googleスプレッドシート連携（未設定時は自動でJSONフォールバック）
try:
    from streamlit_gsheets import GSheetsConnection
    HAS_GSHEETS = True
except ImportError:
    HAS_GSHEETS = False

st.set_page_config(page_title="日本株スイングトレード (真・完成版)", layout="wide", initial_sidebar_state="collapsed")
st.title("🏹 スイングトレード統合分析システム (資金50万・完全防護版)")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WATCHLIST_FILE = os.path.join(BASE_DIR, "watchlist.json")
PORTFOLIO_FILE = os.path.join(BASE_DIR, "portfolio.json")

# 精鋭20銘柄
DEFAULT_WATCHLIST = {
    "ディスコ (6146)": "6146.T", "アドバンテスト (6857)": "6857.T", "東京エレクトロン (8035)": "8035.T",
    "ソシオネクスト (6526)": "6526.T", "フジクラ (5803)": "5803.T", "ソフトバンクG (9984)": "9984.T",
    "日立製作所 (6501)": "6501.T", "三菱重工業 (7011)": "7011.T", "信越化学工業 (4063)": "4063.T",
    "三菱UFJ (8306)": "8306.T", "三井住友FG (8316)": "8316.T", "野村HD (8604)": "8604.T",
    "オリックス (8591)": "8591.T", "三菱商事 (8058)": "8058.T", "丸紅 (8002)": "8002.T",
    "ENEOS HD (5020)": "5020.T", "トヨタ自動車 (7203)": "7203.T", "本田技研 (7267)": "7267.T",
    "川崎汽船 (9107)": "9107.T", "神戸製鋼所 (5406)": "5406.T"
}

# ==========================================
# ストレージ層 (GSheets ⇄ JSON)
# ==========================================
def is_gsheets_available():
    return HAS_GSHEETS and ("connections" in st.secrets) and ("gsheets" in st.secrets["connections"])

def load_json(path, default_data):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f: return json.load(f)
        except Exception: return default_data.copy()
    return default_data.copy()

def save_json(path, data):
    try:
        with open(path, "w", encoding="utf-8") as f: json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception: pass

def load_portfolio():
    if is_gsheets_available():
        try:
            df = st.connection("gsheets", type=GSheetsConnection).read(worksheet="portfolio", ttl=0)
            if df is not None and not df.empty:
                return {str(r["ticker"]).strip(): {
                    "name": str(r["name"]).strip(), "entry_date": str(r["entry_date"]).strip(),
                    "entry_price": float(pd.to_numeric(r["entry_price"], errors='coerce') or 0.0),
                    "shares": int(pd.to_numeric(r.get("shares", 1), errors='coerce') or 1)
                } for _, r in df.iterrows()}
        except Exception: pass
    return load_json(PORTFOLIO_FILE, {})

def save_portfolio(data):
    if is_gsheets_available():
        try:
            recs = [{"ticker": k, "name": v["name"], "entry_date": v["entry_date"], 
                     "entry_price": v["entry_price"], "shares": v.get("shares", 1)} for k, v in data.items()]
            df = pd.DataFrame(recs) if recs else pd.DataFrame(columns=["ticker", "name", "entry_date", "entry_price", "shares"])
            st.connection("gsheets", type=GSheetsConnection).update(worksheet="portfolio", data=df)
        except Exception: pass
    save_json(PORTFOLIO_FILE, data)

def load_watchlist():
    if is_gsheets_available():
        try:
            df = st.connection("gsheets", type=GSheetsConnection).read(worksheet="watchlist", ttl=0)
            if df is not None and not df.empty: return dict(zip(df["name"].astype(str), df["ticker"].astype(str)))
        except Exception: pass
    return load_json(WATCHLIST_FILE, DEFAULT_WATCHLIST)

def save_watchlist(data):
    if is_gsheets_available():
        try:
            df = pd.DataFrame(list(data.items()), columns=["name", "ticker"])
            st.connection("gsheets", type=GSheetsConnection).update(worksheet="watchlist", data=df)
        except Exception: pass
    save_json(WATCHLIST_FILE, data)

if "watchlist" not in st.session_state: st.session_state.watchlist = load_watchlist()
if "portfolio" not in st.session_state: st.session_state.portfolio = load_portfolio()
if "scan_results" not in st.session_state: st.session_state.scan_results = None
if "target_symbol" not in st.session_state:
    k = list(st.session_state.watchlist.keys())
    st.session_state.target_symbol = k[0] if k else ""

# 日本時間判定
JST = timezone(timedelta(hours=9))
now_jst = datetime.now(JST)
is_trading_hours = (now_jst.weekday() < 5) and (dtime(9, 0) <= now_jst.time() < dtime(18, 0))

if is_trading_hours:
    st.warning("⚠️ **【取引時間中またはデータ確定前】** 日足未確定のため判定が不安定になります。夜20時以降の確認を推奨します。")

# ==========================================
# サイドバー
# ==========================================
st.sidebar.header("📋 銘柄リスト管理")
if st.sidebar.button("🔄 精鋭20銘柄に初期化", use_container_width=True):
    st.session_state.watchlist = DEFAULT_WATCHLIST.copy()
    save_watchlist(st.session_state.watchlist)
    st.session_state.target_symbol = list(DEFAULT_WATCHLIST.keys())[0]
    st.session_state.scan_results = None
    st.rerun()

with st.sidebar.expander("➕ 銘柄を追加", expanded=False):
    c_raw = st.text_input("証券コード (例: 6146)")
    n_raw = st.text_input("銘柄名 (例: ディスコ)")
    if st.button("追加", use_container_width=True):
        code = "".join([c for c in unicodedata.normalize('NFKC', c_raw).strip() if c.isalnum() or c == '.'])
        name = unicodedata.normalize('NFKC', n_raw).strip()
        if code:
            t_fmt = code if code.endswith(".T") else f"{code}.T"
            d_name = f"{name} ({code})" if name else f"{code} ({code})"
            st.session_state.watchlist[d_name] = t_fmt
            save_watchlist(st.session_state.watchlist)
            st.session_state.target_symbol = d_name
            st.session_state.scan_results = None
            st.rerun()

w_keys = list(st.session_state.watchlist.keys())
if st.session_state.target_symbol not in w_keys: st.session_state.target_symbol = w_keys[0]
selected_name = st.sidebar.selectbox("個別分析銘柄", w_keys, index=w_keys.index(st.session_state.target_symbol))
st.session_state.target_symbol = selected_name
ticker = st.session_state.watchlist[selected_name]

with st.sidebar.expander("🗑️ 選択中の銘柄を削除", expanded=False):
    if st.button("この銘柄を削除", use_container_width=True):
        if len(st.session_state.watchlist) > 1:
            del st.session_state.watchlist[selected_name]
            save_watchlist(st.session_state.watchlist)
            st.session_state.target_symbol = list(st.session_state.watchlist.keys())[0]
            st.session_state.scan_results = None
            st.rerun()

# 保有管理
st.sidebar.markdown("---")
st.sidebar.header("💼 保有株管理")
with st.sidebar.expander("📝 保有株を登録 / 更新", expanded=False):
    p_name = st.selectbox("保有銘柄", w_keys, key="p_sel")
    p_code = st.session_state.watchlist[p_name]
    p_date = st.date_input("買付日", value=now_jst.date(), key="p_date")
    p_price = st.number_input("買付単価 (円)", value=1000.0, step=1.0, key="p_price")
    p_shares = st.number_input("保有株数", value=10, min_value=1, step=1, key="p_shares")
    if st.button("登録する", use_container_width=True):
        st.session_state.portfolio[p_code] = {"name": p_name, "entry_date": p_date.strftime("%Y-%m-%d"),
                                              "entry_price": float(p_price), "shares": int(p_shares)}
        save_portfolio(st.session_state.portfolio)
        st.session_state.scan_results = None
        st.rerun()

    if st.session_state.portfolio:
        del_k = st.selectbox("手仕舞い完了（解除）", list(st.session_state.portfolio.keys()), 
                             format_func=lambda x: st.session_state.portfolio[x]["name"], key="p_del")
        if st.button("保有リストから削除", use_container_width=True):
            del st.session_state.portfolio[del_k]
            save_portfolio(st.session_state.portfolio)
            st.session_state.scan_results = None
            st.rerun()

# 資金設定
st.sidebar.markdown("---")
st.sidebar.header("💰 資金・取引設定")
def clear_scan(): st.session_state.scan_results = None
unit_mode = st.sidebar.radio("取引単位", ["単元未満株 (1株単位 / S株推奨)", "単元株 (100株単位)"], on_change=clear_scan)
lot_step = 1 if "1株単位" in unit_mode else 100
total_capital = st.sidebar.number_input("口座資金 (円)", value=500_000, step=50_000, on_change=clear_scan)
risk_pct = st.sidebar.slider("1取引の許容損失 (%)", 1.0, 3.0, 2.0, 0.5, on_change=clear_scan)
enable_mkt_filter = st.sidebar.checkbox("日経平均フィルター適用", value=True, on_change=clear_scan)

# ==========================================
# データ取得
# ==========================================
@st.cache_data(ttl=300)
def load_data(sym, p="1y", i="1d"):
    try:
        data = yf.download(sym, period=p, interval=i, progress=False)
        if data is None or data.empty or len(data) < 5: return pd.DataFrame()
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(0 if 'Close' in data.columns.get_level_values(0) else -1)
        data = data.loc[:, ~data.columns.duplicated()]
        if data.index.tz is not None:
            data.index = data.index.tz_convert('Asia/Tokyo').tz_localize(None) if (sym.endswith(".T") or sym == "^N225") else data.index.tz_localize(None)
        data.index = pd.to_datetime(data.index).normalize()
        req_cols = ['Open', 'High', 'Low', 'Close'] if (sym.startswith("^") or sym.endswith("=X")) else ['Open', 'High', 'Low', 'Close', 'Volume']
        for col in req_cols: data[col] = pd.to_numeric(data[col], errors='coerce')
        return data.dropna(subset=req_cols)
    except Exception: return pd.DataFrame()

# ==========================================
# 指標計算（王道ロジック）
# ==========================================
def calculate_indicators(df_raw, n225_ok, use_filter, capital_limit, lot_size):
    df = df_raw.copy()
    c, h, l, o = df["Close"], df["High"], df["Low"], df["Open"]
    v = df["Volume"] if "Volume" in df.columns else pd.Series(1, index=df.index)

    df["SMA5"] = c.rolling(5).mean()
    df["SMA25"] = c.rolling(25).mean()
    df["SMA75"] = c.rolling(75).mean()
    df["Vol_SMA20"] = v.rolling(20).mean()

    # ATR (14)
    tr = pd.concat([(h - l), (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    df["ATR"] = tr.rolling(14).mean().fillna(c * 0.02)

    # RSI (14)
    delta = c.diff()
    gain = delta.where(delta > 0, 0.0).ewm(alpha=1/14, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0.0)).ewm(alpha=1/14, adjust=False).mean()
    df["RSI"] = 100 - (100 / (1 + (gain / (loss + 1e-9))))

    # MACD
    df["MACD"] = c.ewm(span=12, adjust=False).mean() - c.ewm(span=26, adjust=False).mean()
    df["Signal"] = df["MACD"].ewm(span=9, adjust=False).mean()
    df["MACD_Hist"] = df["MACD"] - df["Signal"]

    # 買いシグナル判定
    sma25_up = df["SMA25"] >= df["SMA25"].shift(5) * 0.998
    base_bull = (c > df["SMA25"]) & sma25_up

    dip_touch = (l <= df["SMA25"] * 1.015) & (l >= df["SMA25"] * 0.98) & (c >= df["SMA25"]) & (c > o)
    res_20 = h.shift(1).rolling(20).max()
    vol_up = v >= df["Vol_SMA20"] * 1.2
    breakout = (c > res_20) & vol_up

    df["Buy_Candidate"] = base_bull & (dip_touch | breakout)
    
    # セットアップ名の整合性修正
    df["Buy_Setup"] = np.where(df["Buy_Candidate"], np.where(breakout, "高値ブレイク", "25日線反発"), "-")

    # 【致命的欠陥1修正】資金制約チェック
    is_affordable = (c * lot_size) <= capital_limit
    df["Capital_Over"] = df["Buy_Candidate"] & (~is_affordable)

    if use_filter:
        df["Buy_Signal"] = df["Buy_Candidate"] & n225_ok & is_affordable
        df["Filtered_Out"] = df["Buy_Candidate"] & (~n225_ok) & is_affordable
    else:
        df["Buy_Signal"] = df["Buy_Candidate"] & is_affordable
        df["Filtered_Out"] = False

    return df

# ==========================================
# ポジション判定エンジン（【致命的欠陥2修正：建値防衛の完全発動】）
# ==========================================
def evaluate_position(df, ticker_code, portfolio):
    last = df.iloc[-1]
    c_val = float(last["Close"])
    atr = float(last["ATR"]) if (not np.isnan(last["ATR"]) and float(last["ATR"]) > 0) else c_val * 0.02
    initial_sl = max(c_val - (atr * 2.0), 1.0)

    is_held = ticker_code in portfolio
    pos = portfolio.get(ticker_code, None)

    # 【保有銘柄の判定】
    if is_held and pos:
        try:
            entry_ts = pd.to_datetime(pos["entry_date"]).tz_localize(None).normalize()
            rows = df[df.index >= entry_ts]
            days_held = max(len(rows) - 1, 0)
            entry_p = float(pos["entry_price"])
            gain_pct = ((c_val - entry_p) / entry_p) * 100

            # 保有期間の最高値を追跡
            pos_high = float(rows["High"].max()) if not rows.empty else c_val
            max_gain_pct = ((pos_high - entry_p) / entry_p) * 100

            hard_sl = entry_p - (atr * 2.0)

            # 1. ハードストップ割れ
            if c_val <= hard_sl:
                return f"🚨 損切り発動 ({gain_pct:+.1f}%)", 1, False, hard_sl

            # 2. タイムストップ (5営業日無風)
            if days_held >= 5 and gain_pct < 2.0:
                return f"🚨 タイムストップ撤退 (5日停滞・{gain_pct:+.1f}%)", 1, False, hard_sl

            # 3. 【致命的欠陥2修正】建値撤退トレール（一度+3%達成後、買値を割り込んだら即撤退）
            if max_gain_pct >= 3.0 and c_val <= entry_p:
                return f"🛡️ 建値撤退発動 (損失ゼロ防衛・{gain_pct:+.1f}%)", 2, False, entry_p

            # 4. トレンド終了 (終値が25日線を割り込む)
            if c_val < float(last["SMA25"]):
                return f"🔴 手仕舞い売却 (25日線割れ・{gain_pct:+.1f}%)", 2, False, hard_sl

            # 5. ホールド（利益に応じて防衛ラインを引き上げ）
            current_sl = entry_p if max_gain_pct >= 3.0 else hard_sl
            return f"📈 保有継続・ホールド ({days_held}日目・{gain_pct:+.1f}%)", 4, False, current_sl
        except Exception:
            return "📈 保有継続", 4, False, initial_sl

    # 【未保有銘柄の判定】
    if last["Buy_Signal"]:
        return "🟢 明日朝一【新規買い】", 3, True, initial_sl
    elif last.get("Capital_Over", False):
        return "⚠️ 資金超過 (買付不可)", 5, False, initial_sl
    elif last.get("Filtered_Out", False):
        return "⚠️ 地合いNG【見送り】", 6, False, initial_sl
    elif c_val < float(last["SMA25"]):
        return "🔴 25日線下（買い不可）", 8, False, initial_sl
    else:
        return "⚪ 様子見・待機", 7, False, initial_sl

# 地合い取得
@st.cache_data(ttl=300)
def get_market_env():
    try:
        n225 = load_data("^N225", p="3mo")
        n225_ok = bool((n225["Close"].iloc[-1] >= n225["Close"].rolling(25).mean().iloc[-1])) if (not n225.empty and len(n225) >= 25) else False
        n_stat = f"{int(round(float(n225['Close'].iloc[-1]))):,d} 円" if not n225.empty else "-"
        
        sp = load_data("^GSPC", p="1mo")
        sp_chg = ((sp["Close"].iloc[-1] - sp["Close"].iloc[-2]) / sp["Close"].iloc[-2] * 100) if len(sp) >= 2 else 0.0

        uj = load_data("JPY=X", p="1mo")
        uj_rate = float(uj["Close"].iloc[-1]) if not uj.empty else 150.0
        return n225_ok, n_stat, sp_chg, uj_rate
    except Exception: return False, "-", 0.0, 150.0

n225_ok, n_stat, sp_chg, uj_rate = get_market_env()

st.markdown("### 🌐 市場環境サマリー")
m1, m2, m3 = st.columns(3)
m1.metric("🇯🇵 日経平均", n_stat, "25日線上 (良好)" if n225_ok else "25日線下 (下落警戒)")
m2.metric("🇺🇸 米国S&P500", f"{sp_chg:+.2f} %", "急落警戒" if sp_chg <= -1.5 else "適正")
m3.metric("💴 ドル円", f"{uj_rate:.2f} 円")

tab1, tab2 = st.tabs(["🔍 個別銘柄・行動指示書", "🚀 一括スキャナー (全精鋭20銘柄)"])

# ==========================================
# TAB 1: 個別指示書
# ==========================================
with tab1:
    df = load_data(ticker)
    if df.empty or len(df) < 30:
        st.error(f"データ取得不可: {ticker}")
    else:
        df = calculate_indicators(df, n225_ok, enable_mkt_filter, total_capital, lot_step)
        latest = df.iloc[-1]
        close = float(latest["Close"])
        atr = float(latest["ATR"])
        sl_price = max(close - (atr * 2.0), 1.0)
        risk_per_share = max(close - sl_price, 1.0)
        
        # 【致命的欠陥1修正】厳密なロット制限（リスク枠・口座資金枠の双方を超えない安全計算）
        max_risk = total_capital * (risk_pct / 100.0)
        shares_by_risk = int(max_risk / risk_per_share)
        shares_by_capital = int(total_capital // close)
        
        ideal_shares = min(shares_by_risk, shares_by_capital)
        trade_shares = (ideal_shares // lot_step) * lot_step
        
        action_msg, priority, is_buy, active_sl = evaluate_position(df, ticker, st.session_state.portfolio)
        setup_name = latest["Buy_Setup"] if is_buy else "-"

        # ヘッダーメトリクス
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("現在値", f"{close:,.1f} 円")
        c2.metric("RSI (14)", f"{float(latest['RSI']):.1f}")
        c3.metric("25日移動平均", f"{float(latest['SMA25']):,.1f} 円")
        c4.metric(f"最低必要資金 ({lot_step}株)", f"{close * lot_step:,.0f} 円")

        st.markdown(f"## 📋 明日の行動指示: {selected_name}")
        
        if priority == 1:
            st.error(f"### 🚨 【即時撤退】{action_msg}\n明日朝の寄り付き成行ですべて売却してください。")
        elif priority == 2:
            st.error(f"### 🔴 【手仕舞い売却】{action_msg}\n明日朝の寄り付きで全量決済してください。")
        elif priority == 4:
            p_info = st.session_state.portfolio.get(ticker, {})
            p_price = p_info.get("entry_price", close)
            p_shares = p_info.get("shares", 1)
            p_profit = (close - p_price) * p_shares
            st.info(f"""
            ### 📈 【保有継続・ホールド中】
            * **状況:** {action_msg}
            * **保有損益:** **`{p_profit:+,.0f} 円`** (買値: {p_price:,.1f} 円 / 保有: {p_shares} 株)
            * **防衛逆指値ライン:** **`{active_sl:,.1f} 円`**（この価格を下回ったら即撤退）
            """)
        elif priority == 3:
            st.success(f"""
            ### 🟢 【買い指示】明日朝のエントリー準備
            * **推奨セットアップ:** **{setup_name}**
            * **推奨エントリー株数:** **`{trade_shares:,} 株`** (必要資金: 約 `{trade_shares * close:,.0f} 円` / 口座資金 `{total_capital:,.0f} 円`)
            * **初期損切り逆指値 (SL):** **`{sl_price:,.1f} 円`** (想定損失: 約 `-{trade_shares * risk_per_share:,.0f} 円` / 許容枠 `{max_risk:,.0f} 円`)
            * **利確目標 (TP / 1:2):** **`{close + (risk_per_share * 2.0):,.1f} 円`**
            * ⚠️ **執行注意:** 明日朝8:45の気配値が前日比+1.5%以上のギャップアップの場合は見送り。
            """)
        elif priority == 5:
            st.error(f"### ⚠️ 【買付資金不足】最低単位（{lot_step}株）の必要資金（約 {close * lot_step:,.0f} 円）が口座資金（{total_capital:,.0f} 円）を超過しています。")
        else:
            st.info(f"### ⚪ 【待機】{action_msg} トレンド発生まで静観してください。")

        # 【致命的欠陥4修正】売買サインマーカー付き4段統合チャート
        n = len(df)
        x_idx = list(range(n))
        d_strs = df.index.strftime('%Y-%m-%d').tolist()
        t_idx = np.linspace(0, n - 1, min(8, n), dtype=int).tolist()
        t_txt = [df.index[i].strftime('%m/%d') for i in t_idx]

        buy_idx = np.where(df["Buy_Signal"])[0].tolist()

        fig = make_subplots(rows=4, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.5, 0.15, 0.15, 0.2])
        fig.add_trace(go.Candlestick(x=x_idx, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name="株価"), row=1, col=1)
        fig.add_trace(go.Scatter(x=x_idx, y=df['SMA5'], line=dict(color='yellow', width=1), name='5日線'), row=1, col=1)
        fig.add_trace(go.Scatter(x=x_idx, y=df['SMA25'], line=dict(color='orange', width=2), name='25日線'), row=1, col=1)
        
        # 買いシグナルマーカーの描画
        if buy_idx:
            fig.add_trace(go.Scatter(x=buy_idx, y=(df['Low'].iloc[buy_idx] * 0.98), mode='markers',
                                     marker=dict(symbol='triangle-up', size=13, color='#00FF00'), name='買いサイン'), row=1, col=1)

        v_col = ['#FF4B4B' if c < o else '#00AA00' for c, o in zip(df['Close'], df['Open'])]
        fig.add_trace(go.Bar(x=x_idx, y=df['Volume'], marker_color=v_col, name='出来高'), row=2, col=1)
        fig.add_trace(go.Scatter(x=x_idx, y=df['Vol_SMA20'], line=dict(color='white', width=1), name='20日平均'), row=2, col=1)

        fig.add_trace(go.Scatter(x=x_idx, y=df['RSI'], line=dict(color='magenta', width=1.5), name='RSI'), row=3, col=1)
        fig.add_hline(y=70, line_dash="dash", line_color="red", row=3, col=1)
        fig.add_hline(y=30, line_dash="dash", line_color="lightgreen", row=3, col=1)

        fig.add_trace(go.Scatter(x=x_idx, y=df['MACD'], line=dict(color='aqua', width=1.2), name='MACD'), row=4, col=1)
        fig.add_trace(go.Scatter(x=x_idx, y=df['Signal'], line=dict(color='orange', width=1.2), name='Signal'), row=4, col=1)

        fig.update_layout(height=850, xaxis_rangeslider_visible=False, template="plotly_dark", margin=dict(l=20, r=20, t=20, b=20))
        fig.update_xaxes(tickmode='array', tickvals=t_idx, ticktext=t_txt)
        if n > 60: fig.update_xaxes(range=[n - 60, n + 2])
        st.plotly_chart(fig, use_container_width=True)

# ==========================================
# TAB 2: 一括スキャナー (【致命的欠陥3修正：ゼロ除算クラッシュ完全防御】)
# ==========================================
with tab2:
    st.markdown("### 📡 監視銘柄の一括スクリーニング (全精鋭20銘柄)")
    if st.button("一括スキャンを実行", use_container_width=True):
        results = []
        p_bar = st.progress(0.0)
        items = list(st.session_state.watchlist.items())
        max_risk = total_capital * (risk_pct / 100.0)

        for idx, (name, t_code) in enumerate(items):
            try:
                sub_df = load_data(t_code)
                if not sub_df.empty and len(sub_df) >= 30:
                    sub_df = calculate_indicators(sub_df, n225_ok, enable_mkt_filter, total_capital, lot_step)
                    c_val = float(sub_df["Close"].iloc[-1])
                    p_val = float(sub_df["Close"].iloc[-2])
                    atr_val = float(sub_df["ATR"].iloc[-1])
                    
                    action_msg, priority, is_buy, active_sl = evaluate_position(sub_df, t_code, st.session_state.portfolio)
                    
                    # 【致命的欠陥1&3修正】ゼロ除算防御と買付余力制限
                    risk_dist = max(c_val - active_sl, 1.0)
                    r_shares_risk = int(max_risk / risk_dist)
                    r_shares_cap = int(total_capital // c_val) if c_val > 0 else 0
                    
                    calc_shares = (min(r_shares_risk, r_shares_cap) // lot_step) * lot_step if is_buy else 0

                    results.append({
                        "_p": priority,
                        "推奨行動": action_msg,
                        "銘柄名": name,
                        "現在値": f"{c_val:,.1f} 円",
                        "前日比": f"{((c_val - p_val) / p_val * 100):+.2f}%",
                        "推奨株数": f"{calc_shares:,} 株" if is_buy and calc_shares > 0 else "-",
                        "想定投資額": f"{calc_shares * c_val:,.0f} 円" if is_buy and calc_shares > 0 else "-",
                        "防衛SL": f"{active_sl:,.1f} 円",
                        "型": sub_df["Buy_Setup"].iloc[-1] if is_buy else "-"
                    })
                else:
                    results.append({
                        "_p": 9, "推奨行動": "⚠️ データ取得エラー", "銘柄名": name,
                        "現在値": "-", "前日比": "-", "推奨株数": "-", "想定投資額": "-", "防衛SL": "-", "型": "-"
                    })
            except Exception:
                results.append({
                    "_p": 9, "推奨行動": "⚠️ 通信エラー", "銘柄名": name,
                    "現在値": "-", "前日比": "-", "推奨株数": "-", "想定投資額": "-", "防衛SL": "-", "型": "-"
                })
            p_bar.progress((idx + 1) / len(items))
            time.sleep(0.15)
        p_bar.empty()

        if results:
            res_df = pd.DataFrame(results).sort_values(by="_p").drop(columns=["_p"])
            st.session_state.scan_results = res_df.to_dict('records')

    if st.session_state.scan_results:
        st.dataframe(pd.DataFrame(st.session_state.scan_results), use_container_width=True, height=550)
        buys = [r["銘柄名"] for r in st.session_state.scan_results if "新規買い" in r["推奨行動"]]
        sells = [r["銘柄名"] for r in st.session_state.scan_results if "手仕舞い" in r["推奨行動"] or "撤退" in r["推奨行動"] or "損切り" in r["推奨行動"]]
        
        c1, c2 = st.columns(2)
        c1.success(f"🟢 **買い候補 ({len(buys)}銘柄):** {', '.join(buys) if buys else 'なし'}")
        c2.warning(f"🔴 **決済・撤退 ({len(sells)}銘柄):** {', '.join(sells) if sells else 'なし'}")