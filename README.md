# 台美總經儀表板

用 Python 抓台美總經與市場資料，產生一頁靜態網頁，放在 GitHub Pages 上。
GitHub Actions 每週一到週五台北時間約 07:30 與 21:35 自動重跑一次。

## 檔案

| 檔案 | 用途 |
|---|---|
| `build.py` | 主程式：抓資料、產生 `docs/index.html` |
| `data/manual.json` | 手動維護的資料：台灣總經數據、財經行事曆 |
| `data/cache.json` | 上次成功抓到的資料（程式自動寫入，不用手改） |
| `docs/index.html` | 產生出來的網頁（GitHub Pages 顯示這個檔案） |
| `.github/workflows/update.yml` | 自動排程設定 |
| `workflow-update.yml` | 上面那個檔案的備份，方便複製貼上 |
| `requirements.txt` | 需要的 Python 套件 |

## 上線步驟（約 15 分鐘，全部在瀏覽器完成）

### 1. 註冊 GitHub
到 https://github.com 按 **Sign up**，用 email 註冊免費帳號。

### 2. 建立儲存庫
1. 登入後按右上角 **+** → **New repository**
2. Repository name 填 `macro-dashboard`
3. 選 **Public**（免費版的 GitHub Pages 需要公開）
4. 按 **Create repository**

### 3. 上傳檔案
1. 在新儲存庫頁面按 **uploading an existing file**
2. 把解壓縮後資料夾裡的這些東西一起拖進去：
   `build.py`、`requirements.txt`、`README.md`、`workflow-update.yml`、`data` 資料夾、`docs` 資料夾
3. 按 **Commit changes**

### 4. 建立排程檔
`.github` 是隱藏資料夾，拖曳上傳常常會漏掉，所以用貼上的方式建立：
1. 按 **Add file** → **Create new file**
2. 檔名那一格輸入：`.github/workflows/update.yml`（打斜線時會自動變成資料夾）
3. 打開 `workflow-update.yml`，全部複製貼到內容區
4. 按 **Commit changes**

### 5. 開啟 GitHub Pages
1. 進 **Settings** → 左側 **Pages**
2. Source 選 **Deploy from a branch**
3. Branch 選 **main**，資料夾選 **/docs**，按 **Save**
4. 等一兩分鐘，同一頁上方會出現網址：`https://你的帳號.github.io/macro-dashboard/`

### 6. 手動跑第一次
1. 進 **Actions** 分頁（如果看到提示，按 **I understand my workflows, go ahead and enable them**）
2. 左側點 **更新儀表板** → 右邊 **Run workflow** → **Run workflow**
3. 約 1 到 2 分鐘後出現綠色勾勾，重新整理你的網址就會看到最新資料

之後就會照排程自動更新，不用再管。

## 資料從哪裡來

| 區塊 | 來源 | 更新方式 |
|---|---|---|
| 大盤指數、匯率、原物料、美股類股 | Yahoo Finance（`yfinance` 套件） | 自動 |
| 美國 CPI、非農、失業率、Fed 利率、美債殖利率 | FRED 公開 CSV | 自動 |
| 台股類股漲跌、三大法人 | 臺灣證券交易所 | 自動 |
| 外資台指期淨空單 | 臺灣期貨交易所 | 自動，每天累加一筆 |
| 台灣 CPI、GDP、出口、PMI、景氣燈號、重貼現率 | `data/manual.json` | **手動** |
| 財經行事曆 | `data/manual.json` | **手動**，過期的會自動隱藏 |

### 手動更新台灣數據或行事曆
在 GitHub 上點開 `data/manual.json` → 按鉛筆圖示編輯 → 改數字 → **Commit changes**。
下次排程（或手動 Run workflow）就會顯示新內容。

## 已知限制

- **GitHub 排程不準時**：尖峰時段可能晚 5 到 30 分鐘，所以早上設在 07:30。
- **FRED 有時差**：美國數據公布後，FRED 通常幾小時內更新，21:35 那次不一定抓得到當晚 21:30 剛公布的數字，隔天早上那次會補上。
- **美國 2025 年 10 月 CPI 缺值**（政府關門沒公布），所以 2026 年 10 月的年增率程式算不出來。
  可以在 `manual.json` 的 `us_cpi_override` 手動補，例如 `[["2026-10", 3.5]]`。
- **某個來源抓不到時**，該區塊會沿用上次資料，頁面最下方會列出沒更新到的項目。
- **儲存庫 60 天沒有任何變動**，GitHub 會暫停排程；這個專案每次更新都會存檔，正常不會遇到。

## 在自己電腦上跑（選用）

```bash
pip install -r requirements.txt
python build.py            # 抓資料並產生 docs/index.html
python build.py --offline  # 不連網，只重新產生網頁（改版面時用）
```

想改版面：`build.py` 最下面的 `TEMPLATE` 是 HTML 與 CSS；想加減追蹤的商品：改最上面的 `QUOTES` 清單。

本專案僅供學習參考，不構成投資建議。
