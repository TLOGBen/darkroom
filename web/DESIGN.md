# darkroom 設計系統（web/）

這份是新 React＋MUI 前端的設計依據。數值的真正來源是兩支檔，兩邊同名同值：

| 檔 | 給誰用 |
|---|---|
| `src/styles/theme.ts` | MUI 主題：`tokens` 物件、深淺兩套 palette、typography、元件覆寫 |
| `src/styles/_tokens.scss` | CSS module 用的 Sass 變數、mixin；`dr-custom-properties` 產生全部 `--dr-*` |
| `src/styles/global.scss` | 只 import 一次：輸出 `--dr-*`、reset、捲軸、焦點、照片底色、減少動態 |

改顏色或尺寸時兩支檔一起改。舊介面（`darkroom_app/static/app.css`）的色票與滑桿規則已經封緘過（`CONTRACT-s1-experience` S16、S17），這裡全部沿用，只是換成 MUI 的寫法並補上淺色主題。

## 1. 這個介面在做什麼

使用者坐在螢幕前判斷一張照片的顏色：膚色是不是太紅、天空是不是太青。介面上任何一點顏色都會干擾這個判斷。所以整個設計只有一個立場：

> **介面是一間暗房：牆是中性灰，唯一的光從照片來。**

由這句話推出五條原則：

1. **介面無彩。** 所有介面灰階都是 R = G = B，不帶冷暖。MUI 深色模式預設會依 elevation 疊白色漸層，已經關掉（`MuiPaper` 的 `backgroundImage: none`）。
2. **顏色只代表狀態，而且只出現在小地方。** 四個低彩度語意色只畫在 1～2px 的線、6px 的點、文字上，不塗大面積：
   - 琥珀 `tweak`：你的微調（滑桿差值段、已微調的點、「未儲存」）。
   - 紅 `clamp`：數值被夾住，preset 要的值超出範圍。
   - `err`／`ok`：錯誤與成功。
3. **選取用白，不用藍。** 目前的 preset、按下去的切換鈕、選取的縮圖，一律是「選取色」：深色主題白底黑字，淺色主題反過來。介面裡沒有「強調藍」。
4. **力氣只花在一個地方：滑桿。** 滑桿是使用者一直盯著、一直拖的東西，它要把「preset 放在哪、你改了多少、有沒有被夾住」一眼講清楚。其他元件都安靜、平、細。
5. **動效只回應操作。** 沒有進場動畫、沒有漣漪。預覽圖本身永遠沒有 transition，拖滑桿時畫面要跟手。

暗房紅（logo 的顯影液紅 `#c0392b`）是品牌色，只出現在 logo、README banner、Tauri 第一次啟動的 bootstrap 頁；編輯器、設定頁裡一律不用。

## 2. 色票

### 2.1 深色（預設）

四層灰由暗到亮＝外框 → 面板 → 控制項 → 滑過。對比是在 `bg-panel` 上量的 WCAG 對比值。

| token（CSS／TS） | 值 | 用途 | 對比 |
|---|---|---|---|
| `--dr-bg-frame`／`bgFrame` | `#121212` | 頂列、App 底 | |
| `--dr-bg-panel`／`bgPanel` | `#191919` | 左右欄、對話框 | |
| `--dr-bg-control`／`bgControl` | `#202020` | 按鈕、選單、提示 | |
| `--dr-bg-hover`／`bgHover` | `#2a2a2a` | 滑過 | |
| `--dr-bg-well`／`bgWell` | `#121212` | 輸入框（凹下去的井） | |
| `--dr-line` | `rgba(255,255,255,.07)` | 欄與欄、區塊間細線 | |
| `--dr-line-strong` | `rgba(255,255,255,.12)` | 控制項外框 | |
| `--dr-text` | `#e6e6e6` | 內文 | 14.1:1 |
| `--dr-text-2` | `#a9a9a9` | 標籤、次要說明 | 7.5:1 |
| `--dr-text-3` | `#8a8a8a` | 計數、提示、佔位字 | 5.1:1（`bg-control` 上 4.7:1） |
| `--dr-select-bg`／`--dr-select-fg` | `#e6e6e6`／`#141414` | 選取、主要動作 | 14.8:1 |
| `--dr-select-soft` | `rgba(255,255,255,.07)` | preset 樹的目前列底 | |
| `--dr-focus` | `#e6e6e6` | 鍵盤焦點框 | |
| `--dr-track`／`--dr-track-2` | `#3a3a3a`／`#4a4a4a` | 滑桿軌道／雙向中點、強度 >100% 半段 | |
| `--dr-thumb` | `#ececec` | 滑桿把手 | 14.9:1 |
| `--dr-tweak` | `#d9a85b` | 微調 | 8.1:1 |
| `--dr-clamp` | `#d27a7a` | 夾值 | 5.7:1 |
| `--dr-err`／`--dr-on-err` | `#e06b6b`／`#141414` | 錯誤／紅底上的字 | 5.4:1／5.6:1 |
| `--dr-ok` | `#8fbf93` | 成功 | 8.4:1 |
| `--dr-tweak-soft` | `rgba(217,168,91,.12)` | 「preset 有設定套不上」警告條底 | |
| `--dr-scrim` | `rgba(0,0,0,.55)` | 對話框背幕、裁切框外 | |
| `--dr-overlay` | `rgba(18,18,18,.78)` | 疊在照片上的小標籤（A／B、原圖） | |

### 2.2 淺色

給白天、明亮環境。結構相同，只是亮度反過來；滑過是「變暗」，選取是黑底白字。語意色加深，才在淺底上過 4.5:1。

| token | 值 | 對比（`bg-panel` 上） |
|---|---|---|
| `bg-frame`／`bg-panel`／`bg-control`／`bg-hover`／`bg-well` | `#dedede`／`#ebebeb`／`#f5f5f5`／`#d9d9d9`／`#ffffff` | |
| `line`／`line-strong` | `rgba(0,0,0,.08)`／`rgba(0,0,0,.16)` | |
| `text`／`text-2`／`text-3` | `#1c1c1c`／`#4d4d4d`／`#5f5f5f` | 14.3／7.1／5.4（`text-3` 在 `bg-frame` 上 4.8） |
| `select-bg`／`select-fg` | `#1c1c1c`／`#ffffff` | |
| `track`／`track-2`／`thumb` | `#c2c2c2`／`#a3a3a3`／`#262626` | 把手 12.7 |
| `tweak`／`clamp` | `#8a5a12`／`#a83e3e` | 5.0／5.2 |
| `err`／`on-err`／`ok` | `#b3261e`／`#ffffff`／`#2f6b35` | 5.5／6.5／5.4 |

`overlay` 在淺色主題仍然是深色：它疊在照片上，照片不分主題。

### 2.3 不分主題的顏色

- **照片底色**（`--dr-canvas`）：`dark #151515`、`black #000000`、`mid #4a4a4a` 三段，由 `<html data-canvas="dark|black|mid">` 切換，記在 `localStorage` 鍵 `darkroom.canvas`（跟舊版同一個鍵，升級後使用者的選擇還在）。這是「看照片用的」設定，不跟主題走：淺色主題也可以用黑底看照片。
- **HSL 色相點**（`--dr-hue-red` … `--dr-hue-magenta`，TS `tokens.color.hue.Red` …）：只畫在 HSL 列標籤前的 6px 圓點，告訴你這列調的是哪個顏色；不上軌道、不當背景。
- **曲線通道色**：RGB 曲線的紅綠藍線是資料本身（舊版 `#ff6060`／`#60d060`／`#6090ff`），只用在曲線圖裡。

### 2.4 主題怎麼切

- MUI：`cssVariables.colorSchemeSelector = '[data-theme="%s"]'`、`defaultColorScheme: 'dark'`。`<ThemeProvider theme={theme} defaultMode="dark">`；在 `index.html` 放 `InitColorSchemeScript`（`attribute="data-theme"`、`defaultMode="dark"`）避免載入時閃白。
- `--dr-*`：`:root` 與 `:root[data-theme='dark']` 是深色，`:root[data-theme='light']` 是淺色，跟 MUI 用同一個屬性，所以兩邊永遠同步。
- 元件覆寫裡的顏色全部寫 `var(--dr-*)`，切主題不用重新產生樣式。**前提：`main.tsx` 一定要 import `./styles/global.scss`**，不然覆寫拿不到變數。不要再加 `<CssBaseline />`（global.scss 已經做了它的事，兩邊會打架）。

## 3. 字體

不從網路載字型：darkroom 是本機 App，離線要長得一樣，也不該為了字型連外。全部用平台內建字型。

| 角色 | 字型堆疊 | 用在 |
|---|---|---|
| 介面 `--dr-font-ui` | Segoe UI Variable Text → Segoe UI → Noto Sans TC → Microsoft JhengHei UI → Noto Sans CJK TC → PingFang TC → system-ui | 所有文字。拉丁字母落在 Segoe UI，中文落在微軟正黑／Noto Sans TC |
| 數字 `--dr-font-num` | **Bahnschrift**（窄體 `font-stretch: 87.5%`）→ DIN Alternate → Segoe UI Variable Small | 會變動的數字：滑桿數值、強度讀數、照片尺寸、計數、刻度 |
| 等寬 `--dr-font-mono` | Cascadia Mono → Consolas → DejaVu Sans Mono | 檔案路徑、xmp 鍵名（`SharpenEdgeMasking`）、設定檔位置 |

Bahnschrift 是 Windows 內建的 DIN 系可變字型；窄體數字像放大機計時器的讀數，是這套介面在字上唯一的個性。所有數字一律 `font-variant-numeric: tabular-nums`（每個數字一樣寬），拖滑桿時數值不會左右跳。等寬字只給「真的是路徑或程式識別字」的東西，不拿來裝飾小標籤。

**字級**（px，介面基準 13，密集工具）：

| 名稱 | 大小／粗細 | MUI variant | 用在 |
|---|---|---|---|
| xs | 11 | `caption`、`overline` | 計數、刻度數字、縮圖檔名 |
| sm | 12 | `body2`、`num` | 滑桿標籤與數值、狀態列、說明、表單標籤 |
| md | 13 | `body1`、`button`、`h3`～`h6`、`subtitle1`（600） | 內文、按鈕、preset 樹、分區標題 |
| lg | 15／600 | `h2` | 對話框標題、設定頁區塊標題 |
| xl | 20／600 | `h1` | 設定頁頁名（整個 App 唯一的頁標題） |
| readout | 22／350 窄體 | `readout` | 強度讀數，整個介面唯一的大數字 |

規則：不用全大寫（`overline` 已改成一般小字）；不在標題上方加小標籤；強調靠粗細（600），不靠換色；中文不加字距。說明段落行高 1.6、一行不超過約 40 個中文字（`max-width: 40em`）。

## 4. 間距、尺寸、圓角

**間距**：4px 格，`theme.spacing(n) = 4n`（MUI 預設是 8，這裡改成 4）。Sass：`dr-space(2)` ＝ 8px；CSS：`var(--dr-space-2)`。2、6、10px 是密集列需要的半格（`0_5`、`1_5`、`2_5`）。

**固定尺寸**：

| token | 值 | 是什麼 |
|---|---|---|
| `control-h` | 26 | 按鈕、輸入框、下拉 |
| `row-h` | 24 | preset 樹列、滑桿列 |
| `section-h` | 34 | 右欄分區標題列 |
| `bar-h` | 44 | 頂列 |
| `toolbar-h` | 38 | 預覽工具列、縮圖格工具列（固定一行高，不換行） |
| `lib-w`／`sl-w` | 280／390（≤1280：230／340；≤960：左欄變抽屜、右欄 290） | 左欄 preset 庫、右欄滑桿 |

**圓角依層級**：越大、越浮在上面的東西圓角越大；不是一個值套全部。

| token | 值 | 用在 |
|---|---|---|
| `radius-xs` | 2 | 強度把手、夾值方把手 |
| `radius-sm` | 3 | 縮圖、照片上的小標籤、提示 |
| `radius-md` | 5 | 按鈕、輸入框（`shape.borderRadius`） |
| `radius-lg` | 8 | 選單、彈出框、對話框 |
| 圓 | 50% | 狀態點、色相點、一般滑桿把手 |

照片預覽本身沒有圓角，只有 1px 深色描邊（`0 0 0 1px rgba(0,0,0,.35)`），像相紙的邊。

**影子**：面板是平的，用 1px 細線分隔。只有浮在上面的東西有影子：選單／提示 `--dr-shadow-float`、對話框 `--dr-shadow-dialog`。卡片不加影子。

## 5. 版面

三欄編輯器，照片在正中間、佔最大面積；兩側欄可以收起。

```
┌────────────────────────────────────────────────────────────────────────────┐ 44 頂列：開啟｜上一張 位置 下一張｜復原 重做｜…｜狀態●
├──────────────┬──────────────────────────────────────────┬──────────────────┤
│ 搜尋 preset   │ 預覽工具列（38，固定一行）                    │ ▸ 基本      ●2   │
│ ▾ 人物 31     ├──────────────────────────────────────────┤   色溫  ──●───  +5 │
│   ▾ 女人 6    │                                          │   曝光  ──┃━●── +1.00│
│ ▌ Beauty 01  │               照 片（canvas 底）             │ ▸ 曲線            │
│   Beauty 02  │                                          │ ▸ HSL             │
│ ▸ 器材 157    │                                          │ ▸ 細節            │
│              ├──────────────────────────────────────────┤                  │
│ 280          │ 目前 preset  Beauty 01            強度 140%│ 390              │
└──────────────┴──────────────────────────────────────────┴──────────────────┘
```

- 對齊：一律靠左；數字靠右（同一欄的數值右緣對齊）。
- 頂列以間距分組（開啟／瀏覽／歷史），不畫分隔線。
- 縮圖格是第二個畫面，取代編輯器的三欄，頂列不變。
- 設定頁（`SettingsPage`）是單欄表單，左對齊、最寬 720px，見 6.7。
- 窄視窗（≤960，最小要撐住 820×600）：preset 欄收成蓋在預覽上的抽屜；按鈕只剩圖示但**不藏**（文字移到 tooltip 與 `aria-label`）；強度滑桿 ≥ 200px、預覽 ≥ 400px（舊合約 R6／S18）。

## 6. 元件規則

### 6.1 滑桿（`MuiSlider`，整個設計唯一花力氣的地方）

```
 曝光   ─────────┃━━━━━━●───────────   +1.00 ↺
             preset 落點  你的微調（琥珀）  把手
```

- 2px 軌道（`track`）、10px 圓形中性把手（`thumb`）、1px 黑邊。滑過／按住放大 1.25 倍（只動 transform，120ms）。
- 不用 MUI 的 track（從最小值長出來的那條）：`defaultProps.track = false`，改由三個 CSS 變數畫，元件用 `style` 寫在 Slider 上：
  - `--dr-base`：preset×強度落在哪 → 1px×8px 灰刻度。
  - `--dr-lo`～`--dr-hi`：從 preset 落點到把手 → 琥珀色段＝你的微調。
  - 三個值都是 0%～100%，由 `domain/edit` 的 `sliderVars` 算（從舊 `logic.js` 同名函式移植，單元測試照搬）。
- 狀態用 className，由元件依資料加：
  - `dr-bipolar`：最小值 <0< 最大值，畫中點刻度。
  - `dr-adjusted`：有微調，把手變琥珀；標籤前加 4px 琥珀點、數值變琥珀、出現 ↺ 重設鈕。
  - `dr-clamped`＋`dr-at-min`／`dr-at-max`：被夾住，把手變方形灰、該端加端蓋，數值用 `clamp` 色並註明原值（例：`-90（原 -112.5）`）。
  - `dr-strength`：強度轉盤（見下）。
- 列的版面：`標籤 84px｜滑桿｜數值 96px｜重設 18px`，列高 24px，數值用 `num` 變體靠右。
- 數值可以點兩下直接輸入（`TextField` 數字欄，靠右、`num` 字型）；Enter 確認、Esc 取消。
- 鍵盤：方向鍵一步、PageUp／PageDown 十步、Home／End 到兩端（MUI 內建）；焦點時把手外加 2px `focus` 圈。
- HSL 列：標籤前 6px 色相點（`--dr-hue-*`），軌道仍然是灰的。

**強度轉盤**（`className="dr-strength"`，0～200%）：

- 較高的點擊區（36px）、12×14 圓角 2 的把手。
- 軌道左半 `track`、右半 `track-2`（超過 100% 那半比較亮，提示「誇張區」）；0～目前值那段用 `text-2`，不用琥珀（強度不是微調）。
- `marks=[0,100,200]` 帶數字標籤；第二個 mark（100%）畫成 22px 長刻度；每 25% 的小刻度由元件自己的 CSS module 畫。
- 讀數用 `readout` 變體（22px 窄體），`%` 小一號用 `text-2`；旁邊一顆「100%」快速重設。

### 6.2 面板與分區

- 左右欄是 `bg-panel`，跟預覽之間一條 `line`。沒有卡片、沒有影子。
- 右欄分區用 `Accordion`（已覆寫成平的）：標題是一行 600 字＋底下一條細線；展開箭頭在左邊（跟 preset 樹同側），用向右的箭頭圖示、展開時轉 90°。分區有微調時在右端顯示琥珀點＋「微調 N 項」。
- preset 樹：24px 列，資料夾 `text`、preset `text-2`；目前的 preset ＝ `select-soft` 底＋左緣 2px `select-bg`＋白字。最愛星號與「⋯」選單平常 35% 透明，滑過或鍵盤焦點才全亮（不靠 media query，觸控也看得到）；已最愛的星是琥珀。套不上的設定：major 用琥珀 ⚠，minor 用 `text-3`。

### 6.3 工具列與按鈕

- 一種按鈕（`outlined`）：灰底細框，26px 高。輕重靠亮度，不靠色相。
- 主要動作（`variant="contained"`）＝選取色實心，**一個畫面最多一顆**（匯出對話框的「匯出」、設定頁的「儲存」）。
- 安靜鈕（`variant="text"`）：沒底沒框，滑過才浮出；用在列內的小動作。
- 切換鈕（A/B、裁切、縮圖格）用 `aria-pressed`；按下＝選取色，跟「目前的 preset」是同一個視覺語言。
- 分段選擇（照片底色、裁切比例）用 `ToggleButtonGroup`；HSL 的「色相／飽和度／明度」用 `<Tabs className="dr-segmented">`。
- 圖示：15px、1.6 線寬、圓頭（舊版同款線條圖示）。純圖示按鈕一定有 `aria-label`＋tooltip。
- 不要在按鈕文字後面加箭頭；按鈕寫「會發生什麼」：「匯出 3 張」，不是「確定」。
- 預覽工具列固定一行 38px，不換行；左邊是看圖的工具（原圖、A/B、裁切），右邊是輸出資訊（尺寸）；放不下時文字縮成省略號，按鈕不藏。

### 6.4 對話框（`MuiDialog`）

- 置中、寬 560（`maxWidth="sm"` 已改成 560）、圓角 8、`shadow-dialog`，背幕 `scrim`。內容自己捲，820×600 的視窗也要每個控制項都碰得到。
- 標題 15/600，旁邊可接一行 `text-2` 小字（例如「3 張照片」）。
- 表單列：`標籤 96px｜控制項`，最少 36px 高。
- 底部 `DialogActions`：細線隔開、靠右，取消在左、主要動作在右。
- 危險動作（刪除匯出預設、清除多張編輯）用 `variant="contained" color="error"`，文字寫清楚刪什麼，且旁邊說明怎麼復原（「刪掉後可以再存一次」）。
- 進場 180ms 淡入、離場 120ms；`Esc` 關閉、焦點鎖在對話框裡、關閉後焦點回到開它的按鈕（MUI 內建，不要關掉）。

### 6.5 縮圖格

- 底色是目前的照片底（`--dr-canvas`），不是面板灰：縮圖是照片，要跟大圖在同一個環境裡看。
- `auto-fill, minmax(176px, 1fr)`、間距 14px；縮圖框高 124px，圖 `object-fit: contain`，圓角 3，平常 1px 6% 白描邊。
- 滑過：描邊 25% 白；鍵盤焦點與選取：2px `select-bg` 框。檔名 11px `text-2`，單行省略。
- 有編輯：右下 8px 琥珀實心點；編輯的 preset 已改或不見：琥珀空心圈。
- 縮圖還沒產好：同尺寸的空框（不放轉圈動畫），產好直接換上，不淡入。

### 6.6 回饋：狀態列、toast、警告條

- 狀態列（頂列最右）：6px 點＋一行字。閒置點 `track-2`、忙碌點 `text`、錯誤點與字 `clamp`。毫秒數放在 title，不佔版面。
- toast：底部置中、反轉色（`select-bg`／`select-fg`）、12px；錯誤是 `err` 底 `on-err` 字。可以帶一顆動作鈕（例如「復原」）。動作的名字從頭到尾一致：按「儲存為 preset」→ toast「已儲存為 preset」。
- 「這個 preset 有 N 項設定套不上」：預覽工具列裡一條 `tweak-soft` 底的琥珀字，點一下在預覽上方展開全文。
- 錯誤句子照後端原句顯示（規劃 §2：v2 不翻後端句子），說明發生什麼與怎麼修，不道歉。

### 6.7 設定頁表單

- 單欄、左對齊、最寬 720px，頁名用 `h1`。分區（資料夾、ComfyUI、AI 代理、語言與外觀）用 `h2`＋細線，不用卡片。
- 每列：`標籤（160px，text-2 12px）｜控制項｜來源`。標籤寫在框外（`FormLabel`），**不用 MUI 的浮動標籤**；說明用 `FormHelperText`（`text-3`），錯誤時變 `err` 並寫出原句。
- 路徑欄位用 `mono` 字型。
- 來源（`GET /api/settings` 的 `sources`）：每個值旁邊一行小字「來自設定檔」「來自環境變數」「預設值」；來自環境變數的欄位唯讀並說明原因。
- 金鑰：只接受 1Password 參照（`op://…`），欄位旁明寫「這裡不存金鑰本身」。永遠不顯示金鑰值。
- 儲存：一顆主要按鈕「儲存設定」，全部驗證通過才寫；儲存後每個重測項目（`checks`：comfyui、agent_sdk…）在該列下方顯示 `ok` 點＋「可以連線」或 `err` 點＋原因。
- 匯出／匯入設定是安靜鈕，放在頁面底部；匯入前先顯示會改哪些鍵。

## 7. 動效

| 情境 | 時間 | 說明 |
|---|---|---|
| 滑過、按下、展開箭頭轉向、把手放大 | 120ms `cubic-bezier(.2,0,0,1)` | 回應操作 |
| 對話框、抽屜、選單進場 | 180ms；離場 120ms | 只淡入／滑出，不彈跳 |
| 預覽圖、縮圖 | **無** | 新的一張直接換上，拖滑桿時要跟手 |
| 載入中 | 2px `LinearProgress`（灰） | 不用轉圈、不用骨架閃爍 |

不做：進場時各區塊依序淡入、卡片滑過浮起、漣漪（已全域 `disableRipple`）。`prefers-reduced-motion: reduce` 時 global.scss 把所有 transition／animation 關掉。

## 8. 無障礙

- **對比**：內文與標籤 ≥ 4.5:1（見第 2 節的表，最低的是 `text-3` 在 `bg-control` 上 4.7:1）；語意色當文字用時也都 ≥ 4.5:1。軌道本身對比低是刻意的（不搶照片），位置由把手（≥ 12:1）表達。
- **鍵盤焦點**：只在鍵盤操作時出現（`:focus-visible`／`.Mui-focusVisible`），全站同一個 2px `focus` 框，偏移 1px；在列表與分區標題裡往內縮（`outline-offset: -2px`）免得被裁掉。不准 `outline: none` 而不補別的焦點樣式。
- **不只靠顏色**：微調除了琥珀還有點與 ↺ 鈕；夾值除了紅還有方形把手與「原 …」文字；套不上的設定有 ⚠ 與文字。
- 所有只有圖示的按鈕有 `aria-label`；切換鈕用 `aria-pressed`；分區標題用 `aria-expanded`（Accordion 內建）。
- 滑桿的 `aria-valuetext` 要帶單位與狀態（例：「曝光 +1.00，已微調」）。
- Windows 高對比模式（`forced-colors: active`）：焦點框改用系統 `Highlight`。
- 字級最小 10px（只有強度刻度數字），一般資訊最小 11px。

## 9. Do／Don't

| Do | Don't |
|---|---|
| 介面灰一律 R = G = B | 用帶冷暖的灰（`#1e1f22` 這種藍灰）或 MUI 預設的深色漸層 |
| 選取用 `select-bg`（白／黑） | 用藍色、或任何色相表示選取 |
| 語意色只畫在線、點、字 | 用琥珀或紅塗整塊背景（警告條只有 12% 透明底） |
| 一個畫面最多一顆主要按鈕 | 每個對話框底部兩顆實心鈕 |
| 數字用 `num`／`readout`，等寬、靠右 | 數字用比例字、置中 |
| 標籤寫在輸入框外 | MUI 浮動標籤、全大寫小標、標題上方的小標籤 |
| 面板用細線分隔 | 卡片＋影子＋統一圓角的「SaaS 卡片組」 |
| 動效回應操作，120／180ms | 進場動畫、漣漪、預覽圖淡入 |
| 顏色寫 `var(--dr-*)`、尺寸用 token | 在元件裡寫死色碼（`#e6e6e6`）或 `theme.palette.*` 以外的新顏色 |
| 暗房紅只在 logo 與歡迎頁 | 拿品牌紅當強調色、按鈕色 |
| 窄視窗把按鈕縮成圖示 | 窄視窗把按鈕藏起來 |

## 10. 在程式裡怎麼用

```tsx
// main.tsx
import './styles/global.scss';
import { ThemeProvider } from '@mui/material';
import theme from './styles/theme';

<ThemeProvider theme={theme} defaultMode="dark">…</ThemeProvider>
```

```tsx
// 一般滑桿：三個變數＋狀態 className
<Slider
  className={clsx(bipolar && 'dr-bipolar', adjusted && 'dr-adjusted', clamped && ['dr-clamped', atMax ? 'dr-at-max' : 'dr-at-min'])}
  style={{ '--dr-base': vars.base, '--dr-lo': vars.lo, '--dr-hi': vars.hi } as React.CSSProperties}
  aria-label={t('sliders.Exposure2012')}
  …
/>
<Typography variant="num">{formatted}</Typography>
```

```scss
// 某個 CSS module
@use '../../styles/tokens' as *;

.cells {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(176px, 1fr));
  gap: 14px;
  padding: dr-space(3);
  background: var(--dr-canvas);

  @include dr-below($dr-bp-narrow) {
    gap: dr-space(2);
  }
}

.value {
  @include dr-num;
  color: var(--dr-text);
}
```

`_tokens.scss` 只有變數、函式與 mixin，`@use` 它不會多輸出任何 CSS；`--dr-*` 由 global.scss 輸出一次。
