# SI 環境異動紀錄檔 (SI Environment Change Logs)

> **維護者**：`SD_SI_PROJECT_ASSISTANT`  
> **紀錄規範**：每次 WSL2 資源調整、Docker 掛載路徑異動或核心 Runtime 版本更換時，追加於此。  
> **必填欄位**：變更時間、實體環境異動、資源限額變更、對 Docker 沙盒 Runtime 的影響評估。

---

## [2026-05-19] Sprint 2 Docker Compose 沙盒環境建立 — 初始化基線紀錄

### 1. 異動概述
Sprint 2 首次在實體環境中建立 Docker Compose 多容器沙盒，以進行 k6 高併發整合壓力測試。此為本專案 SI 環境的初始化基線（Baseline）快照。

### 2. 實體宿主機環境（Host Machine）

| 環境項目 | 規格 |
| :--- | :--- |
| **作業系統** | Windows 11 |
| **專案根目錄** | `G:\git_projects\f_b_high_concurrency_veification\` |
| **虛擬化層** | WSL2（Windows Subsystem for Linux 2）|
| **容器引擎** | Docker Desktop（透過 WSL2 後端運行）|

### 3. WSL2 資源限額基線

| 資源項目 | 配置值 | 備註 |
| :--- | :--- | :--- |
| **記憶體（Memory）** | 預設（未明確限制） | 由 Docker Desktop 動態調配 |
| **CPU 核心數** | 預設（未明確限制） | 由宿主機動態提供 |
| **Swap** | 預設 | 未另行調整 |

> [!NOTE]
> 本 Sprint 尚未透過 `%USERPROFILE%\.wslconfig` 進行 WSL2 資源顯式限制。若後續壓測出現宿主機記憶體競爭問題，應補充明確的 `memory` 與 `processors` 限制設定，並在本紀錄中追加異動。

### 4. Docker Compose 容器拓撲定案

| 容器服務名稱 | 基礎映像 | 對外映射埠口 | 職責 |
| :--- | :--- | :--- | :--- |
| `db_mysql` | `mysql:8.0` | `3306:3306` | 實體關聯式資料庫，持久化訂單紀錄 |
| `redis` | `redis:7.0-alpine` | `6379:6379` | 消息佇列與 Lua 快取阻擊層 |
| `app_server` | `python:3.11-slim`（自建）| `8000:8000` | FastAPI ASGI 應用伺服器 |
| `background_worker` | `python:3.11-slim`（自建）| — | 非同步佇列消費者，負責落庫 |
| `nginx` | `nginx:latest` | `80:80` | 反向代理網關，動靜分離與限流 |

### 5. 關鍵掛載路徑（Volume Mounts）

| 容器服務 | 宿主機路徑（Windows 相對路徑） | 容器內路徑 | 用途 |
| :--- | :--- | :--- | :--- |
| `db_mysql` | `./database/schema.sql` | `/docker-entrypoint-initdb.d/schema.sql` | 啟動時自動建立資料庫 Schema |
| `nginx` | `./src_staging/gateway/nginx.conf` | `/etc/nginx/conf.d/default.conf` | Nginx 反向代理與限流配置 |
| `nginx` | `./src_staging/gateway/index.html` | `/usr/share/nginx/html/index.html` | Nginx 靜態資源 Offloading |

### 6. 環境變數注入規格

| 容器服務 | 環境變數 | 注入值 | 說明 |
| :--- | :--- | :--- | :--- |
| `app_server` | `REDIS_HOST` | `redis` | Docker 內部網路 Service Name |
| `app_server` | `DB_HOST` | `db_mysql` | Docker 內部網路 Service Name |
| `background_worker` | `REDIS_HOST` | `redis` | Docker 內部網路 Service Name |
| `background_worker` | `DB_HOST` | `db_mysql` | Docker 內部網路 Service Name |

> [!IMPORTANT]
> 所有應用層代碼讀取連線設定時，**必須**以環境變數為優先（`os.getenv("DB_HOST", "localhost")`），確保代碼能同時在「本地單機直執行（localhost）」與「Docker 容器網路（service-name）」兩種環境下無縫運作。

### 7. 啟動協議（Sequenced Bootstrapping）— 定案版本

依 ADR-005 定案，採用分步引導啟動協議（見 `src_staging/run_sandbox_test.ps1`）：

1. **Phase 1**：啟動基礎設施層 → `docker-compose up -d db_mysql redis`
2. **Phase 2**：等待就緒 → 輪詢 `docker inspect` 直至 `db_mysql` 健康狀態變為 `"healthy"`
3. **Phase 3**：啟動應用層 → `docker-compose up --build -d app_server background_worker nginx`
4. **Phase 4**：預載初始資料 → Python 腳本向 Redis 寫入初始庫存（`SET ticket:stock:concert_a <N>`）
5. **Phase 5**：執行壓測 → `k6 run src_staging/tests/k6_load_test.js`
6. **Phase 6**：執行對帳 → `python src_staging/tests/reconcile.py`
7. **Phase 7**：清理環境 → `docker-compose down -v`

### 8. 對 Docker 沙盒 Runtime 的影響評估

| 評估項目 | 結論 |
| :--- | :--- |
| **網路隔離** | ✅ 所有容器在 Docker Compose 預設橋接網路中運行，彼此隔離於宿主機環境 |
| **資料持久性** | ⚠️ `docker-compose down -v` 執行後，MySQL 資料卷將被清除，此為設計行為（每次壓測後重置）|
| **資源競爭風險** | ⚠️ k6 以 10,000 VUs 執行時，宿主機 CPU 與記憶體壓力較高。若出現 OOM，需評估調整 WSL2 資源限額 |
| **WSL2 路徑相容性** | ✅ 所有掛載路徑已採用相對路徑，Docker Desktop 自動處理 Windows/WSL2 路徑轉換 |

---

## [2026-05-19] Sprint 2 整合測試崩潰修復 — 環境層異動

### 1. 異動概述
`INTEGRATION_TESTER` 執行沙盒整合測試後，發現兩個環境層問題並進行修復。詳細問題診斷見 `doc_log/agent_change_logs.md` 與 ADR-005。

### 2. 環境層變更明細

| 變更項目 | 變更前 | 變更後 | 關聯 ADR |
| :--- | :--- | :--- | :--- |
| `Dockerfile.worker` 啟動命令 | `CMD ["python", "src/app/worker.py"]` | `CMD ["python", "-m", "src.app.worker"]` | ADR-005 |
| `run_sandbox_test.ps1` 啟動策略 | 一次性 `docker-compose up --build` | 分步引導啟動（Sequenced Bootstrapping）| ADR-005 |
| `main.py` / `worker.py` 連線初始化 | 無重試機制 | 加入 5 次重試、2 秒間隔的防禦性重試 | ADR-005 |

### 3. 對 Docker 沙盒 Runtime 的影響評估

| 評估項目 | 結論 |
| :--- | :--- |
| **功能正確性** | ✅ 修復後所有容器正常啟動，ImportError 與 Connection Refused 問題完全消除 |
| **資料一致性驗證** | ✅ `[RECONCILE_SUCCESS]` — MySQL 39 筆 == Redis Hash 39 筆，超賣率 0.00% |
| **啟動時間影響** | ⚠️ 分步啟動額外增加約 10~30 秒（等待 MySQL 健康檢查），可接受 |
| **WSL2 環境穩定性** | ✅ 無需調整 WSL2 資源限額，現有配置已足夠支撐本次壓測規模 |
