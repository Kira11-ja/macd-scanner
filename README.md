# 美股每日自動掃描（MACD 版 + 動能版，合併輸出）

這個 repo 透過 GitHub Actions，每天台灣時間晚上 8:00 自動執行三個 job：

1. `macd-scan`：跑 `scan_stocks.py`（MACD 多週期策略掃描）
2. `momentum-scan`：跑 `momentum_scan.py`（均線多頭排列 + 型態判斷的動能選股，只保留**嚴格版**流動性複篩）
3. `combine-results`：等前兩個都跑完後，把兩邊的今日結果合併存成**同一個 Excel 檔**（兩個工作表分頁）

兩支掃描程式共用同一份 Google 試算表排除名單（`SHEET_ID` / `SHEET_NAME`）。

## 設定步驟

### 1. 建立 / 更新 GitHub repo

把這個資料夾裡的所有檔案上傳到你的 repo：

- `scan_stocks.py`
- `momentum_scan.py`
- `combine_results.py`（新增）
- `requirements.txt`
- `.github/workflows/daily-scan.yml`（**這次有更新，變成三個 job，記得整份覆蓋掉舊版**）
- 本 README

上傳方式：

- 根目錄檔案用 **Add file → Upload files** 拖上去即可（檔名相同會直接覆蓋更新，不會變成重複檔案）
- `.github/workflows/daily-scan.yml` 直接點進該檔案 → 右上角鉛筆圖示編輯 → 全選刪除 → 貼上新內容 → Commit

或用 git 指令一次處理：

```bash
git add .
git commit -m "combine macd + momentum results into one excel"
git push
```

### 2. 設定 Google 試算表分享權限

打開你的排除名單試算表 → 右上角「共用」→ 一般存取權改成 **「知道連結的使用者」可查看**。

### 3. 設定 GitHub Secrets（隱藏你的試算表 ID）

進入 repo → **Settings → Secrets and variables → Actions**，確認已經有：

- `SHEET_ID`：你的試算表 ID（只填 ID 那段，不要整段網址）
- `SHEET_NAME`：實際分頁名稱（**建議一定要設定**，就算是 `Sheet1` 也手動加上去）

### 4. 測試執行

1. 進入 repo → **Actions** 分頁 → 左側選 **Daily Stock Scans**
2. 點 **Run workflow** 手動觸發一次
3. 會看到三個 job：`macd-scan`（約 30 分鐘）、`momentum-scan`（**耗時較長**，逐檔查詢沒有批次下載）、`combine-results`（**要等前兩個都跑完才會開始**，跑完通常幾十秒內完成）
4. 全部完成後，回 repo 首頁的 `results/` 資料夾看 `latest.xlsx`

### 5. 之後

- 排程每天台灣時間 20:00 自動執行一次
- 在 Google 試算表增減股票代號，隔天會自動套用最新排除名單
- 想改執行時間，改 `.github/workflows/daily-scan.yml` 裡的 `cron`（UTC 時間，台灣時間 = UTC+8）

## 輸出檔案說明

### 你平常只需要看這個

- **`results/latest.xlsx`** ← 今天的合併結果，一個 Excel 檔裡有兩個工作表分頁：
  - `MACD` 分頁：MACD scan 的結果
  - `Momentum_嚴格版` 分頁：動能選股（嚴格版流動性複篩）的結果
- **`results/YYYY-MM-DD.xlsx`** ← 同上，但是當天日期的歷史存檔版本

### 中間過程檔案（除錯用，平常不用看）

- `results/macd_latest.xlsx` / `macd_YYYY-MM-DD.xlsx`：MACD scan 自己的原始輸出（`combine_results.py` 讀這個來組合）
- `results/symbols_raw.xlsx`：MACD scan 抓到的原始 NASDAQ 清單
- `results/momentum_latest.xlsx` / `momentum_YYYY-MM-DD.xlsx`：Momentum scan 自己的原始輸出（嚴格版，`combine_results.py` 讀這個來組合）
- `results/momentum_failcodes_latest.xlsx` / `_YYYY-MM-DD.xlsx`：嚴格版篩選時「沒通過」的代號清單
- `results/momentum_symbols_raw.xlsx`、`momentum_symbols_filtered.xlsx`：動能選股抓清單、排除黑名單後的中間結果
- `results/momentum_strong_latest.xlsx`、`momentum_rising_latest.xlsx`、`momentum_merged_latest.xlsx`：動能選股各階段的中間結果（流動性複篩之前）

## 注意事項

- `momentum_scan.py` 只保留**嚴格版**流動性複篩（近三天每一天都要符合量能條件），寬鬆版已經拿掉。
- `momentum_scan.py` 的篩選階段是逐檔呼叫 yfinance（沒有改成批次下載，維持原本的寫法），實際執行時間可能明顯比 MACD 版長，也比較容易遇到 Yahoo Finance 的流量限制而讓少數股票查詢失敗——這是正常現象，程式本身有錯誤跳過機制，不會讓整個流程中斷。
- `combine-results` 這個 job 用 `needs: [macd-scan, momentum-scan]` 設定，保證一定要等前兩個都成功推送結果之後才會開始，不會讀到跑一半的舊資料。
