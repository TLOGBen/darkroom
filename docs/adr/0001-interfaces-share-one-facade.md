# 三個入口共用一個 facade，入口只做格式轉換

Web App（HTTP）、CLI、MCP 都只是入口：各自的 action／controller 解析參數、呼叫同一個 facade 介面、把結果與錯誤轉成自己的格式（HTTP 狀態碼、CLI 結束碼、MCP isError）。驗證、夾值、錯誤句子、原檔唯讀與匯出不覆蓋這些規則全部在 facade 之後的 service 裡。這樣代理和人做同一件事時結果一定一致，新功能只寫一次 service（使用者 2026-10-09 指定）。

## Consequences

- 現有 `darkroom_app/server.py` 裡的邏輯要先搬進 service，HTTP handler 變薄；既有 App 測試整套當回歸。
- 某個 service 要換成更快的實作（例如 Rust，見 0003）時，facade 與三個入口都不用改。
