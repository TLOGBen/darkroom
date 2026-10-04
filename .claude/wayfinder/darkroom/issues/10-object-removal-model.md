# ③ 去雜物、去路人用什麼？

Type: research
Status: resolved

## Question

候選：萬事通現有的 Qwen-Image 修圖（提示詞「移除 ⋯」，會不會動到其他地方？）、專門的補圖模型（LaMa、Flux Fill 之類）。查：各自的效果特性、VRAM、ComfyUI 節點、授權；怎麼讓使用者指定要移除的東西（框選、點選、文字描述＋分割）。

## Answer

（2026-10-04，研究子代理；詳見 [research/10-object-removal-model.md](../research/10-object-removal-model.md)。主 session 抽查屬實：`comfy_extras/nodes_sam3.py` 有 `SAM3_Detect`；`TextEncodeQwenImage21` 的 latent 輸出在原始碼註明是 Empty latent。）

- **只用提示詞叫 Qwen-Image 2.1 移除，保證不了遮罩外不變**：它整張重畫，社群實測對齊後仍有約 2.6% 像素被改，臉與配色會漂。萬事通目前沒有任何保留遮罩外內容的機制（latent 是空的）；`resolution=0` 仍會把長寬捨入到 32 的倍數。
- **指定要移除的東西**：用 ComfyUI 0.38 核心內建的 `SAM3_Detect`（文字、框、正負點都吃），不用另裝 Florence-2／GroundingDINO／SAM2；要下載 `sam3.1_multiplex_fp16.safetensors`（約 1.75GB）。點選、框選模式本機還沒實測；影子、倒影要靠擴張遮罩或手動補塗。
- **推薦流程**：SAM3 指定 → 擴張遮罩 → Inpaint Crop → 補圖 → 貼回原圖（`ImageCompositeMasked` 或 Inpaint Stitch），並自動檢查遮罩外跟原圖差值為 0。**保證不動原圖靠最後的程式合成**，模型只負責遮罩內那一塊（符合「AI 重畫內容、程式保留原圖」的原則）。
- **補圖兩檔**：快速檔＝LaMa（Apache-2.0、約 200MB、依賴本機已有、不會生出新東西）；精修檔＝本機的 Qwen-Image 2.1 做遮罩補圖（先試不用裝的 `SetLatentNoiseMask`，邊界一格 16px 很粗；不夠再裝 LanPaint，約慢 5 倍）。FLUX Fill 可行但要再下載 10GB 以上；ObjectClear、OmniEraser、RORem、MAT、QIE Remover LoRA 因為沒節點、授權或版本不合而排除。
- **未知**：Qwen 2.1 做遮罩補圖的品質沒人測過（接縫、把人畫回去）；LaMa 在「人站在複雜背景前」的大面積移除會不會糊。要拿使用者照片 A/B 實測，決定精修檔有沒有必要（③ 細化時做）。

