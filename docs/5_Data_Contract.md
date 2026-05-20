# Data_Contract.md: 資料規格與通訊契約

## 1. API 介面規範 (RESTful API)

本系統採前後端分離架構，前端發起請求時，僅需攜帶簡化之 `member_id` (以 `int` 實作以降低解析與傳輸開銷) 及用於身份認證之 `token`。

### A. 搶票下單接口 (Order Reservation Request)
* **HTTP Method**: POST
* **Path**: `/api/v1/tickets/{event_id}/reserve`
* **Content-Type**: `application/json`
* **Request Header**: 
  - `Authorization: Bearer <token>`
* **Request Body**: (請參閱附錄 [JSON 區塊 1.A])
* **Response**:
    - **202 Accepted**: 成功寫入佇列排隊中，回傳輪詢導向。(參閱 [JSON 區塊 1.B])
    - **401 Unauthorized**: Token 驗證失敗，不承認之存取。(參閱 [JSON 區塊 1.C])
    - **403 Forbidden**: 網關限流觸發，阻斷非法刷票。(參閱 [JSON 區塊 1.D])
    - **503 Service Unavailable**: 服務過載或已開啟全域熔斷。

### B. 訂單狀態輪詢接口 (Order Status Polling)
* **HTTP Method**: GET
* **Path**: `/api/v1/orders/{event_id}/{member_id}`
* **Response**:
    - **200 OK**: 成功獲取搶票處理狀態（排隊中/成功/失敗）。(請參閱 [JSON 區塊 1.E])
    - **404 Not Found**: 查無此訂單紀錄。

---

## 2. Redis Key 命名與資料結構 (Naming Convention)

| Key 範例 | 資料型別 | TTL | 描述 |
| :--- | :--- | :--- | :--- |
| `ticket:stock:{event_id}` | String | 24h | 快取層核心剩餘票數庫存 |
| `ticket:request:queue` | List | 1h | 削峰佇列 (LPUSH 入隊, BRPOP 出隊) |
| `ticket:success:orders` | Hash | 48h | 預扣成功名單雜湊表 (欄位為 `member_id`) |
| `ticket:user:has_bought:{event_id}:{member_id}` | String | 24h | 用於 Lua 內重複購買判斷的防重唯一 Key |
| `ticket:soldout:flag` | String | 24h | 全域熔斷/售罄標記 |

---

## 3. 資料庫 Schema (Database Schema)

本專案於 Docker 容器中使用 MySQL 作為實體資料庫，用於最終一致性持久化與對帳。

### 訂單表 (orders)
* `id`: BIGINT (PK, Auto Increment)
* `member_id`: INT (Indexed) ── 使用 `int` 實作以降低環境運算成本
* `event_id`: VARCHAR(64) (Indexed)
* `status`: VARCHAR(32) (例如：'SUCCESS', 'FAILED')
* `created_at`: TIMESTAMP (Default CURRENT_TIMESTAMP)

> [!IMPORTANT]
> 必須建立聯合唯一索引 `UNIQUE KEY uk_member_event (member_id, event_id)`。這能在資料庫層面提供最終的冪等性與重複購買防護。

---

## 4. 佇列訊息協定 (Queue Message Protocol)

當 App Server 驗證 Token 成功後，將搶票請求打包為 JSON 字串，以 `LPUSH` 推入 Redis 佇列。

* **佇列名稱**: `ticket:request:queue`
* **訊息格式**: (請參閱附錄 [JSON 區塊 4.A])

---

## 附錄：JSON 數據區塊 (Raw JSON Schemas)

### [區塊 1.A] Order Reservation Request Body
```json
{
  "member_id": 100249,
  "token": "simplified_session_token_xyz"
}
```

### [區塊 1.B] 202 Accepted Response (入隊排隊中)
```json
{
  "status": "QUEUED",
  "message": "Request successfully enqueued. Please poll order status.",
  "poll_url": "/api/v1/orders/concert_2026/100249"
}
```

### [區塊 1.C] 401 Unauthorized Response (Token 失敗)
```json
{
  "error": "UNAUTHORIZED",
  "message": "Invalid or expired session token."
}
```

### [區塊 1.D] 403 Forbidden Response (網關限流)
```json
{
  "error": "RATE_LIMIT_EXCEEDED",
  "message": "Too many requests. Please slow down."
}
```

### [區塊 1.E] Polling Status Response (輪詢狀態)
```json
{
  "member_id": 100249,
  "event_id": "concert_2026",
  "status": "PENDING|SUCCESS|FAILED",
  "message": "Status description"
}
```

### [區塊 4.A] MQ Enqueue Payload
```json
{
  "event_id": "concert_2026",
  "member_id": 100249,
  "timestamp": 1715765415
}
```