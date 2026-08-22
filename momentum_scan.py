"""
美股「動能選股」掃描（均線多頭排列 + 型態判斷 + 流動性複篩）
------------------------------------------------
把原本六段式的 Colab notebook 合併成單一腳本，
方便在 GitHub Actions 排程執行，與 scan_stocks.py（MACD 版）共用同一個
排程觸發時間、同一組 Google 試算表排除名單 (SHEET_ID / SHEET_NAME)。

保留原本程式碼的邏輯與篩選條件，只做以下調整：
  - 拿掉 Colab 專屬的 /content/ 路徑
  - Google 試算表 ID／分頁名稱改從環境變數讀取，不寫死在程式碼裡
  - 輸出檔案固定存到 results/ 資料夾，並同時保留 latest 版與帶日期的歷史版
  - 流動性複篩只保留「嚴格版」（近三天每一天都要符合量能條件），
    寬鬆版已依使用者要求移除

流程：
  1. 抓取 NASDAQ 全市場股票代號清單（含 GitHub 備援來源）
  2. 讀取 Google 試算表排除名單，過濾掉黑名單與含 $ 的代號
  3. 強勢股篩選（均線多頭排列 + 型態 A/B/C + 量能 + 站穩 EMA52）
  4. 持續走升篩選（均線多頭排列 + 強勢收盤）
  5. 合併去重（強勢優先）
  6. 流動性複篩：嚴格版（近三天每一天都要符合，並輸出失敗代碼清單）
"""

import io
import os
import time
from datetime import datetime, timezone, timedelta

import pandas as pd
import requests
import yfinance as yf
from tqdm import tqdm

RESULTS_DIR = "results"
os.makedirs(RESULTS_DIR, exist_ok=True)

TW_TZ = timezone(timedelta(hours=8))
TODAY_STR = datetime.now(TW_TZ).strftime("%Y-%m-%d")


def out_paths(base_name: str):
    """回傳 (latest 路徑, 帶日期路徑)"""
    latest = os.path.join(RESULTS_DIR, f"{base_name}_latest.xlsx")
    dated = os.path.join(RESULTS_DIR, f"{base_name}_{TODAY_STR}.xlsx")
    return latest, dated


def save_both(df: pd.DataFrame, base_name: str):
    latest, dated = out_paths(base_name)
    df.to_excel(latest, index=False)
    df.to_excel(dated, index=False)
    print(f"💾 已輸出：{latest}")
    print(f"💾 已輸出：{dated}")


# =========================================================
# Step 1. 取得 NASDAQ 全市場股票代號（與 scan_stocks.py 相同邏輯）
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
# Step 2. 讀取 Google 試算表排除名單（與使用者原本程式碼相同：只取第一欄）
# =========================================================
def get_delete_list() -> list[str]:
    sheet_id = os.environ.get("SHEET_ID")
    sheet_name = os.environ.get("SHEET_NAME") or "Sheet1"

    if not sheet_id:
        print("ℹ️ 未設定 SHEET_ID，略過排除名單。")
        return []

    csv_url = (
        f"https://docs.google.com/spreadsheets/d/{sheet_id}"
        f"/gviz/tq?tqx=out:csv&sheet={sheet_name}"
    )

    try:
        df_delete = pd.read_csv(csv_url)
        delete_list = df_delete.iloc[:, 0].dropna().astype(str).str.upper().tolist()
        print(f"✅ 已成功讀取 Google 試算表排除名單，共 {len(delete_list)} 檔。")
        return delete_list
    except Exception as e:
        print(f"⚠️ 讀取排除名單失敗 ({e})，本次不排除任何代號。")
        return []


# =========================================================
# 型態判斷（強勢股篩選）
# =========================================================
def classify_stock(df_hist: pd.DataFrame):
    if df_hist.empty or len(df_hist) < 60:
        return None

    close = df_hist["Close"]
    vol = df_hist["Volume"]
    open_ = df_hist["Open"]

    ema5 = close.ewm(span=5, adjust=False).mean()
    ema10 = close.ewm(span=10, adjust=False).mean()
    ema20 = close.ewm(span=20, adjust=False).mean()
    ema52 = close.ewm(span=52, adjust=False).mean()

    close_last3 = close[-3:]
    ema5_last3 = ema5[-3:]
    ema10_last3 = ema10[-3:]
    ema20_last3 = ema20[-3:]
    ema52_last3 = ema52[-3:]

    cond_1 = ((ema5_last3 > ema10_last3) & (ema10_last3 > ema20_last3)).all()
    cond_2 = close_last3.iloc[-1] > close_last3.iloc[-2] > close_last3.iloc[-3]

    if len(close) >= 3:
        Close_t = close.iloc[-1]
        Close_t_1 = close.iloc[-2]
        Close_t_2 = close.iloc[-3]
        Open_t = open_.iloc[-1]
        Open_t_1 = open_.iloc[-2]

        alt_A = (
            (Close_t < Open_t_1)
            and (Open_t_1 > Close_t_2)
            and (Open_t > Close_t_1)
            and (Open_t > Open_t_1)
        )
        alt_B = (Close_t > Close_t_1) and (Close_t_1 < Close_t_2) and (Close_t > Close_t_2)
    else:
        alt_A = False
        alt_B = False

    if len(close) >= 6:
        Close_t_3 = close.iloc[-4]
        Close_t_4 = close.iloc[-5]
        Close_t_5 = close.iloc[-6]
        alt_C = (Close_t < Close_t_1 < Close_t_2) and (Close_t_3 > Close_t_4 > Close_t_5)
    else:
        alt_C = False

    cond_2_ext = cond_2 or alt_A or alt_B or alt_C

    avg_vol_10 = vol.iloc[-11:-1].mean()
    cond_3 = vol.iloc[-1] > avg_vol_10

    cond_4 = (close_last3 > ema52_last3).all()

    if cond_1 and cond_2_ext and cond_3 and cond_4:
        return "強勢+站穩+大量"
    elif cond_1 and cond_2_ext and cond_4:
        return "開漲+站穩"
    elif cond_1 and cond_2_ext and cond_3:
        return "開漲+大量"
    elif cond_1 and cond_2_ext:
        return "開漲"
    return None


# =========================================================
# Step 3. 強勢股篩選
# 改成批次下載（一次跟 Yahoo 要 100 檔的資料，而不是一檔一檔單獨查），
# 大幅減少 HTTP 請求數，降低被 Yahoo Finance 流量限制擋掉、漏抓的機率。
# 篩選門檻、classify_stock() 判斷邏輯完全不變；auto_adjust=True 對應原本
# yf.Ticker(code).history() 的預設行為，確保股價數值跟原本一致。
# =========================================================
def scan_strong(symbols: list[str]) -> pd.DataFrame:
    batch_size = 100
    sleep_sec = 2

    result_strong = []
    result_start_stable = []
    result_start_volume = []
    result_start = []
    fail_list = []

    def classify_and_store(code, df_hist):
        cat = classify_stock(df_hist)
        if cat == "強勢+站穩+大量" and code not in result_strong:
            result_strong.append(code)
        elif cat == "開漲+站穩" and code not in result_start_stable:
            result_start_stable.append(code)
        elif cat == "開漲+大量" and code not in result_start_volume:
            result_start_volume.append(code)
        elif cat == "開漲" and code not in result_start:
            result_start.append(code)

    for i in range(0, len(symbols), batch_size):
        batch = symbols[i : i + batch_size]
        print(f"\n🚀 處理第 {i + 1} ~ {i + len(batch)} 檔（共 {len(symbols)}）...")

        try:
            data = yf.download(
                batch,
                period="200d",
                group_by="ticker",
                threads=True,
                progress=False,
                auto_adjust=True,
            )
        except Exception:
            data = pd.DataFrame()

        tmp_fail = []
        for code in tqdm(batch, desc="檢查中"):
            try:
                df_hist = pd.DataFrame()
                if len(batch) == 1:
                    df_hist = data
                elif not data.empty and code in data.columns.levels[0]:
                    df_hist = data[code]

                if df_hist.empty or df_hist["Close"].isnull().all():
                    df_hist = yf.Ticker(code).history(period="200d")  # 批次沒抓到的補抓一次

                classify_and_store(code, df_hist)
            except Exception:
                tmp_fail.append(code)
                continue

        if tmp_fail:
            print(f"⚠️ 批次失敗 {len(tmp_fail)} 檔，進行補抓...")
            for code in tmp_fail:
                try:
                    df_hist = yf.Ticker(code).history(period="200d")
                    classify_and_store(code, df_hist)
                except Exception:
                    fail_list.append(code)
                    continue

        time.sleep(sleep_sec)

    df_out = pd.DataFrame(
        {
            "強勢+站穩+大量": pd.Series(result_strong),
            "開漲+站穩": pd.Series(result_start_stable),
            "開漲+大量": pd.Series(result_start_volume),
            "開漲": pd.Series(result_start),
        }
    )
    print("✅ 強勢股篩選完成。最終失敗數量：", len(fail_list))
    return df_out


# =========================================================
# Step 4. 持續走升篩選
# 同樣改成批次下載。auto_adjust=False 對應原本
# yf.download(symbol, auto_adjust=False) 的設定，股價數值跟原本一致。
# =========================================================
def scan_rising(symbols: list[str]) -> pd.DataFrame:
    all_symbols = list(set(symbols))
    print(f"✅ 共 {len(all_symbols)} 檔符合初步條件")

    final_list = []
    error_count = 0
    batch_size = 100

    for i in tqdm(range(0, len(all_symbols), batch_size), desc="批次檢查持續走升（多頭排列 + 強勢收盤）"):
        batch = all_symbols[i : i + batch_size]

        try:
            data = yf.download(
                batch,
                period="200d",
                group_by="ticker",
                threads=True,
                progress=False,
                auto_adjust=False,
            )
        except Exception:
            data = pd.DataFrame()

        for symbol in batch:
            try:
                df = pd.DataFrame()
                if len(batch) == 1:
                    df = data
                elif not data.empty and symbol in data.columns.levels[0]:
                    df = data[symbol]

                if df.empty or df["Close"].isnull().all():
                    df = yf.download(symbol, period="200d", auto_adjust=False, progress=False)  # 補抓

                if df.empty or len(df) < 60:
                    continue

                close = df["Close"]
                ema5 = close.ewm(span=5).mean()
                ema10 = close.ewm(span=10).mean()
                ema20 = close.ewm(span=20).mean()

                close_last5 = close[-5:]
                ema5_last5 = ema5[-5:]
                ema10_last3 = ema10[-3:]
                ema20_last3 = ema20[-3:]
                ema5_last3 = ema5[-3:]

                cond1 = ((ema5_last3 > ema10_last3) & (ema10_last3 > ema20_last3)).all()
                cond2 = (close_last5 > (ema5_last5 * 1.01)).all()

                if cond1 and cond2:
                    final_list.append(symbol)
            except Exception:
                error_count += 1
                continue

    print(f"✅ 檢查完成，共略過 {error_count} 檔錯誤")
    return pd.DataFrame({"持續走升": final_list})


# =========================================================
# Step 5. 合併去重（強勢優先）
# =========================================================
def merge_dedupe(df_strong: pd.DataFrame, df_rising: pd.DataFrame) -> pd.DataFrame:
    def flatten_symbols(df):
        return [str(x).strip() for x in df.values.ravel() if isinstance(x, str)]

    symbols_strong = flatten_symbols(df_strong)
    symbols_rising = flatten_symbols(df_rising)

    combined_symbols = []
    seen = set()
    for symbol in symbols_strong + symbols_rising:
        if symbol not in seen:
            seen.add(symbol)
            combined_symbols.append(symbol)

    print(f"✅ 合併後總股票數：{len(combined_symbols)}")

    cols = df_strong.columns
    num_cols = len(cols)
    num_rows = (len(combined_symbols) + num_cols - 1) // max(num_cols, 1)
    df_combined = pd.DataFrame(columns=cols)

    for i, symbol in enumerate(combined_symbols):
        col = cols[i % num_cols]
        row = i // num_cols
        if row >= len(df_combined):
            df_combined.loc[row] = [None] * num_cols
        df_combined.at[row, col] = symbol

    return df_combined


# =========================================================
# Step 6. 流動性複篩：嚴格版（近三天每一天都要符合）
# 使用者已確認只需要保留嚴格版，寬鬆版邏輯已移除。
# 這裡候選股票數量通常已經不多（合併去重後大約幾百檔），但一樣改成批次
# 下載，跟前兩個階段的作法一致，避免這一步也因為逐檔查詢被 Yahoo 擋掉。
# =========================================================
def liquidity_strict(df_merged: pd.DataFrame):
    all_codes = df_merged.values.ravel()
    all_codes = [str(code).strip().replace("$", "") for code in all_codes if isinstance(code, str)]

    valid_codes = []
    fail_codes = []
    batch_size = 100

    for i in range(0, len(all_codes), batch_size):
        batch = all_codes[i : i + batch_size]

        try:
            data = yf.download(
                batch,
                period="5d",
                group_by="ticker",
                threads=True,
                progress=False,
                auto_adjust=True,
            )
        except Exception:
            data = pd.DataFrame()

        for code in batch:
            try:
                hist = pd.DataFrame()
                if len(batch) == 1:
                    hist = data
                elif not data.empty and code in data.columns.levels[0]:
                    hist = data[code]

                if hist.empty or hist["Close"].isnull().all():
                    hist = yf.Ticker(code).history(period="5d")  # 補抓

                if hist.empty or len(hist) < 3:
                    fail_codes.append(code)
                    continue
                close = hist["Close"][-3:]
                volume = hist["Volume"][-3:]
                if close.isnull().any() or volume.isnull().any():
                    fail_codes.append(code)
                    continue
                amount = close * volume
                if (volume >= 1_000_000).all() and (amount >= 30_000_000).all():
                    valid_codes.append(code)
                else:
                    fail_codes.append(code)
            except Exception:
                fail_codes.append(code)

    df_filtered = df_merged.map(
        lambda x: x
        if isinstance(x, str) and x.replace("$", "") in valid_codes
        else (x if not isinstance(x, str) else None)
    )

    df_compacted = pd.DataFrame()
    for col in df_filtered.columns:
        compacted = df_filtered[col].dropna().reset_index(drop=True)
        df_compacted[col] = compacted

    max_len = df_compacted.apply(len).max() if len(df_compacted.columns) else 0
    for col in df_compacted.columns:
        df_compacted[col] = df_compacted[col].reindex(range(max_len))

    print(f"✅ 嚴格版流動性複篩完成，合格 {len(valid_codes)} 檔，失敗 {len(fail_codes)} 檔。")
    return df_compacted, pd.DataFrame(fail_codes, columns=["失敗代碼"])


# =========================================================
# 主流程
# =========================================================
def main():
    symbols = get_nasdaq_symbols()
    if not symbols:
        print("⚠️ 沒有股票代碼，程式結束。")
        return

    pd.DataFrame({"Symbol": symbols}).to_excel(
        os.path.join(RESULTS_DIR, "momentum_symbols_raw.xlsx"), index=False
    )

    delete_list = get_delete_list()
    df_symbols = pd.DataFrame({"Symbol": symbols})
    df_symbols["Symbol"] = df_symbols["Symbol"].astype(str).str.upper()
    df_filtered = df_symbols[
        (~df_symbols["Symbol"].isin(delete_list)) & (~df_symbols["Symbol"].str.contains(r"\$", regex=True))
    ]
    df_filtered.to_excel(os.path.join(RESULTS_DIR, "momentum_symbols_filtered.xlsx"), index=False)
    print("✅ 已排除代號，剩餘：", len(df_filtered))

    filtered_symbols = df_filtered["Symbol"].dropna().astype(str).tolist()
    filtered_symbols = [s for s in filtered_symbols if s.isalpha() and len(s) <= 5]

    # Step 3
    df_strong = scan_strong(filtered_symbols)
    save_both(df_strong, "momentum_strong")

    # Step 4
    df_rising = scan_rising(filtered_symbols)
    save_both(df_rising, "momentum_rising")

    # Step 5
    df_merged = merge_dedupe(df_strong, df_rising)
    save_both(df_merged, "momentum_merged")

    # Step 6 嚴格版流動性複篩（唯一保留的最終版本）
    df_strict, df_fail = liquidity_strict(df_merged)
    save_both(df_strict, "momentum")
    save_both(df_fail, "momentum_failcodes")

    print("\n🎉 momentum_scan.py 全部完成！")


if __name__ == "__main__":
    main()
