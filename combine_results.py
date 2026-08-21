"""
把 MACD scan 跟 Momentum scan（嚴格版）的今日結果，合併存成同一個 Excel 檔。
------------------------------------------------
在 GitHub Actions 裡，這支程式會在 macd-scan 跟 momentum-scan 兩個 job
都執行完成、且都把各自的結果 push 回 repo 之後才執行（workflow 裡用
`needs: [macd-scan, momentum-scan]` 保證順序）。

讀取：
  results/macd_latest.xlsx      <- scan_stocks.py 的今日結果
  results/momentum_latest.xlsx  <- momentum_scan.py 的今日結果（嚴格版）

輸出：
  results/latest.xlsx        <- 固定路徑，每天覆蓋，裡面有兩個工作表
  results/YYYY-MM-DD.xlsx    <- 當天日期存檔，同樣兩個工作表
"""

import os
from datetime import datetime, timezone, timedelta

import pandas as pd

RESULTS_DIR = "results"
os.makedirs(RESULTS_DIR, exist_ok=True)

TW_TZ = timezone(timedelta(hours=8))
TODAY_STR = datetime.now(TW_TZ).strftime("%Y-%m-%d")

MACD_SRC = os.path.join(RESULTS_DIR, "macd_latest.xlsx")
MOMENTUM_SRC = os.path.join(RESULTS_DIR, "momentum_latest.xlsx")


def load_or_empty(path: str, label: str) -> pd.DataFrame:
    if not os.path.exists(path):
        print(f"⚠️ 找不到 {path}，{label} 這個分頁會是空的。")
        return pd.DataFrame()
    try:
        df = pd.read_excel(path)
        print(f"✅ 已讀取 {path}（{label}），共 {len(df)} 列。")
        return df
    except Exception as e:
        print(f"⚠️ 讀取 {path} 失敗 ({e})，{label} 這個分頁會是空的。")
        return pd.DataFrame()


def main():
    df_macd = load_or_empty(MACD_SRC, "MACD scan")
    df_momentum = load_or_empty(MOMENTUM_SRC, "Momentum scan（嚴格版）")

    latest_path = os.path.join(RESULTS_DIR, "latest.xlsx")
    dated_path = os.path.join(RESULTS_DIR, f"{TODAY_STR}.xlsx")

    for path in (latest_path, dated_path):
        with pd.ExcelWriter(path, engine="openpyxl") as writer:
            df_macd.to_excel(writer, sheet_name="MACD", index=False)
            df_momentum.to_excel(writer, sheet_name="Momentum_嚴格版", index=False)
        print(f"💾 已輸出：{path}")

    print("\n🎉 combine_results.py 完成！")


if __name__ == "__main__":
    main()
