"""
美股 MACD 多週期策略掃描
------------------------------------------------
把原本分成三段的 Colab notebook 合併成單一腳本，
方便在 GitHub Actions 排程執行。

流程：
  1. 抓取 NASDAQ 全市場股票代號清單（含 GitHub 備援來源）
  2. 從 Google 試算表讀取「手動排除名單」，過濾掉不要的代號
     （試算表 ID 從環境變數 SHEET_ID 讀取，不寫死在程式碼中）
  3. 針對候選股票做月/週/日/4小時多週期 MACD 策略分類
  4. 針對分類結果做流動性二次篩選，輸出最終 Excel

輸出檔案：
  results/latest.xlsx        <- 每次執行都會覆蓋，固定路徑方便抓取
  results/YYYY-MM-DD.xlsx    <- 歷史存檔
"""

import io
import os
import sys
import time
import warnings
from datetime import datetime, timezone, timedelta

import numpy as np
import pandas as pd
import requests
import yfinance as yf
from tqdm import tqdm

warnings.simplefilter(action="ignore", category=FutureWarning)

RESULTS_DIR = "results"
os.makedirs(RESULTS_DIR, exist_ok=True)

# 台灣時間 (UTC+8) 的今天日期，用來命名歷史存檔
TW_TZ = timezone(timedelta(hours=8))
TODAY_STR = datetime.now(TW_TZ).strftime("%Y-%m-%d")

HISTORY_PERIOD = "5y"   # 日線抓長一點算月線
HISTORY_1H = "60d"      # 1 小時線
BATCH_SIZE = 100


# =========================================================
# Step 1. 取得 NASDAQ 全市場股票代號
# =========================================================
def get_nasdaq_symbols() -> list[str]:
    print("🚀 啟動：嘗試以「下載模式」抓取完整 NASDAQ 資料...")

    url = "https://api.nasdaq.com/api/screener/stocks"
    params = {"download": "true"}
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Referer": "https://www.nasdaq.com/",
    }

    final_symbols: list[str] = []

    try:
        resp = requests.get(url, headers=headers, params=params, timeout=45)
        resp.raise_for_status()
        payload = resp.json()
        csv_content = payload.get("data", {}).get("csv")
        if not csv_content:
            raise RuntimeError("API 回傳了 JSON 但沒有 CSV 內容")

        df = pd.read_csv(io.StringIO(csv_content))
        print(f"API 回傳欄位: {list(df.columns)}")
        df.columns = [c.lower() for c in df.columns]

        if "country" not in df.columns:
            print("⚠️ 警告：下載模式依然缺少 country 欄位，將跳過國家篩選...")
            df = df[~df["symbol"].str.contains(r"[\^.](W|U|R)", regex=True)]
        else:
            print("✅ 成功取得 country 欄位，執行美國股票篩選...")
            df = df[df["country"] == "United States"]

        df["symbol"] = df["symbol"].astype(str).str.strip()
        df = df[~df["symbol"].str.endswith(("W", "U", "R", "^"))]
        df = df[df["symbol"].str.len() <= 5]

        final_symbols = sorted(df["symbol"].unique())
        print(f"🎉 NASDAQ API 下載成功！取得 {len(final_symbols)} 檔股票。")

    except Exception as e:
        print(f"❌ NASDAQ API 失敗 ({e})。")
        print("🔄 正在切換至 GitHub 備份來源 (確保程式能跑完)...")
        try:
            backup_url = (
                "https://raw.githubusercontent.com/rreichel3/"
                "US-Stock-Symbols/main/all/all_tickers.txt"
            )
            r = requests.get(backup_url, timeout=30)
            symbols_list = r.text.splitlines()
            final_symbols = [s.strip().split(",")[0] for s in symbols_list if s.strip()]
            final_symbols = sorted(set(final_symbols))
            print(f"✅ 從備份源成功取得 {len(final_symbols)} 檔股票。")
        except Exception as e2:
            print(f"❌ 備份源也失敗: {e2}")

    return final_symbols


# =========================================================
# Step 2. 從 Google 試算表讀取手動排除名單
# =========================================================
def get_excluded_symbols() -> set[str]:
    sheet_id = os.environ.get("SHEET_ID")
    sheet_name = os.environ.get("SHEET_NAME") or "Sheet1"

    if not sheet_id:
        print("ℹ️ 未設定 SHEET_ID，略過手動排除名單。")
        return set()

    csv_url = (
        f"https://docs.google.com/spreadsheets/d/{sheet_id}"
        f"/gviz/tq?tqx=out:csv&sheet={sheet_name}"
    )

    try:
        resp = requests.get(csv_url, timeout=30)
        resp.raise_for_status()
        excl_df = pd.read_csv(io.StringIO(resp.text), header=None)
        raw_values = excl_df.values.flatten()
        excluded = {
            str(v).strip().upper()
            for v in raw_values
            if pd.notna(v) and str(v).strip()
        }
        print(f"✅ 從 Google 試算表讀取到 {len(excluded)} 檔排除代號。")
        return excluded
    except Exception as e:
        print(f"⚠️ 讀取排除名單失敗 ({e})，本次不排除任何代號。")
        return set()


# =========================================================
# 核心指標算法
# =========================================================
def get_tv_macd(close: pd.Series, fast=12, slow=26, signal_len=9):
    if len(close) < slow:
        return pd.Series(dtype=float), pd.Series(dtype=float)
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal_len, adjust=False).mean()
    return macd_line, signal_line


def check_divergence(close, macd, window=20):
    if len(close) < window:
        return False
    recent_low_price = close.iloc[-3:].min()
    window_low_price = close.iloc[-window:].min()
    price_broken = recent_low_price <= window_low_price * 1.005
    recent_low_macd = macd.iloc[-3:].min()
    window_low_macd = macd.iloc[-window:].min()
    macd_higher = recent_low_macd > window_low_macd
    return price_broken and macd_higher


def analyze_strategy(df_d, df_1h):
    df_m = df_d.resample("ME").agg({"Close": "last"}).dropna()
    if len(df_m) < 12:
        return None
    m_macd, _ = get_tv_macd(df_m["Close"])
    if m_macd.empty or m_macd.iloc[-1] <= 0:
        return None

    df_w = df_d.resample("W-FRI").agg({"Close": "last"}).dropna()
    if len(df_w) < 12:
        return None
    w_macd, _ = get_tv_macd(df_w["Close"])
    w_blue = w_macd.iloc[-1]

    d_macd, d_sig = get_tv_macd(df_d["Close"])
    d_blue = d_macd.iloc[-1]
    d_prev_blue = d_macd.iloc[-2]
    d_org = d_sig.iloc[-1]
    d_price = df_d["Close"].iloc[-1]

    has_4h = False
    h4_blue = h4_prev_blue = h4_org = h4_price = None
    if not df_1h.empty and len(df_1h) > 24:
        df_4h = df_1h.resample("4h").agg({"Close": "last"}).dropna()
        if len(df_4h) > 26:
            h4_macd, h4_sig = get_tv_macd(df_4h["Close"])
            has_4h = True
            h4_blue = h4_macd.iloc[-1]
            h4_prev_blue = h4_macd.iloc[-2]
            h4_org = h4_sig.iloc[-1]
            h4_price = df_4h["Close"].iloc[-1]

    d_hook_up = d_blue > d_prev_blue
    d_rising = d_blue > d_prev_blue
    d_gold_state = d_blue > d_org

    if w_blue < 0:
        if check_divergence(df_d["Close"], d_macd):
            dynamic_threshold = d_price * -0.015
            if (d_blue > dynamic_threshold) and d_gold_state:
                return "1. 信號反轉-底背離"

    if w_blue < 0:
        dynamic_threshold = d_price * -0.015
        if (d_blue < 0) and d_gold_state and d_hook_up and (d_blue > dynamic_threshold):
            return "2. 信號反轉-回升"

    if w_blue > 0:
        if (d_blue > 0) and d_gold_state and has_4h:
            h4_rising = h4_blue > h4_prev_blue
            if (h4_blue > 0) and h4_rising:
                if h4_blue > h4_org:
                    return "3. 機會入場"
                if h4_blue < h4_org:
                    if h4_blue <= (h4_price * 0.015):
                        return "3. 機會入場"

    if w_blue > 0:
        if (d_blue > 0) and d_gold_state and has_4h:
            h4_gold_state = h4_blue > h4_org
            h4_hook_up = h4_blue > h4_prev_blue
            dynamic_threshold_4h = h4_price * -0.015
            if (h4_blue < 0) and h4_gold_state and h4_hook_up and (h4_blue > dynamic_threshold_4h):
                return "4. 重新起漲"

    if w_blue > 0:
        if (d_blue > 0) and d_rising:
            if d_blue > d_org:
                return "5. 空中加油"
            if d_blue < d_org:
                if d_blue <= (d_price * 0.015):
                    return "5. 空中加油"

    return None


# =========================================================
# Step 3. 兩段式掃描：全域濾網 -> 型態分析
# =========================================================
def scan_symbols(symbols: list[str]) -> dict[str, list[str]]:
    candidates = []
    results = {
        "1. 信號反轉-底背離": [],
        "2. 信號反轉-回升": [],
        "3. 機會入場": [],
        "4. 重新起漲": [],
        "5. 空中加油": [],
    }

    print("🚀 階段一：批次下載日線並執行全域濾網...")
    for i in tqdm(range(0, len(symbols), BATCH_SIZE)):
        batch_syms = symbols[i : i + BATCH_SIZE]
        try:
            data = yf.download(
                batch_syms,
                period=HISTORY_PERIOD,
                group_by="ticker",
                threads=True,
                progress=False,
                auto_adjust=True,
            )
        except Exception:
            data = pd.DataFrame()

        for sym in batch_syms:
            try:
                df_d = pd.DataFrame()
                if len(batch_syms) == 1:
                    df_d = data
                elif sym in data.columns.levels[0]:
                    df_d = data[sym]

                if df_d.empty or df_d["Close"].isnull().all():
                    df_d = yf.Ticker(sym).history(period=HISTORY_PERIOD)

                if len(df_d) < 100:
                    continue

                df_m = df_d.resample("ME").agg({"Close": "last"}).dropna()
                if len(df_m) >= 12:
                    m_macd, _ = get_tv_macd(df_m["Close"])
                    if not m_macd.empty and m_macd.iloc[-1] > 0:
                        candidates.append((sym, df_d))
            except Exception:
                continue

    print(f"✅ 全域濾網篩選出 {len(candidates)} 檔潛力股，進入階段二 (型態分析)...")

    for sym, df_d in tqdm(candidates, desc="分析型態"):
        try:
            df_1h = yf.Ticker(sym).history(period=HISTORY_1H, interval="1h")
            category = analyze_strategy(df_d, df_1h)
            if category:
                results[category].append(sym)
        except Exception:
            continue

    return results


# =========================================================
# Step 4. 流動性二次篩選
# =========================================================
def liquidity_filter(results: dict[str, list[str]]) -> pd.DataFrame:
    stock_category_map = {}
    for col, syms in results.items():
        for s in syms:
            stock_category_map[s] = col

    target_codes = list(stock_category_map.keys())
    print(f"🔍 索引建立完成：共 {len(target_codes)} 檔美股需檢查流動性")

    if not target_codes:
        return pd.DataFrame({k: [] for k in results.keys()})

    valid_codes = []
    hist_data = {}

    try:
        print("   正在執行 Level 1 批次下載...")
        data = yf.download(
            target_codes,
            period="15d",
            group_by="ticker",
            threads=True,
            progress=False,
            auto_adjust=True,
        )
        if not data.empty:
            if len(target_codes) == 1:
                t = target_codes[0]
                if not data.empty and not data["Close"].isnull().all():
                    hist_data[t] = data
            else:
                for t in target_codes:
                    if t in data.columns.levels[0]:
                        d = data[t]
                        if not d["Close"].isnull().all():
                            hist_data[t] = d
    except Exception as e:
        print(f"   Level 1 發生錯誤 (不影響後續補抓): {e}")

    downloaded = set(hist_data.keys())
    missing = set(target_codes) - downloaded

    if missing:
        print(f"⚠️ 有 {len(missing)} 檔股票在批次下載時失敗，啟動 Level 2 補抓...")
        for t in tqdm(missing, desc="Level 2 補抓"):
            try:
                time.sleep(0.1)
                df_retry = yf.Ticker(t).history(period="3mo", auto_adjust=True)
                if not df_retry.empty and not df_retry["Close"].isnull().all():
                    hist_data[t] = df_retry
            except Exception:
                continue

    print("\n⚖️ 執行流動性判斷 (量>100萬 或 額>3000萬)...")
    for code, hist in hist_data.items():
        try:
            if len(hist) < 3:
                continue
            last_3 = hist.tail(3)
            vol = last_3["Volume"]
            amt = last_3["Close"] * last_3["Volume"]
            cond = (vol >= 1_000_000).any() or (amt >= 30_000_000).any()
            if cond:
                valid_codes.append(code)
        except Exception:
            continue

    print(f"📊 篩選完成！合格股票：{len(valid_codes)} 檔")

    result_dict = {col: [] for col in results.keys()}
    for code in valid_codes:
        category = stock_category_map.get(code)
        if category:
            result_dict[category].append(code)

    max_len = max((len(v) for v in result_dict.values()), default=0)
    for col in result_dict:
        result_dict[col].extend([None] * (max_len - len(result_dict[col])))

    return pd.DataFrame(result_dict)


# =========================================================
# 主流程
# =========================================================
def main():
    symbols = get_nasdaq_symbols()
    if not symbols:
        print("⚠️ 沒有股票代碼，程式結束。")
        sys.exit(1)

    # 存一份原始清單方便追蹤
    pd.DataFrame({"Symbol": symbols}).to_excel(
        os.path.join(RESULTS_DIR, "symbols_raw.xlsx"), index=False
    )

    excluded = get_excluded_symbols()
    if excluded:
        before = len(symbols)
        symbols = [s for s in symbols if s.upper() not in excluded]
        print(f"🧹 套用排除名單：{before} -> {len(symbols)} 檔")

    results = scan_symbols(symbols)

    print("\n✅ MACD 掃描完成！結果統計：")
    for k, v in results.items():
        print(f"👉 {k}: {len(v)} 檔")

    df_final = liquidity_filter(results)

    latest_path = os.path.join(RESULTS_DIR, "latest.xlsx")
    dated_path = os.path.join(RESULTS_DIR, f"{TODAY_STR}.xlsx")

    df_final.to_excel(latest_path, index=False)
    df_final.to_excel(dated_path, index=False)

    print(f"\n💾 已輸出：{latest_path}")
    print(f"💾 已輸出：{dated_path}")


if __name__ == "__main__":
    main()
