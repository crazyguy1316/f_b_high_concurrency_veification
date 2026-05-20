# 系統需求說明書 (System Requirement Specification)
## 專案名稱：高併發搶票交易驗證系統 (High-Concurrency Ticketing Verification System)

### 1. 專案目標 (Project Objective)
本專案旨在透過**小型硬體環境**（如單機或少量容器環境）驗證分散式系統架構之效能。核心目標在於建立一套**可橫向擴展應付 High-Concurrency** 的可靠的交易驗證機制，確保在**萬人級別同時湧入**的極端情境下，系統仍能維持穩定運作，杜絕系統崩潰（System Crash）與庫存超賣（Overselling）之風險。

### 2. 核心功能需求 (Functional Requirements)

| 功能模組 | 描述 |
| :--- | :--- |
| **前後端 API 介接 (Frontend/Backend API)** | 系統採前後端分離。前端發起請求時，僅需攜帶以 `int` 型別實作的 `member_id`（降低運算成本）與簡化的 `token` 以進行買票驗證。 |
| **交易與身份驗證 (Transaction & Token Verification)** | 實作簡化的 Token 驗證機制。攔截無效請求，確保每筆交易合法。 |
| **排隊機制 (Queueing)** | 建立流量緩衝區，攔截瞬間湧入的非法或重複請求，確保後端服務負載穩定。 |
| **扣庫存 (Inventory Deduction)** | 實作具備原子性（Atomicity）的扣庫存邏輯，保證在高併發環境下數據的一致性。 |
| **資料庫持久化 (MySQL Persistence)** | 採用 MySQL 作為資料庫（測試方便）。執行完成後，需存有購買紀錄供查詢哪些 `member_id` 成功購買，且販售票數需與模擬數據完全吻合。 |
| **邊緣防禦與流量調度 (Edge Defense & Traffic Ingress)** | 整合反向代理網關（Reverse Proxy Gateway）進行動靜分離、邊界限流清洗與安全預檢，保障核心服務可用性。 |

#### 2.1 邊緣防禦與流量調度架構 (Edge Defense & Traffic Ingress)
1. **職責定義 (Responsibility)**
   為確保高併發搶票期間核心應用程式（Application Core）的可用性，系統採用「反向代理網關（Reverse Proxy Gateway）」作為唯一合法的外部網路進入點。所有前端靜態資源請求與動態 API 請求皆由網關進行高併發調度，嚴禁外部流量直接觸發後端服務。

2. **核心控制機制**
   網關層於本階段衝刺（Sprint）核心承擔以下三項防禦與解耦職責：
   *   **靜態資源邊界解耦 (Static Content Offloading)：**
       網關層在作業系統核心（OS Kernel）級別直接託管、緩存並回傳前端精簡 Web 網頁（HTML/JS）。此機制可將「靜態讀取流量」與「動態計算流量」徹底分離，確保後端應用程序服務（Application Server）的執行緒（Threads）100% 聚焦於處理高價值的代碼校驗與隊列寫入。
   *   **流量清洗與邊界速率限制 (Rate Limiting & Traffic Shaving)：**
       針對動態搶票端點（/api/v1/tickets/*），網關層實作「基於客戶端特徵（如來源 IP）的令牌桶/漏桶控制演算法」。限制單一客戶端之每秒最大存取頻率（例如 2r/s），一經偵測超過閾值（Burst limit），網關將於邊界直接阻斷並回應 HTTP 403 / 503，達成無損耗的惡意流量清洗，保護後端消息佇列（MQ）不因阻斷服務攻擊（DoS）而崩潰。
   *   **安全邊界預檢（Security Pre-verification）：**
       網關層負責過濾畸形請求（Malformed Requests），在第一時間剔除長度不合規、格式錯誤之無效存取，僅將結構正確的請求轉發至應用層。

3. **CDN 邊界模擬與演進策略 (CDN Edge Simulation & Evolution Strategy)**
   本專案定位為本地單機驗證，為控制研發成本與環境複雜度，現階段『實作層』不引入外部雲端 CDN。
   但為了確保高併發搶票的系統架構完整性，將 CDN 的兩大核心核心職責——『靜態資源分流』與『邊界流量清洗（限流防刷）』——全權封裝在最前端的網關層（Gateway）進行模擬。

   **此設計的核心價值在於：**
   *   **商業防禦：** 在邊界就攔截無效點擊，保護後端核心業務不受影響。
   *   **投資保護：** 未來系統要規模化（Scale-up）上雲端時，現有的網關配置可直接無縫移植到實體 CDN，確保前期的開發架構完全具備延續性。



### 3. 技術指標 (Non-functional Requirements / Technical Metrics)

為達成資深等級的系統設計，本專案設定以下硬性技術指標：

#### A. 併發性能 (Concurrency)
*   **目標流量：** 10,000 QPS (Queries Per Second)。
*   **驗證重點：** 系統需在 CPU/Memory 受限的小型環境下，透過優化算法與中間件配置達成此目標。

#### B. 延遲控制 (Latency)
*   **響應標準：** P95 Latency < 500ms。
*   **定義：** 95% 以上的有效請求必須在 5 秒內完成從發起到回傳結果的完整週轉。

#### C. 高可用性 (Availability & Reliability)
*   **故障轉移 (Failover)：** 系統關鍵組件（如 Cache, Message Queue）需具備故障偵測與自動切換機制。
*   **容錯處理：** 當單點服務失效時，系統應能自動降級（Degradation），確保核心購票流程不中斷。

---

### 4. 實作環境與測試限制 (Environment & Testing Constraints)
*   **容器化部署：** 測試環境必須全面架設於 Docker 上，以單機多容器 (Docker Compose) 模擬分散式佈署。
*   **壓測工具：** 採用 **k6** 模擬大量連線存取測試。
*   **測試案例要求：** 
    *   測試中需混入部分 `token` 驗證失敗的案例，作為模擬登入失敗或不承認的非法存取。
*   **資料對帳驗證：** 
    *   測試執行完成後，MySQL 中的最終成交量（成功購買紀錄）必須與測試賣出量一致。
*   **開發原則：** 優先考慮「效能功耗比」，利用緩存與非同步處理減少磁碟 I/O 壓力。