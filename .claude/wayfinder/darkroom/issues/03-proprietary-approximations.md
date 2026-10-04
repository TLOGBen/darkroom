# ① 未公開演算法各用哪個公開方法近似？

Type: research
Status: resolved

## Question

Adobe 沒公開的：清晰度（1083 個 preset 用到）、去朦朧（673）、紋理（324）、亮部／陰影（PV2012，數值大時影響最大）、PV2012 曝光的高光滾降。查開源與文獻的近似做法（RawTherapee、darktable、論文、社群的逆向分析），每項列出候選方法、在 GPU 上的成本、已知跟 Adobe 的差異，推薦一個。另查 `LRTemplate Apply` 節點（comfyai.run 文件提到）的出處與實作方式可否參考。

## Answer

（2026-10-04，研究子代理；詳見 [research/03-proprietary-approximations.md](../research/03-proprietary-approximations.md)，27 個來源；GPU 時間是子代理在這台用 ComfyUI 內建 torch 2.14 跑原型量的，腳本在 scratchpad、未進 repo。主 session 重算 preset 統計屬實：Blacks 正值 811、Highlights |x|≥50 有 566、Clarity 平均絕對值 16.7、ProcessVersion 6.7 有 57 個。）

- **調校優先順序**：Highlights／Shadows／Whites／Blacks 幾乎每個 preset 都用、平均絕對值 36～46、|x|≥50 各有 332～566 個；Blacks 有 811 個是正值（抬黑＝霧面感的主要來源，推論）。Clarity／Dehaze／Texture 平均只有 ±17 左右，近似不準影響小。**調校先花在亮部、陰影、白、黑。**
- **各項推薦**：
  - Clarity：快速 local Laplacian filter（Aubry 2014），在 log 亮度上做、加中間調權重（Adobe 說過 PV2012 的 Clarity、Highlights、Shadows 源自 local Laplacian）。1.5MP 10 ms、24MP 92 ms。
  - Dehaze：dark channel prior＋guided filter（RawTherapee、darktable 的路線）；大氣光與透射率下限只在預覽圖算一次、以只動亮度為主；估不出霧時退回「全域扣霧幕＋對比＋飽和」。2.1 ms／25.6 ms。
  - Texture：Laplacian 金字塔中頻帶增益＋coring 避開雜訊，跟 Clarity 共用金字塔。
  - Highlights／Shadows：guided filter 做平滑亮度基底、套分區曲線、細節加回（darktable tone equalizer、RawTherapee shadows/highlights 的路線）。0.5 ms／7 ms；天際線光暈調不掉再升級成共用的 local Laplacian。
  - Whites／Blacks：全域、依照片調整的端點曲線，錨點取預覽直方圖 0.5%／99.5% 百分位（依照片調整的規則是推論）。
  - Exposure：線性光乘 2^EV＋平滑肩部；負 EV 借 Adobe 公開 DNG SDK 的二次式讓純白對到純白。
- **成本**：全部打開 1.5MP 預覽約 15 ms、24MP 輸出約 0.15 秒；24MP 時 local Laplacian 顯存峰值約 7GB（fp32），要改 fp16 或分塊。→ 支持「後端算預覽」的賭注在運算這一段成立，剩下要量的是傳輸與編碼（「① 預覽速度原型」那張）。
- **`LRTemplate Apply` 不值得參考**：出自 `mcaishao123/ComfyUI-lut`（MIT）；曝光在 sRGB 上直接乘且 EV 減半、亮部陰影白黑都是全域遮罩、Clarity 是大半徑 unsharp mask、沒有 Dehaze／Texture。RAWviewer、VibePhoto、LumiBase 也是憑經驗調；LumiBase 只校了負 Highlights 且沒有授權條款，不能抄。
- **授權限制**：darktable、RawTherapee 是 GPL，只能參考演算法與參數範圍，不能把程式碼抄進節點。
- **未知**：沒有 Adobe 參考渲染，所有「-100～+100 對應到參數」只是推論的初值，偏偏霧面感的關鍵數字（Blacks 正值抬多少、Highlights -85 壓多少）完全不知道。校正來源：賣家前後對比圖反推，或使用者決定是否用 Lightroom 試用期一次渲染「單一滑桿掃描」校正集——交給「① 『像 Lightroom』的驗收方式？」。Dehaze 在沒霧的照片上 dark channel 可能估錯（很多人像 preset 加 +10～+20）。

