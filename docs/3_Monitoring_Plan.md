# Monitoring_Plan.md: 邊緣防禦與流量佇列監控預警方案

## 1. 監控哲學 (Monitoring Philosophy)
針對本專案的前後端分離及網關防禦架構，監控策略聚焦於「多層級防禦流量清洗」與「資料最終一致性對帳」：
- **邊緣網關層 (Gateway)**: 監控惡意 IP 限流阻斷率及畸形請求過濾數。
- **應用伺服器層 (App Server)**: 監控 Token 驗證失敗率、佇列寫入速度。
- **快取佇列層 (Redis MQ & Cache)**: 監控佇列堆積量、Lua 扣減延遲、暫存訂單數。
- **資料庫層 (MySQL DB)**: 監控實體訂單落庫速率與對帳一致性。

---

## 2. 核心觀測指標 (Key Metrics)

### A. 網關與邊緣防禦指標 (Nginx / Gateway)
| 指標名稱 | 觀測來源 | 說明 | 警報閥值 |
| :--- | :--- | :--- | :--- |
| **限流阻斷率 (Rate Limit Blocks)** | Nginx error.log | 因觸發每秒頻率限制 (如 >2r/s) 被回傳 403 / 503 的請求數。 | 連續 1 分鐘 > 30% 總流量 (P1) |
| **無效請求過濾數 (Malformed Requests)** | Nginx access.log | 因格式不合規被邊界直接剔除的畸形請求數。 | 連續 1 分鐘 > 1000 筆 (P2) |

### B. 應用與身份驗證指標 (App Server)
| 指標名稱 | 觀測來源 | 說明 | 警報閥值 |
| :--- | :--- | :--- | :--- |
| **Token 驗證失敗率** | App Server Log | 因 Token 驗證失敗 (登入失效/非法存取) 被回傳 401 的佔比。 | 佔總請求比率 > 20% (P1) |
| **佇列寫入延遲 (Enqueue Latency)**| App Server | 請求寫入 Redis List 佇列所耗費的時間。 | P99 > 50ms (P2) |

### C. 佇列與快取指標 (Redis)
| 指標名稱 | Redis 指令 / Key | 說明 | 警報閥值 |
| :--- | :--- | :--- | :--- |
| **佇列堆積長度 (Queue Backlog)** | `LLEN ticket:request:queue` | 目前待處理的排隊搶票請求數。 | 長度 > 50,000 (P1) |
| **Lua 扣減延遲 (Lua Execution)** | Redis Slowlog | Lua 庫存扣減腳本執行耗時。 | 執行耗時 > 10ms (P1) |
| **快取剩餘庫存 (Cache Stock)** | `GET ticket:stock:{event_id}` | 目前快取層剩餘的票數。 | 餘額為 0 且佇列已空 (INFO) |
| **快取成功名單數 (HSET Size)** | `HLEN ticket:success:orders` | 快取記錄中成功預扣的名單總量。 | 超過初始釋出票數 (P0 - 超賣) |

### D. 資料庫持久化指標 (MySQL)
| 指標名稱 | 觀測來源 | 說明 | 警報閥值 |
| :--- | :--- | :--- | :--- |
| **MySQL 落庫速率 (Write QPS)** | MySQL Stats | 背景 Worker 異步寫入訂單的速率。 | 寫入 QPS < 500/s (P2) |
| **落庫失敗/超時數** | Worker Log | 因資料庫死鎖、連線中斷導致寫入失敗的次數。| 失敗數 > 0 (P0 - 需補償) |

---

## 3. 異常預警機制 (Lightweight Alerting)

警報分級定義與通報媒介：

| 警報等級 | 觸發條件 | 通報媒介 | 緊急行動 |
| :--- | :--- | :--- | :--- |
| **P0 (Emergency)** | Redis 中獎暫存數 != MySQL 實體訂單數，或成功單數 > 釋出票數 | Webhook + PagerDuty | 立即啟動全域熔斷，暫停 Worker 消費，進行對帳人工介入。 |
| **P1 (Critical)** | 佇列堆積長度持續攀升且消費速度為 0 (Worker 崩潰) | Webhook (Slack / Discord) | 檢查 Worker 容器健康度，執行自動或手動重啟 Worker。 |
| **P2 (Warning)** | Redis 記憶體使用率 > 80% 或 Nginx 限流率偏高 | Webhook (Slack / Discord) | 評估是否擴容 Redis 或調整限流閾值。 |

---

## 4. 定期對帳與資料一致性審計 (Reconciliation Engine)

系統配置背景程序執行離線資料對帳，驗證最終一致性：

1. **對帳公式**:
   $$\text{MySQL 訂單總量} == \text{Redis } \texttt{ticket:success:orders} \text{ 雜湊表總數} == (\text{初始票數} - \text{Redis 剩餘庫存})$$
2. **對帳頻率**:
   - 搶票進行中：每 1 分鐘執行一次增量對帳。
   - 搶票結束後：執行完整對帳，產出最終對帳報告。
3. **異常修正**:
   - 若 MySQL 筆數 < Redis 成功名單數：指出特定缺失 `member_id`，觸發重試機制補寫入 MySQL。
   - 若 MySQL 筆數 > Redis 成功名單數：代表發生嚴重邏輯穿透，人工介入標記訂單並安排退款。
