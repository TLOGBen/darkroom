# darkroom

本機專業相片編輯：套用 Lightroom XMP preset、調強度與微調滑桿、拖動即時預覽，AI 只做程式做不到的部分（看圖給建議數值、遮罩、移除雜物、放大）。

**狀態**：規劃中。路線與所有決定在 [`.claude/wayfinder/darkroom/map.md`](.claude/wayfinder/darkroom/map.md)。

- 核心：版本化的參數 schema（Lightroom crs 鍵名）＋torch GPU 渲染的函式庫
- 介面：獨立本機 App（Python 後端＋Web 前端）
- 模型：本機 llama-server（看圖給數值）；擴散模型透過 ComfyUI API（`C:/Users/powde/workspace/LocalLLMs`）
