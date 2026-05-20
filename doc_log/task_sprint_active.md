# 🎯 當前開發衝刺目標: Sprint 2 - 建立 Docker Compose 沙盒部署與 k6 高併發整合壓力測試

## 1. 範疇鎖定與技術邊界 (Scope & Boundaries)

本衝刺旨在透過實體 Docker Compose 容器群組與 Nginx 網關建立真實的微服務沙盒，並利用 k6 注入萬人級別的極限併發混合流量，最終運行對帳腳本驗證系統在真實高併發環境下的防禦限流、防超賣與最終一致性表現。

*   **應該做的事 (In-Scope)**：
    *   **網關層配置**：建立 Nginx 反向代理網關，實作動靜分離、路徑分流（`/` 轉靜態首頁，`/api/v1/` 轉後端）、以及基於單一來源 IP 的漏桶/令牌桶限流（限制 2r/s，超出限額則丟失或於邊界直接返回 HTTP 403 / 503）。
    *   **容器化編排**：撰寫 `Dockerfile.app`（包裝 FastAPI）與 `Dockerfile.worker`（包裝背景消費 Worker）。撰寫 `docker-compose.yml` 串接 `nginx`、`app_server`、`redis`、`db_mysql` 與 `background_worker` 五大組件。
    *   **資料庫初始化自動化**：配置 MySQL 容器自動執行 `database/schema.sql` 完成資料庫結構初始化。
    *   **高併發 k6 腳本撰寫**：撰寫 k6 壓力測試腳本，模擬萬人搶票與混合流量比例（80% 合法購票、10% 401 身份驗證失敗、10% 403/503 限流超頻請求）。
    *   **對帳審計腳本**：編寫獨立的 Python 對帳腳本，比對 MySQL `orders` 成功筆數與 Redis 中的中獎名單 Hash 數量，若有任何不一致，必須拋出 AssertionError 報錯。
    *   **沙盒自動化腳本**：撰寫一個整合啟動與測試的 PowerShell 腳本（`run_sandbox_test.ps1`），其流程為：清理舊容器 $\rightarrow$ `docker-compose up --build` 啟動 $\rightarrow$ 等待 MySQL 與 Redis 就緒 $\rightarrow$ 預載 Redis 商品庫存 $\rightarrow$ 啟動 k6 壓測 $\rightarrow$ 壓測後運行對帳 $\rightarrow$ 關閉容器，並將全量執行輸出（Stdout & Stderr）重新導向至 `log/sandbox_runtime.log`。

*   **不該做的事 (Out-of-Scope)**：
    *   **不更動 Python 核心業務代碼**：除因應容器連線 Hostname 調整（改用環境變數 `DB_HOST`、`REDIS_HOST` 等）外，嚴禁隨意重構 `services.py` 的業務邏輯。
    *   **不配置 Kubernetes / K8s**：本階段僅使用單機 Docker Compose 以降低環境配置成本。
    *   **不引入實體雲端 CDN**：所有邊界防禦與分流由 Nginx 容器本地模擬。

---

## 2. 影響組件與職責規劃 (Impacted Components & Responsibilities)

*   **Staging 配置目錄 (`src_staging/`)**：
    *   `src_staging/gateway/nginx.conf`：配置 Nginx 轉發、限流閥值與靜態網頁 Offloading。
    *   `src_staging/gateway/index.html`：精簡的前端靜態搶票網頁，包含按鈕與基本異步 Fetch 輪詢邏輯。
    *   `src_staging/Dockerfile.app`：FastAPI 容器包裝檔。
    *   `src_staging/Dockerfile.worker`：背景消費 Worker 容器包裝檔。
    *   `src_staging/docker-compose.yml`：定義五大容器服務、端口映射、掛載路徑與環境變數注入。
    *   `src_staging/tests/k6_load_test.js`：k6 萬人混合壓測腳本。
    *   `src_staging/tests/reconcile.py`：實體連線 Redis 與 MySQL 的對帳腳本。
    *   `src_staging/run_sandbox_test.ps1`：沙盒整合測試自動化驅動腳本。
*   **日誌路徑**：
    *   `project_root/log/sandbox_runtime.log`：收集沙盒從啟動、壓測、對帳到清理的完整日誌，供 `LOG_ANALYZER_RECOVERY` 進行動態除錯。

---

## 3. 分步開發工單 (Action Items for Implementer)

### 第一階段：微服務容器化與網關配置 (Dockerization & Nginx Gateway)
1.  **Nginx 網關限流與靜態託管**
    *   建立 `src_staging/gateway/nginx.conf`：
        *   配置 `limit_req_zone $binary_remote_addr zone=api_limit:10m rate=2r/s;` 宣告限流區。
        *   靜態網頁（`/`）由 Nginx 本地直接讀取 `index.html` 並回傳，不向後端轉發。
        *   動態請求（`/api/v1/`）轉發至 FastAPI `app_server` 容器（例如 `http://app_server:8000`），並對 `/api/v1/tickets/*/reserve` 套用 `limit_req zone=api_limit burst=5 nodelay;`。限流超限時，回傳 `503` 或 `403`。
    *   建立 `src_staging/gateway/index.html`：包含基本的搶票按鈕、輸入 Token 的欄位、按下按鈕後向 `/api/v1/tickets/concert_a/reserve` 發送請求，並定期輪詢 `/api/v1/orders/concert_a/{member_id}` 更新 UI 顯示「排隊中」、「購買成功」或「售罄」。
2.  **Dockerfile 與 Docker Compose 編排**
    *   建立 `src_staging/Dockerfile.app`：使用輕量級 `python:3.11-slim`，複製 `src/app/` (因 staging 通過後會同步至 src，容器以 src 作為代碼來源)，安裝 FastAPI/Uvicorn。
    *   建立 `src_staging/Dockerfile.worker`：包裝背景 Worker，運行 `src/app/worker.py`。
    *   建立 `src_staging/docker-compose.yml`：
        *   `db_mysql`：使用 `mysql:8.0`，掛載本地 `database/schema.sql` 到 `/docker-entrypoint-initdb.d/` 實現啟動即建表。
        *   `redis`：使用 `redis:7.0-alpine`，開放預設端口。
        *   `app_server`：注入環境變數 `REDIS_HOST=redis`、`DB_HOST=db_mysql`，依賴於 redis 與 db_mysql，並映射埠口 `8000:8000`。
        *   `background_worker`：注入環境變數 `REDIS_HOST=redis`、`DB_HOST=db_mysql`。
        *   `nginx`：掛載 `gateway/nginx.conf` 與 `gateway/index.html`，映射埠口 `80:80`，依賴於 app_server。

### 第二階段：連線環境變數調整 (Configuration Refactoring)
3.  **核心連線配置調整**
    *   調整 `src_staging/app/main.py` 與 `src_staging/app/worker.py` 中資料庫與 Redis 的連線配置，使其能讀取環境變數 `DB_HOST` (預設為 `localhost`)、`REDIS_HOST` (預設為 `localhost`)。確保既能在本地單機執行單元測試，也能在 Docker 容器網路中流暢運作。

### 第三階段：壓測與對帳腳本編寫 (k6 & Reconciliation)
4.  **k6 高併發混合流量壓測指令碼**
    *   建立 `src_staging/tests/k6_load_test.js`：
        *   設置壓測階段 (stages) 達到 10,000 VUs 併發。
        *   模擬三類流量分配：
            *   **80% 合法搶票**：向 `/api/v1/tickets/concert_a/reserve` 發送 POST 請求，帶有正確拼接的 token（如 `token_{VU_ID}`）與 `member_id = VU_ID`。
            *   **10% 401 拒絕**：發送無效 token 的請求，預期回傳 401。
            *   **10% 頻率超頻**：同一 VU 快速連續發送兩次請求，觸發 Nginx 限流區，預期回傳 503/403。
5.  **對帳驗證 CLI**
    *   建立 `src_staging/tests/reconcile.py`：
        *   以實體連線 `aiomysql` 與 `redis`，查詢 MySQL 中 `orders` 表的總列數。
        *   查詢 Redis 中雜湊表 `ticket:success:orders` 的欄位數量。
        *   比對兩者是否相等。如不相等，拋出 `AssertionError("MySQL Count X does not match Redis Count Y")`。

### 第四階段：沙盒自動化驅動器 (Sandbox Orchestrator)
6.  **自動化測試執行腳本**
    *   建立 `src_staging/run_sandbox_test.ps1`：
        *   執行 `docker-compose down -v` 清理殘留資料卷。
        *   執行 `docker-compose up --build -d` 在背景啟動所有服務。
        *   循環等待 MySQL（port 3306）與 Redis（port 6379）可連線就緒。
        *   **預載初始化資料**：使用 Python 腳本向 Redis 寫入初始商品庫存（例如 `SET ticket:stock:concert_a 2000`）。
        *   執行壓測命令：`k6 run src_staging/tests/k6_load_test.js`。
        *   執行對帳命令：`python src_staging/tests/reconcile.py`。
        *   測試完成後，執行 `docker-compose down -v` 清除容器。
        *   將整個腳本的 Stdout 與 Stderr 全數導向寫入 `project_root/log/sandbox_runtime.log`。
