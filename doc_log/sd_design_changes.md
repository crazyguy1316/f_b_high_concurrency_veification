## [2026-05-19] 技術選型評審：確立 Async I/O 連線庫之併發安全邊界

### 1. 選型定案
- 後端驅動核心全面採用 `redis.asyncio` 與 `aiomysql`，以異步非阻塞（Non-blocking）模式極大化 FastAPI 之 RPS。

### 2. 併發防禦約束（Anti-Pattern Guardrail）
- **禁止狀態交錯**：嚴禁在 Python 代碼層面使用 `await redis.get` 與 `await redis.set` 進行組合式業務狀態變更。
- **動態防線**：所有涉及「庫存、身分防重」等狀態變更，一律強制走 `await redis.eval()` 調用原子化 Lua 腳本，藉由 Redis 單線程核心確保 Asyncio 協程交錯時的資料絕對一致。

---

## [2026-05-19] 團隊協作架構異動：引入 Waterfall Flow 與專職整合測試 Agent

### 1. 變更緣由
為縮減單一開發階段的除錯範圍（Blast Radius），優化團隊交付管道：
- 確立 **Waterfall Flow（瀑布式流程）** 工作原則：每個 Agent 在完成本階段職責後即刻停止，防堵開發與測試範疇發散。
- 原 `REVIEWER_REFACTOR` 僅專注於「靜態代碼走查」與「單一單元測試（Mock）」，不應跨足實體容器集群搭建。
- 新建 **`INTEGRATION_TESTER`** 專職 Agent，專門負責 Docker Compose 環境編排、k6 萬人高併發壓力測試，以及最終的資料一致性對帳審計。

### 2. 受影響 Agent
- **新增**：`INTEGRATION_TESTER` (專門負責實體 Docker 壓測與對帳)
- **調整**：`REVIEWER_REFACTOR` (職責收斂至代碼審查與 staging 同步，不再兼任沙盒調控與壓測)
- **連動**：`LOG_ANALYZER_RECOVERY` (輸入源對接由 `INTEGRATION_TESTER` 產出的 `log/sandbox_runtime.log`)

### 3. 受影響 src 子目錄
- `project_root/src/` （做為容器化部署的輸入來源）
- `project_root/log/` （運行期 Sandbox 輸出日誌目錄）

### 4. 前後架構對比
*   **舊架構**：
    `ARCHITECT_DISPATCHER` $\rightarrow$ `GENERAL_OOP_IMPLEMENTER` $\rightarrow$ `REVIEWER_REFACTOR` (審查 + 同步 + 隱式宣稱壓測通過) $\rightarrow$ 流程結束（缺乏實體壓測驗證與閉環）。
*   **新 Waterfall 架構**：
    `ARCHITECT_DISPATCHER` (開工單) $\rightarrow$ `GENERAL_OOP_IMPLEMENTER` (代碼編寫) $\rightarrow$ `REVIEWER_REFACTOR` (靜態審查 & 放行至 src) $\rightarrow$ `INTEGRATION_TESTER` (實體容器搭建、k6 壓測、對帳日誌輸出) $\rightarrow$ `LOG_ANALYZER_RECOVERY` (監聽日誌，若 Failed 則輸出 JSON Healing 引導回退至實作員；若 Success 則正式通過驗證)。

---

## [2026-06-03] 架構決策正式化：最終一致性模型與對帳補償策略（ADR-006）

### 1. 變更緣由
ADR-003 §2.3 聲明了 Lua 原子性邊界止於 Redis 內部，Redis→MySQL 之間屬於分散式事務問題，但僅以引用方式帶過，未形成完整的決策文件。本次補完正式化此一致性策略，確立以下核心架構決策。

### 2. 受影響 Agent
- **`INTEGRATION_TESTER`**：明確其強制執行 `reconcile.py` 的責任（對帳失敗即測試失敗）。
- **`LOG_ANALYZER_RECOVERY`**：明確 `[RECONCILE_FAILURE]` 為觸發日誌分析的系統故障信號。
- **`GENERAL_OOP_IMPLEMENTER`**：明確 `reconcile.py` 必須實作補償邏輯（從 Redis Hash 重建 MySQL 缺失訂單）。
- **`REVIEWER_REFACTOR`**：審查清單新增：MySQL INSERT 失敗時嚴禁反向回滾 Redis。

### 3. 受影響 src 子目錄
- `project_root/src_staging/tests/reconcile.py`（補償邏輯規格更新）

### 4. 前後架構對比
*   **舊定義（隱含）**：`reconcile.py` 僅做「比對 MySQL 與 Redis 筆數是否相等」，相等則通過，不等則失敗。補償路徑未定義。
*   **新定義（ADR-006）**：`reconcile.py` 在發現差異後必須執行補償（從 Redis Hash 重建缺失訂單），補償後再次驗證。`MySQL 筆數 > Redis Hash 筆數` 為系統故障信號。明確定義五類已接受的技術債與風險。