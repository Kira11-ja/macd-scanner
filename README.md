# 美股 MACD 每日自動掃描

這個 repo 會透過 GitHub Actions，每天台灣時間晚上 8:00 自動執行 `scan_stocks.py`，
把掃描結果存到 `results/latest.xlsx`（固定路徑，每天覆蓋）與 `results/YYYY-MM-DD.xlsx`（歷史存檔）。

## 設定步驟

### 1. 建立 GitHub repo

1. 到 https://github.com/new 建立一個新的 **公開 (Public)** repo，例如叫 `macd-scanner`
2. 把這個資料夾裡的所有檔案（`scan_stocks.py`、`requirements.txt`、`.github/workflows/daily-scan.yml`、本 README）上傳上去
   - 最簡單的方式：在 repo 頁面點 **Add file → Upload files**，把檔案拖進去，注意要保留 `.github/workflows/daily-scan.yml` 這個資料夾結構
   - 或用 git 指令：
     ```bash
     git init
     git add .
     git commit -m "init macd scanner"
     git branch -M main
     git remote add origin https://github.com/<你的帳號>/macd-scanner.git
     git push -u origin main
     ```

### 2. 設定 Google 試算表分享權限

打開你的排除名單試算表 → 右上角「共用」→ 一般存取權改成 **「知道連結的使用者」可查看**。
（這一步是必要的，不然 GitHub Actions 的機器人抓不到資料）

### 3. 設定 GitHub Secrets（隱藏你的試算表 ID）

1. 進入 repo → **Settings → Secrets and variables → Actions**
2. 點 **New repository secret**，新增：
   - Name: `SHEET_ID`　Value: 你的試算表 ID（網址 `.../d/這一段/edit` 中間那段）
   - 如果你的分頁名稱不是 `Sheet1`，再新增一個 Name: `SHEET_NAME`　Value: 實際分頁名稱

### 4. 確認排程已啟用

1. 進入 repo → **Actions** 分頁
2. 如果看到提示要啟用 workflow，點擊啟用
3. 可以先手動點 **Daily MACD Stock Scan → Run workflow** 測試跑一次，確認大約 30 分鐘後 `results/latest.xlsx` 有更新

### 5. 之後

- 排程會每天台灣時間 20:00 自動執行一次
- 你只要在 Google 試算表增減股票代號，隔天就會自動套用最新排除名單，不用碰程式碼
- 如果想改執行時間，改 `.github/workflows/daily-scan.yml` 裡的 `cron` 那一行（UTC 時間，台灣時間 = UTC+8）

## 檔案說明

- `scan_stocks.py`：主程式，合併了原本 Colab 三段流程（抓清單 → 排除 → MACD 分類 → 流動性篩選）
- `requirements.txt`：Python 套件清單
- `.github/workflows/daily-scan.yml`：GitHub Actions 排程設定
- `results/latest.xlsx`：每次執行覆蓋的最新結果
- `results/YYYY-MM-DD.xlsx`：每日歷史存檔
