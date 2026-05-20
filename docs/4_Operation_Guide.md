# Operation_Guide.md: 系統維運與緊急應變手冊

## 1. 系統檢查清單 (Pre-Event Checklist)
在搶票活動正式開始前 30 分鐘，維運人員必須完成以下實體檢查：

*   **Docker 容器健康狀態**：
    *   執行 `docker compose ps` 確認 `nginx`、`app`、`redis`、`mysql` 與 `worker` 所有服務皆處於 `Up` 狀態。
*   **MySQL 資料庫預熱與清理**：
    *   確認 `orders` 表已清理乾淨（無舊測試資料）。
    *   確認已配置 `member_id` 與 `event_id` 的聯合唯一索引 (Unique Index)，防止重複寫入。
*   **Redis 初始化與預熱**：
    *   確認舊的搶票佇列 `ticket:request:queue` 與成功名單 `ticket:success:orders` 已被 `DEL` 清空。
    *   設定活動初始票數，指令：`SET ticket:stock:{event_id} <Total_Tickets>` (例如 20000)。
*   **網關防禦配置檢驗**：
    *   檢查 Nginx 限流配置是否生效，確認靜態網頁（HTML/JS）已正確託管至網關層目錄下，達成動靜分離。

---

## 2. 緊急操作指令 (Emergency Operations)

當搶票現場發生異常時，維運人員應依照本手冊立即下達指令：

### A. 全域熔斷 (Global Circuit Breaker)
*   **情境**：發現 Token 驗證代碼發生核心死鎖、資料庫崩潰或收到法規/管理層緊急停售指令。
*   **操作方法**：
    1.  **快取級熔斷**（由 App 處理）：於 Redis 中直接寫入強制售罄旗標。
        *   指令：`SET ticket:soldout:flag true`
        *   效果：後端 App 讀取到此 Flag 後將立即短路，對所有進來的請求直接回應「活動結束」，停止向佇列寫入。
    2.  **網關級阻斷**（極端流量打滿）：修改 Nginx 配置直接將動態 API 阻斷。
        *   修改 `nginx.conf` 將 `/api/v1/tickets/` 路由段改為 `return 503;`。
        *   重載指令：`docker compose exec nginx nginx -s reload`

### B. 庫存人工緊急修正
*   **情境**：對帳系統回報快取庫存數據與實際售出不符，需人工緊急補貨或減扣。
*   **操作指令**：
    *   修改 Redis 快取庫存：`SET ticket:stock:{event_id} <Correct_Amount>`
    *   備註：若 Master 原本已扣至 0，在人工作業將庫存設為大於 0 時，必須同步移除全域售罄旗標：`DEL ticket:soldout:flag`，否則系統會繼續處於售罄熔斷狀態。

---

## 3. 常見問題與處理 SOP (Troubleshooting)

| 問題現象 | 可能原因 | 處理 SOP |
| :--- | :--- | :--- |
| **大量客戶端收到 HTTP 503/403** | 網關層 (Nginx) 觸發每秒限流阻斷，惡意流量刷屏。 | 1. 確認是否為單一 IP 惡意攻擊。<br>2. 若為正常流量大於預估，評估修改 `nginx.conf` 中的 limit_req 速率，並執行 `nginx -s reload`。 |
| **排隊等待時間過長，佇列大量積壓** | 後端 Worker 消費速度跟不上，或 MySQL 資料庫寫入出現瓶頸。 | 1. 執行 `docker compose scale worker=5` 擴容 Worker 容器執行緒。<br>2. 檢查 MySQL 是否有長期事務锁 (Long Transaction Locks)。 |
| **出現「資料不一致 (Data Mismatch)」警報** | Background Worker 寫入 MySQL 失敗，导致 Redis 已扣票但 DB 無紀錄。 | 1. 執行對帳補償腳本找出未落庫的 `member_id`。<br>2. 使用補帳指令強制將中獎明細補寫入 MySQL。 |

---

## 4. 數據對帳腳本使用指南 (Reconciliation CLI)

系統提供指令供手動執行即時對帳，比對 Redis 與 MySQL 資料一致性：

*   **執行對帳**：
    `docker compose exec worker python manage.py reconcile --event_id concert_2026`
*   **對帳輸出解讀**：
    - `DIFF = 0` (SUCCESS)：Redis 快取扣減量與 MySQL 實體訂單數完全相符，庫存 100% 精確。
    - `DIFF > 0` (WARN)：有 Redis 已中獎名單但 MySQL 漏單，系統會自動輸出遺漏的 `member_id` 清單，並提示補單。
    - `DIFF < 0` (CRITICAL)：MySQL 訂單數多於 Redis 預扣數，代表發生嚴重的超賣，需立即暫停活動並排查日誌。