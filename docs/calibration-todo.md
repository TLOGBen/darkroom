# 校正待辦：未校正的初值（合約 P3）

`darkroom/_render.py` 目前所有數值對應都是**沒有對 Lightroom 校正過的初值**，只保證方向對、大小合理。等校正集（單一滑桿掃描，見 `.claude/wayfinder/darkroom/issues/14-calibration-set.md`）渲染出來後，逐項擬合。調校優先順序照研究 03：**亮部、陰影、白、黑**先。

## 執行者暫定的語意（要用校正集確認）

| 項目 | 暫定 | 位置 |
|---|---|---|
| 放射漸層 `Flipped` | `true`＝效果在橢圓**內**，`false`＝在橢圓外；`MaskInverted` 再反轉一次 | `_shape_mask` |
| `LocalExposure2012` | xmp 值 ±1＝±4 EV（範圍表照合約夾在 ±4，等於最多 ±16 EV，實際 preset 只出現 -0.15～0.25） | `_LOCAL_MAP` |
| 其他 `Local*` | xmp 值 ±1＝對應全域滑桿 ±100 | `_LOCAL_MAP` |
| 放射漸層的 `Midpoint`、`Roundness` | 解析但不使用；羽化只用 `Feather`（內緣＝1−Feather/100，smoothstep 過渡） | `_shape_mask` |
| 線性漸層 | Zero→Full 之間線性 0→1 | `_shape_mask` |

## 未校正的數值初值

| 設定 | 目前做法與常數 | 位置 |
|---|---|---|
| `IncrementalTemperature`／`Tint` | 線性光增益 R 2^(0.45T)、G 2^(−0.30Ti)、B 2^(−0.55T)（T、Ti 為 ±1），再正規化亮度 | `_linear_stage` |
| 相機校正 `Red/Green/BlueHue`、`…Saturation` | 3×3 矩陣：色相每 ±100 往相鄰原色借 0.25、飽和度 ×(1+0.5s)，列和正規化成 1 | `_calibration_matrix` |
| `ShadowTint` | G 通道 ×2^(−0.25·st·(1−Y)³) | `_linear_stage` |
| `Exposure2012` | 線性光 ×2^EV；正 EV 在最大通道套肩部（膝點 0.8、tanh）；負 EV 沒有做 DNG SDK 的白點保留 | `_linear_stage` |
| `Dehaze` | 暗通道（視窗＝長邊 1%）、大氣光取最亮 0.1%、ω＝0.9·d、t 下限 0.15、guided filter（半徑長邊 4%）、亮度／每通道各半 | `_dehaze` |
| `Highlights2012`／`Shadows2012` | guided filter 基底（半徑長邊 1/24、eps 1e-2）；亮部 0.30·hl·smoothstep(0.45,1)、陰影 0.35·sh·(1−smoothstep(0,0.55))·(1−B)·B^0.35；沒有依直方圖自適應 | `_tone` |
| `Contrast2012` | Y + c·k·Y(1−Y)(2Y−1)，k＝0.9（正）／0.8（負） | `_tone` |
| `Whites2012` | Y + 0.18·wh·Y⁴；沒有依百分位自適應 | `_tone` |
| `Blacks2012` | Y + 0.12·bl·(1−Y)⁴（正，抬黑）／0.10（負）；+100 最多抬到約 0.12——**抬黑量是霧面感的關鍵，優先校** | `_tone` |
| `Clarity2012` | 快速 local Laplacian（K＝8、σ＝0.2）、α＝1−0.6c（正）／1+0.8\|c\|（負）、中間調權重 (4Y(1−Y))^0.7 | `_tone`、`_fast_llf` |
| `Texture` | 金字塔第 1、2 層（大圖第 2、3 層）增益 1+t（正）／1−0.8\|t\|（負），coring 門檻＝平均絕對值×1.2533 | `_texture` |
| 亮度套回 RGB | 比例法，比例上限 2，超出部分加灰 | `_tone` |
| 參數曲線 `Parametric*` | 四區 sin² 凸塊，幅度 0.15·a/100，峰值在分割點的中點 | `_parametric` |
| 點曲線 | 單調三次（Fritsch–Carlson）；Lightroom 實際用的插值不明 | `_pchip` |
| `Vibrance`／`Saturation` | 以亮度為軸放大色度：(1+S)·(1+V·(1−飽和度))；沒有膚色保護 | `_color_ops` |
| HSL | 色相 ±100＝±30°；明度 v·(1+0.35·l·s)；色帶中心 0/30/60/120/180/240/270/300° 線性內插 | `_color_ops`、`_hue_interp` |
| 顏色分級／分離色調 | 色調強度 0.35·sat/100（加色度、保亮度）；區界 c＝0.5−0.2·Balance、寬度 0.1+0.4·Blending；亮度項 0.2·lum/100 | `_zone_weights`、`_apply_tint`、`_color_grade` |
| 黑白 `GrayMixer*` | Y·(1+0.6·mix(h)·s)；先轉黑白再套顏色分級 | `_grayscale` |
| 暗角 `PostCropVignette*` | 起點 0.4+0.8·Midpoint、過渡 0.05+0.6·Feather、強度 0.9·a；Roundness 只處理正值；Style、HighlightContrast 未用 | `_vignette` |
| 顆粒 `Grain*` | 固定種子雜訊、模糊 σ＝0.3+1.5·Size/100（依長邊放大）、強度 0.12·a、中間調權重；`GrainFrequency`（粗糙度）未用 | `_grain` |
| 銳利化 `Sharpness` | 亮度 unsharp，強度 Sharpness/150、半徑 `SharpenRadius`；Detail、EdgeMasking 未用 | `_sharpen` |

## 沒有渲染、會列入 skipped 的設定

降噪（`LuminanceSmoothing`、`ColorNoiseReduction`）、鏡頭與透視校正、去紫邊、Point Color（`PointColors`／`ColorVariance`）、`<crs:Look>`、`HDREditMode`、非中性的 `CameraProfile`、`CorrectionRangeMask`、絕對 `Temperature`／`Tint`（非 RAW）、不認得的遮罩種類、超出範圍表而被夾值的鍵。
