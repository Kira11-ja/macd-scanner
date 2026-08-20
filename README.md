# 美股每日自動掃描（MACD 版 + 動能版）

這個 repo 透過 GitHub Actions，每天台灣時間晚上 8:00 自動平行執行兩支程式：

- `scan_stocks.py`：MACD 多週期策略掃描
- `momentum_scan.py`：均線多頭排列 + 型態判斷的動能選股

兩支程式共用同一份 Google 試算表排除名單（`SHEET_ID` / `SHEET_NAME`），
結果都存到 `results/` 資料夾裡。

## 設定步驟

### 1. 建立 / 更新 GitHub repo

把這個資料夾裡的所有檔案上傳到你的 repo：

- `scan_stocks.py`
- `momentum_scan.py`
- `requirements.txt`
- `.github/workflows/daily-scan.yml`（**這次有更新，內容從一個 job 變成兩個 job，記得覆蓋掉舊版**）
- 本 README

上傳方式：

- 根目錄檔案（`scan_stocks.py`、`momentum_scan.py`、`requirements.txt`、`README.md`）用 **Add file → Upload files** 拖上去即可
- `.github/workflows/daily-scan.yml` 如果已經存在，直接點進該檔案 → 右上角鉛筆圖示編輯 → 全選刪除 → 貼上新內容 → Commit；如果還沒有，用「Add file → Create new file」，檔名欄位打完整路徑 `.github/workflows/daily-scan.yml`

或用 git 指令一次處理：

```bash
git add .
git commit -m "add momentum scan"
git push
```

### 2. 設定 Google 試算表分享權限

打開你的排除名單試算表 → 右上角「共用」→ 一般存取權改成 **「知道連結的使用者」可查看**。

### 3. 設定 GitHub Secrets（隱藏你的試算表 ID）

進入 repo → **Settings → Secrets and variables → Actions**，確認已經有：

- `SHEET_ID`：你的試算表 ID
- `SHEET_NAME`：實際分頁名稱（**建議一定要設定**，就算是 `Sheet1` 也手動加上去，避免空值造成讀取失敗）

### 4. 測試執行

1. 進入 repo → **Actions** 分頁 → 左側選 **Daily Stock Scans**
2. 點 **Run workflow** 手動觸發一次
3. 這次會看到兩個平行執行的 job：`macd-scan`（約 30 分鐘）和 `momentum-scan`（**耗時較長，可能 1~2 小時以上**，因為是逐檔查詢、沒有做批次下載）
4. 兩個 job 都完成後，回 repo 首頁看 `results/` 資料夾

### 5. 之後

- 排程每天台灣時間 20:00 自動執行一次，兩支程式平行跑
- 在 Google 試算表增減股票代號，隔天會自動套用最新排除名單
- 想改執行時間，改 `.github/workflows/daily-scan.yml` 裡的 `cron`（UTC 時間，台灣時間 = UTC+8）

## 輸出檔案說明

### MACD 版（`scan_stocks.py`）

- `results/latest.xlsx`：最新結果（每天覆蓋）
- `results/YYYY-MM-DD.xlsx`：歷史存檔
- `results/symbols_raw.xlsx`：當次抓到的原始 NASDAQ 清單

### 動能版（`momentum_scan.py`）

- `results/momentum_symbols_raw.xlsx`：原始 NASDAQ 清單
- `results/momentum_symbols_filtered.xlsx`：排除黑名單後的清單
- `results/momentum_strong_latest.xlsx` / `_YYYY-MM-DD.xlsx`：強勢股篩選（強勢+站穩+大量 / 開漲+站穩 / 開漲+大量 / 開漲）
- `results/momentum_rising_latest.xlsx` / `_YYYY-MM-DD.xlsx`：持續走升篩選
- `results/momentum_merged_latest.xlsx` / `_YYYY-MM-DD.xlsx`：合併去重（強勢優先）
- `results/momentum_final_loose_latest.xlsx` / `_YYYY-MM-DD.xlsx`：流動性複篩 **寬鬆版**（近三天任一天符合量能條件即可）
- `results/momentum_final_strict_latest.xlsx` / `_YYYY-MM-DD.xlsx`：流動性複篩 **嚴格版**（近三天每一天都要符合）
- `results/momentum_final_strict_failcodes_latest.xlsx` / `_YYYY-MM-DD.xlsx`：嚴格版的失敗代碼清單

## 注意事項

- `momentum_scan.py` 的兩個篩選階段是逐檔呼叫 yfinance（沒有改成批次下載，維持原本的寫法），實際執行時間可能明顯比 MACD 版長，也比較容易遇到 Yahoo Finance 的流量限制而讓少數股票查詢失敗——這是正常現象，程式本身有錯誤跳過機制，不會讓整個流程中斷。
- 兩個 job 是平行執行、各自把結果推回同一個 repo，`daily-scan.yml` 裡已經加了推送失敗自動重試的機制，避免兩邊同時 push 互相衝突。
