# src_staging/ — AI Agent 審查暫存區

## 用途說明

`src_staging/` 是本專案 AI 協作工作流程（Multi-Agent Pipeline）中的**程式碼審查暫存區**，由 `GENERAL_OOP_IMPLEMENTER` Agent 將實作成果寫入此目錄後，交由 `REVIEWER_REFACTOR` Agent 進行走查。

**只有通過審查的程式碼，才會被放行（同步）至 `src/` 正式目錄並進入整合測試。**

```
[GENERAL_OOP_IMPLEMENTER] → src_staging/ → [REVIEWER_REFACTOR 審查] → src/ → [INTEGRATION_TESTER]
```

> **注意**：此目錄內容為最後一次審查通過的快照，與 `src/` 內容相同。實際開發與執行請使用 `src/` 目錄。
