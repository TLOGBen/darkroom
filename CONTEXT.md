# darkroom

在本機用使用者買的 Lightroom preset 修照片：挑 preset、調強度、微調滑桿，即時預覽，再匯出成新檔。照片原檔與 preset 原檔永遠不被改寫。

## 調色

**Preset**（Preset）：
使用者買來的一個 Lightroom XMP 檔，代表一組調色設定。原檔唯讀，darkroom 只讀它。
_Avoid_：預設集、濾鏡、樣式

**自存 preset**（UserPreset）：
使用者從一份編輯另存出來的 preset，存在 preset 庫的使用者區。跟買來的 preset 一樣可以挑、可以套。
_Avoid_：自訂 preset、我的 preset

**調色參數**（Params）：
一個 preset 在 100% 強度時的全部設定值，用 Lightroom 的設定名稱記錄；包含全域滑桿、曲線、漸層遮罩與略過的設定。
_Avoid_：設定檔、參數檔、preset 資料

**強度**（Strength）：
把 preset 的效果從 0% 放大到 200% 的比例；100% 就是 preset 原本的樣子，0% 等於沒套。
_Avoid_：濃度、混合比例、透明度

**微調**（Overrides）：
使用者在 preset×強度之上，對個別滑桿再加減的差值。微調是差值，不是絕對值。
_Avoid_：覆寫、手動值、調整值

**最終參數**（EffectiveParams）：
preset 依強度縮放、夾進範圍，再加上微調、再夾一次之後，真正拿去渲染的那組值。由編輯算出來，不另外儲存。
_Avoid_：結果參數、套用後參數

**略過的設定**（Skipped settings）：
preset 裡有、但 darkroom 目前無法套用的設定。分兩級：**觀感級**（會讓畫面看起來不一樣，要提醒使用者）與**細節級**（對 JPEG 預覽幾乎沒影響）。
_Avoid_：不支援的設定、錯誤

## 照片與編輯

**照片**（Photo）：
使用者硬碟上的一個影像原檔（JPEG、PNG、TIFF、HEIC）。原檔唯讀；以**照片指紋**辨認，不以路徑辨認。
_Avoid_：圖片、影像、檔案

**照片指紋**（PhotoFingerprint）：
由照片原檔內容算出的識別值；同樣內容的照片指紋相同，搬移或改名不會變，被其他程式改過內容就會變。
_Avoid_：照片 ID、雜湊、路徑

**編輯**（Edit）：
套在一張照片上的修改：哪個 preset（含當時的調色參數快照）、強度、微調。一張照片同時只有一份編輯；沒套 preset 也可以只有微調。
_Avoid_：修改紀錄、參數檔、設定、sidecar

**複製編輯／貼上編輯**（Copy / Paste edit）：
把一張照片的整份編輯原樣套到其他照片，取代它們原本的編輯。
_Avoid_：同步設定、批次套用

**照片資料夾**（PhotoFolder）：
使用者正在瀏覽的一個硬碟資料夾，裡面支援格式的照片依檔名排序，可以上一張／下一張、看縮圖格。
_Avoid_：專案、相簿、目錄（catalog）、圖庫

**照片庫**（PhotoLibrary）：
darkroom 記住的全部編輯，以照片指紋對到照片。存放在 App 自己的資料區，不在照片資料夾裡。
_Avoid_：目錄、catalog、資料庫

## Preset 庫

**Preset 庫**（PresetLibrary）：
所有 preset 加上一份索引；索引記錄群組、顯示名稱、最愛等整理結果，所以整理 preset 不必動到原檔。
_Avoid_：preset 資料夾、素材庫

**Preset 群組**（PresetGroup）：
Preset 庫裡的分類層級；預設對應買來時的資料夾結構，可以在索引裡改名、搬移、新增。
_Avoid_：專案資料夾、分類、資料夾

**最愛**（Favorite）：
使用者標記的 preset，記在索引裡。
_Avoid_：書籤、星號

**匯入**（Import）：
把新的 xmp 檔加進 preset 庫；複製進庫、登錄進索引，來源檔不動。
_Avoid_：安裝、載入

## 輸出

**預覽**（Preview）：
為了即時互動而縮小渲染的畫面；拖滑桿時只看最新一次。
_Avoid_：縮圖、草稿

**縮圖**（Thumbnail）：
照片資料夾縮圖格裡的小圖，只用來挑照片，不反映精確顏色。
_Avoid_：預覽

**匯出**（Export）：
用照片的最終參數，從原檔全解析度渲染，寫成一個新的**匯出檔**；不改原檔、不覆蓋任何既有檔案。
_Avoid_：儲存、輸出、另存

## 校正

**校正集**（CalibrationSet）：
在 Lightroom 裡一次只動一個滑桿、掃過多個數值所渲染出來的參考圖組。
_Avoid_：測試圖、樣本

**擬合**（Fit）：
調整 darkroom 對某個未公開滑桿的近似算法，讓結果對校正集的色差變小。
_Avoid_：訓練、校準、調參

## 入口

**入口**（Interface）：
使用者或代理操作 darkroom 的方式：Web App、CLI、MCP。不同入口做同一件事，結果與錯誤說法必須一樣。
_Avoid_：前端、API、介面層

**代理**（Agent）：
透過 CLI 或 MCP 操作 darkroom 的 AI 程式；跟人一樣受「原檔唯讀、匯出不覆蓋」約束。
_Avoid_：bot、自動化、腳本
