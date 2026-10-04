# CONTRACT — darkroom 核心函式庫（xmp → 參數 → GPU 渲染）

## 目標
`python -m darkroom apply` 能把任一支援的 Lightroom preset 依強度套到 JPEG／PNG／TIFF 並輸出新檔；`scan` 能解析使用者全部 1466 個 xmp 並明確回報不支援的版本。App 與未來 ComfyUI 節點只靠公開 API 使用它。

## 前提（Premises）
- P1 已驗（2026-10-04 掃描 1466 個 xmp）：無 BOM；1464 個數值帶正號（`"+15"`）；PV 11.0×1277、15.4×101、10.0×31、6.7×57；每個檔都同時有 `SplitToning*` 與 `ColorGrade*`；21 個 `ConvertToGrayscale="True"`；1114 個 `WhiteBalance="Custom"`、約 300 個帶絕對 `Temperature`；曲線 `<rdf:li>x, y</rdf:li>`、2～16 點；漸層只有 `Mask/Gradient`（ZeroX/ZeroY/FullX/FullY）與 `Mask/CircularGradient`（Top/Left/Bottom/Right/Angle/Midpoint/Roundness/Feather/Flipped）；40 個 `HDREditMode`；80 個 `<crs:Look>`。
- P2 已驗：執行環境 `runtimes/darkroom-python/py3.13.14-torch2.14.0-cu130/python.exe`，torch CUDA 可用（戰役 runtime 前線證據）。
- P3 未驗、不入條文：渲染結果與 Lightroom 的接近程度（留給校正集）；「強度內插」與 Lightroom Amount 的實際行為是否一致。

## 可斷言條文
- [ ] A1：`python -m unittest discover -s tests` 結束碼 0（不得依賴 pytest 等未安裝套件）。
- [ ] A2：公開 API＝`darkroom/__init__.py` 的 `__all__` 恰為 `load_preset`、`Params`、`render`、`SCHEMA_VERSION`、`UnsupportedPresetError`；`tests/` 外不得 import `darkroom._*` 或子模組私有名稱。
- [ ] A3：`scan` 對使用者 preset 資料夾輸出恰一行（見常數），值為 `1409／1466`、不支援 `57`、失敗 `0`。
- [ ] A4：PV 6.7 的 xmp 由 `load_preset` 拋 `UnsupportedPresetError`；`apply` 印錯誤行（見常數）、結束碼 2、不得產生輸出檔。
- [ ] A5：數值解析接受正號與小數（`"+15"`、`"-0.24"`、`"+0.80"`）；任何已知數值鍵解析失敗＝該 preset 解析失敗，不得默默當 0。
- [ ] A6：參數格式＝`{"schema": SCHEMA_VERSION, "values": {...}, "curves": {...}, "masks": [...], "skipped": [...]}`；`values` 的鍵是去掉 `crs:` 的 Lightroom 名稱；`Params` 轉 JSON 再讀回與原物件相等。
- [ ] A7：強度 s∈[0, 2]（CLI 的 0～200%）：數值滑桿＝`default + s × (v − default)`，預設值取自單一預設表（見常數，未列者預設 0）；色相角度鍵（`SplitToningShadowHue`、`SplitToningHighlightHue`、`ColorGrade*Hue`）不縮放；曲線點的 y＝`x + s × (y − x)` 再夾到 0～255；布林鍵（`ConvertToGrayscale`）在 s>0 時生效。
- [ ] A8：s=0 時 `render` 的浮點輸出與輸入（sRGB 0～1）逐像素最大差 ≤ 1e-4。
- [ ] A9：`Blacks2012` 正值使最暗的灰階變亮、負值變暗（測試用灰階梯，不得反向）。
- [ ] A10：陰影／亮部色調只讀 `SplitToning*`，中間調／整體只讀 `ColorGrade*Midtone*`、`ColorGrade*Global*`；同一色調不得被套用兩次。
- [ ] A11：`ConvertToGrayscale` 生效時輸出每個像素 R=G=B（差 ≤ 1e-4）。
- [ ] A12：非 RAW 輸入時絕對 `Temperature`／`Tint` 不套用、列入 `skipped`；只用 `IncrementalTemperature`／`IncrementalTint`。
- [ ] A13：`<crs:Look>`、`HDREditMode`、不認得的遮罩種類都列入 `skipped`，`apply` 印略過行；不得默默丟棄。
- [ ] A14：線性與放射狀漸層依 xmp 幾何（座標為 0～1 的相對值、`MaskInverted`、`Flipped`）產生 0～1 的遮罩，只在遮罩內套該組局部調整。
- [ ] A15：`load_preset` 與 `scan` 只以唯讀模式開檔；跑完全部測試與 `scan` 後 preset 資料夾合併雜湊仍為 `15C015CC0C080FF9`。
- [ ] A16：`apply` 的輸出路徑等於輸入路徑、或已存在且沒帶 `--overwrite` 時，印錯誤行、結束碼 2、不寫檔。
- [ ] A17：在 CUDA 上對 1.5MP 圖跑完整全域管線，熱機後 20 次的中位數 ≤ 25 ms；無 CUDA 時自動用 CPU 且結果與 CUDA 差 ≤ 1e-3。
- [ ] A18：色彩管線：sRGB → 線性光工作空間 → sRGB 的往返，對色域內顏色最大差 ≤ 1e-4。

## 錯不起表面（Surface Inventory）
| 表面 | 格式 | 影響（資產 → 後果｜類別） | 釘死測試 |
|------|------|--------------------------|----------|
| 參數 JSON（A6） | 見 A6 | App、preset 庫、② AI、未來 ComfyUI 節點 → 格式一變，使用者存的自訂 preset 與 AI 建議全部讀不回來｜上下游契約 | `test_params_json_roundtrip_and_schema` |
| preset 原檔（A15） | 唯讀 | 使用者買的 1466 個 preset → 被寫壞就無法復原｜不可逆／資料 | `test_presets_untouched_hash` |
| 使用者照片（A16） | 不覆寫 | 使用者照片原檔 → 被輸出蓋掉就沒了｜不可逆／資料 | `test_apply_refuses_overwrite` |
| 強度縮放（A7） | 見 A7 與預設表 | 每個 preset 的非 100% 效果 → 預設值錯就整批偏掉｜邏輯核心 | `test_strength_interpolates_from_defaults` |
| 色調與方向（A9～A12） | 見條文 | preset 的觀感 → 黑色反向、色調重複、黑白失效就跟原意相反｜邏輯核心 | `test_blacks_direction`、`test_split_vs_colorgrade_once`、`test_grayscale_equal_channels`、`test_absolute_wb_skipped_non_raw` |
| CLI 成功／略過／錯誤行（A3、A4、A13、A16） | 見常數 | 使用者 → 不知道哪些設定沒套到、為什麼失敗｜UI/UX | `test_cli_messages_exact` |

## Verbatim Constants
```text
SCHEMA_VERSION = "darkroom-params/1"
apply 成功：已套用：{preset_name}（強度 {strength}%）→ {output_path}
apply 略過：略過：{skipped_items_joined_by_、}
scan 摘要：已解析 {ok}／{total}，不支援 {unsupported}（ProcessVersion 6.7），失敗 {failed}
錯誤（版本）：不支援的 preset 版本：ProcessVersion {pv}（{file_name}）
錯誤（覆寫）：輸出檔已存在或與輸入相同：{output_path}（要覆寫請加 --overwrite）
CLI：python -m darkroom apply --preset <xmp> [--strength 0..200] [--overwrite] <input> <output>
CLI：python -m darkroom scan <preset_dir>
預設表（未列者為 0）：SharpenRadius 1.0、SharpenDetail 25、SharpenEdgeMasking 0、LuminanceNoiseReductionDetail 50、
  LuminanceNoiseReductionContrast 0、ColorNoiseReduction 25、ColorNoiseReductionDetail 50、ColorNoiseReductionSmoothness 50、
  GrainSize 25、GrainFrequency 50、PostCropVignetteMidpoint 50、PostCropVignetteFeather 50、PostCropVignetteRoundness 0、
  PostCropVignetteStyle 1、PostCropVignetteHighlightContrast 0、ParametricShadowSplit 25、ParametricMidtoneSplit 50、
  ParametricHighlightSplit 75、ColorGradeBlending 50、SplitToningBalance 0
```
