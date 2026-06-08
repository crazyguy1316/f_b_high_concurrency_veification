# 高併發搶票驗證系統 (High-Concurrency Ticketing Verification System)

## 專案緣起與協作模式 (Project Genesis & Collaboration Model)
本專案由**專案執行者（扮演 SD 系統設計師 與 SI 系統整合商 雙重角色）**與多位專業領域的 **AI Agents** 協作完成。

在這個協作過程中，由人類主導架構方向、業務規格定義與資源調度（採用嚴謹的 Waterfall Flow 瀑布式流向管控），而各專屬 AI Agents 則被精確指派到對應的開發與維運階段（包含 `ARCHITECT_DISPATCHER`, `GENERAL_OOP_IMPLEMENTER`, `REVIEWER_REFACTOR`, `INTEGRATION_TESTER`, `LOG_ANALYZER_RECOVERY`）。實現從概念設計、程式實作、架構走查到高壓自動化測試的完美閉環，展示人機協同在複雜系統開發上的潛力與風險控管。

## 業務問題目標 (Business Objectives)
本專案旨在解決現代電商或售票系統中最嚴苛的業務場景：**極短時間內的瞬間極高併發請求（Flash Sales / Ticketing）**。
主要解決的業務痛點與目標包含：
1. **防止超賣 (Zero Overselling)**：在萬人同時點擊「搶票」的毫秒級競爭下，確保庫存絕對準確，絕不產生負庫存或超額訂單。
2. **流量削峰 (Traffic Shaping)**：保護後端關聯式資料庫（MySQL），避免因瞬間海量連線導致資料庫資源耗盡、崩潰或死鎖。
3. **優雅降級與順暢的使用者體驗**：在系統滿載時，能夠透過網關阻擋惡意請求，並透過前端非同步輪詢（Polling）機制，提供使用者明確的排隊與等待回饋，而非呈現伺服器崩潰頁面。
4. **資料最終一致性 (Eventual Consistency)**：確保快取（Redis）的超高速運算結果，能穩定且不遺漏地持久化回歸至永久儲存層（MySQL），完成最終的對帳一致。

## 技術門檻與核心架構 (Technical Thresholds & Core Architecture)
為了達成上述的業務目標，本專案跨越了數項具備高技術門檻的核心架構：

### 1. 分散式快取與 Lua 腳本原子操作
*   放棄傳統 MySQL 的 `SELECT ... FOR UPDATE` 行鎖（這在高併發下會導致嚴重的阻塞與效能瓶頸），改用 Redis 儲存即時庫存。
*   撰寫 Redis Lua Script 確保「檢查庫存」與「扣減庫存」的原子性（Atomicity），徹底消除分散式系統下的競態條件（Race Condition）。

### 2. 非同步訊息佇列機制 (Asynchronous Message Queue)
*   採用 Redis List 作為非同步隊列，FastAPI 後端接收到合法請求後，僅將訂單拋入隊列即回應 `HTTP 202 Accepted`，將回應時間縮短至毫秒級，釋放伺服器連線資源。
*   獨立的 Background Worker 以非同步 (asyncio) 方式持續消費隊列，進行緩衝與批次寫入 MySQL。

### 3. 高防禦 Nginx API Gateway
*   實作嚴格的 Rate Limiting (限流) 區域機制，防禦惡意洗頻與 DDoS 衝擊。
*   擔任反向代理與靜態資源伺服器，將前端（HTML/JS）與後端 API 完全分離。

### 4. 嚴謹的物件導向設計 (SOLID Principles)
*   嚴格遵循依賴反轉原則（Dependency Inversion），利用介面 (`ITokenValidator`, `IQueuePublisher`, `IOrderRepository`) 解耦業務邏輯與底層驅動。
*   確保系統具備極高的可測性與抽換彈性。

### 5. 容器化與自動化沙盒部署 (Docker Orchestration)
*   透過 Docker Compose 達成微服務一鍵部署，並撰寫嚴謹的腳本建立「分步引導啟動（Sequenced Bootstrapping）」，排除微服務啟動過程中的資料庫依賴時差錯誤。
*   內建 `k6` 高併發壓力測試沙盒，可自動生成 1,000 個虛擬用戶狂暴轟炸，並於測試結束後執行自動化資料對帳審計（Reconciliation Audit），證明架構的絕對強健性。

## 系統元件與技術堆疊 (Tech Stack)
*   **前端介面**：HTML5, Vanilla JS, CSS3 (Glassmorphism UI 現代化設計)
*   **反向代理與網關**：Nginx (Alpine)
*   **非同步後端框架**：FastAPI (Python 3.11), Uvicorn, asyncio
*   **快取與佇列引擎**：Redis 7
*   **關聯式資料庫**：MySQL 8.0 (aiomysql / PyMySQL)
*   **架構驗證與壓測工具**：k6, Pytest, Docker Compose, PowerShell

## 📁 文件索引 (Documentation Index)

| 文件 | 說明 |
|---|---|
| [1. 需求規格書](docs/1_requirement_specification.md) | 業務目標、系統邊界與非功能性需求定義 |
| [2. 流程圖](docs/2_Flow_Diagram.md) | 端到端請求流程圖與元件互動時序圖 |
| [3. 監控計畫](docs/3_Monitoring_Plan.md) | 指標收集、告警閾值與觀測策略 |
| [4. 操作指南](docs/4_Operation_Guide.md) | 本機部署與沙盒壓測執行步驟 |
| [5. 資料契約](docs/5_Data_Contract.md) | API Request/Response Schema 與 Redis Key 命名規範 |
| [6. 測試計畫](docs/6_Test_Plan.md) | k6 壓測策略、對帳驗證邏輯與測試通過標準 |
| [ADR-001: 技術選型決策](docs/adr/ADR-001.md) | 核心架構選型理由（Nginx + Redis Lua + 非同步 Worker） |
| [ADR-002](docs/adr/ADR-002.md) | 其他架構決策紀錄 |

## 🚀 快速啟動 (Quick Start)

### 前置需求
- Docker & Docker Compose
- Python 3.11+（含虛擬環境）
- k6（壓測工具，透過 Docker 自動拉取，無需手動安裝）

### 一鍵執行沙盒壓測

```powershell
# 1. 複製環境變數範本
Copy-Item .env.example src/.env

# 2. 在 src/.env 中設定你的密碼（沙盒環境可直接使用預設值）

# 3. 從專案根目錄執行完整壓測（含自動啟動、壓測、對帳、清理）
.\src\run_sandbox_test.ps1
```

測試結束後，對帳結果將輸出於 `log/sandbox_runtime.log`。通過標準為 MySQL 成交筆數 = Redis 成功名單筆數，且無超賣。

---
*Generated collaboratively by SD/SI Project Executor and Antigravity AI Agents (2026).*
