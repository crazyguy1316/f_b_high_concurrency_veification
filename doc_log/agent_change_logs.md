# Agent 異動紀錄檔 (Agent Change Logs)

## [2026-05-19] 引入 INTEGRATION_TESTER 與確立 Waterfall Flow 協作機制

### 1. 異動概述
為了優化搶票驗證系統的開發與驗證管道，避免測試範疇發散並縮小除錯範圍（Blast Radius），我們在此次變更中新增了 `INTEGRATION_TESTER` 專任 Agent，並將整體協作模式調整為瀑布式流程（Waterfall Flow）。

### 2. 決斷原因 (Decision Rationale)
*   **單一職責與關注點分離**：
    原先的 `REVIEWER_REFACTOR` 職責過於臃腫，兼顧了代碼語法審查、OOP 原則確認、以及隱式的測試驗證。但在高併發系統中，「代碼靜態品質」與「實體環境併發表現」是截然不同的維度。引入專門負責實體 Docker 環境與 k6 的 Agent，可讓審查與測試職責各歸其位。
*   **縮減除錯範圍**：
    在 Waterfall Flow 下，每個 Agent 各自獨立運作並在產出交付物後停機。如果單元測試或靜態語法不合格，程式碼將在 Staging 階段被阻斷，根本不會進入 Docker 部署與壓測階段，進而確保在高併發測試失敗時，能將問題鎖定在運行期併發衝突上，而非基礎語法錯誤。
*   **促成無人值守 Healing 閉環**：
    壓測產生的真實日誌輸出到 `sandbox_runtime.log` 後，能為 `LOG_ANALYZER_RECOVERY` 提供標準化的錯誤輸入源，從而精準驅動 `GENERAL_OOP_IMPLEMENTER` 重構代碼，使整個驗證流程具備自動化自我修復能力。

### 3. Agent 角色定義與關係異動

| Agent ID | 變更狀態 | 調整後職責 / 輸入輸出關係 |
| :--- | :--- | :--- |
| **`ARCHITECT_DISPATCHER`** | 保持不變 | 專注於任務工單編排。在 Sprint 2 將高流量測試的環境配置與腳本規格指派給實作員。 |
| **`GENERAL_OOP_IMPLEMENTER`** | 擴展範圍 | 根據工單，除編寫業務代碼外，亦編寫 `docker-compose.yml`, `Dockerfile`, `nginx.conf` 與 k6 腳本。 |
| **`REVIEWER_REFACTOR`** | 收斂職責 | 僅進行代碼走查與 Mock 單元測試審查。通過後同步推廣至 `src/` 即完成工作。 |
| **`INTEGRATION_TESTER`** | **[NEW] 新增** | 讀取 `src/`，負責 Docker Sandbox 搭建、執行 k6 壓測與資料一致性對帳，將全量日誌輸出至 `log/sandbox_runtime.log`。 |
| **`LOG_ANALYZER_RECOVERY`** | 輸入源對齊 | 唯一輸入對接 `log/sandbox_runtime.log`，解析實體併發/資料庫死鎖等異常並反饋給實作員。 |

### 4. 變更版本與生效時間
*   **生效時間**：2026-05-19
*   **Agent 設定更新**：
    *   新增 `agents/integration_tester.json` (v1.0.0)

## [2026-05-19] 整合測試實體環境執行異常修復紀錄 (Sprint 2 Diagnostics Logs)

### 1. 異動概述
在 `INTEGRATION_TESTER` 執行沙盒整合測試期間，遭遇了數個運行期崩潰與連線競態條件。此紀錄詳細追蹤了問題現象、根因診斷與修復路徑。

### 2. 問題診斷與自動修復紀錄

#### 案一：Worker 容器啟動 `ImportError` 異常
*   **日誌錯誤**：
    ```text
    Dumping queue worker logs...
    Traceback (most recent call last):
      File "/workspace/src/app/worker.py", line 9, in <module>
        from .services import RedisCacheService, MySQLOrderRepository
    ImportError: attempted relative import with no known parent package
    ```
*   **根因分析**：
    在 `Dockerfile.worker` 中，原先使用 `python src/app/worker.py` 直接啟動。此方式會導致 Python 以主程式模式而非包模組模式執行，致使相對導入語法失效。
*   **修復決策**：
    將 `Dockerfile.worker` 啟動命令修改為以 package 方式調用：`python -m src.app.worker`。

#### 案二：FastAPI 與 Worker 容器資料庫連線競態條件 (Connection Refused)
*   **日誌錯誤**：
    ```text
    pymysql.err.OperationalError: (2003, "Can't connect to MySQL server on 'db_mysql'")
    ```
*   **根因分析**：
    MySQL 容器就緒（Docker Healthcheck 通過）與 MySQL TCP 埠完全開放監聽（綁定 TCP port 3306）之間存在極小的毫秒級時間差。FastAPI 與 Worker 提早連線導致 Socket 連線被拒絕。此外，FastAPI 首次重試時因 `main.py` 漏掉 `import asyncio` 拋出 `NameError`。
*   **修復決策**：
    1. 在 `main.py` 補上 `import asyncio`。
    2. 在 `main.py` 與 `worker.py` 的 MySQL 連線池創建處，加入 5 次重試與 2 秒間隔的防禦性重試機制。
    3. 重構 `run_sandbox_test.ps1` 啟動順序，實施「分步引導啟動（Sequenced Bootstrapping）」：優先啟動 `db_mysql` 與 `redis`，待 `docker inspect` 確認 MySQL 狀態完全變為 `"healthy"` 後，再以 `--build` 參數編譯並啟動後端主機與 Gateway 服務。

### 3. 測試驗證結果
經修復後重新啟動整合測試，所有容器正常啟動，未再出現連線中斷或錯誤。壓測資料成功透過背景隊列寫入，最後對帳結果如下：
*   **MySQL Success Order Count**: `39`
*   **Redis Hash Success Count**: `39`
*   **Remaining Stock**: `161`
*   **對帳結果**：**`[RECONCILE_SUCCESS]`**（完全無超賣，資料對齊一致）。
