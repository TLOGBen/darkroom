# llm-slider-experiment 數字（analyze.py 產生）

## 速度與格式

| | 35B-A3B | PE-I2I |
|---|---|---|
| 載入到 /health ok（秒） | 15.2 | 5.1 |
| VRAM 載入前 → 載入後 → 跑完（MiB） | 1548 → 15671 → 15749 | 1546 → 12137 → 12205 |
| 請求數 | 24 | 24 |
| 每次秒數 平均（最小–最大） | 10.53（9.52–13.5） | 9.55（8.63–10.53） |
| 提示詞 tokens 平均 | 634.21 | 634.21 |
| 提示詞處理 tok/s 平均 | 264.01 | 1677.45 |
| 生成 tokens 平均 | 531.17 | 566.62 |
| 生成 tok/s 平均 | 58.55 | 60.96 |
| json.loads 成功 | 24/24 | 24/24 |
| 欄位齊全＋範圍合法 | 24/24 | 24/24 |
| 不合格內容 | - | - |

## 兩次（seed 101 vs 202，中性提示詞）數值差異：各滑桿平均絕對差（9 張平均）

| 滑桿 | 35B-A3B | PE-I2I |
|---|---|---|
| Exposure2012 | 0.23 | 0.24 |
| Contrast2012 | 5.56 | 3.67 |
| Highlights2012 | 11.67 | 2.89 |
| Shadows2012 | 16.67 | 6.22 |
| Whites2012 | 6.11 | 2.89 |
| Blacks2012 | 7.78 | 2.78 |
| IncrementalTemperature | 8 | 6.44 |
| IncrementalTint | 5.78 | 1.78 |
| Vibrance | 6.11 | 3.67 |
| Saturation | 2.78 | 1.33 |
| Clarity2012 | 4.44 | 2.67 |
| Dehaze | 6.67 | 4 |
| Texture | 3.89 | 3.67 |
| HSL 18 鍵平均 | 1.6 | 0.32 |
| 基本 12 鍵（整數）平均 | 7.12 | 3.5 |

兩次正負號一致率（兩次都非 0 的滑桿中，正負號相同的比例；以及兩次『是否為 0』相同的比例）：

- 35B-A3B：正負號一致 92/97（95%）；是否動這個滑桿一致 236/279（85%）
- PE-I2I：正負號一致 89/91（98%）；是否動這個滑桿一致 258/279（92%）

兩次診斷（白平衡／曝光／反差）相同的張數：

- 35B-A3B：白平衡 5/9、曝光 7/9、反差 9/9
- PE-I2I：白平衡 9/9、曝光 7/9、反差 8/9

每次回應動了幾個滑桿（非 0 個數，31 個中）平均：
- 35B-A3B：12.79
- PE-I2I：11.33

## 方向檢查（中性提示詞的 2 次都算）

| 檢查 | 35B-A3B | PE-I2I |
|---|---|---|
| food_bluecast_dark: Exposure2012 > 0 | 2/2 | 2/2 |
| food_bluecast_dark: IncrementalTemperature > 0 | 2/2 | 2/2 |
| food_bluecast_dark: Contrast2012 > 0 or Blacks2012 < 0（反差低要加） | 2/2 | 2/2 |
| food_bluecast_dark 診斷：白平衡判為 cool | 2/2 | 2/2 |
| food_bluecast_dark 診斷：曝光判為 under（含 slightly） | 2/2 | 2/2 |
| sunset_kite: IncrementalTemperature >= 0（不中和夕陽） | 2/2 | 2/2 |
| sunset_kite: Highlights2012 <= 0（太陽／天空） | 2/2 | 2/2 |
| night_street: Highlights2012 <= 0（路燈） | 2/2 | 2/2 |
| night_street: Exposure2012 <= +0.7（不把夜景拉成白天） | 1/2 | 2/2 |
| **照片專屬檢查合計** | **17/18** | **18/18** |
| 全部照片：|Exposure2012| <= 1.5（保守） | 18/18 | 17/18（違反：food_bluecast_dark/s202） |
| 全部照片：|Saturation| <= 30（保守） | 18/18 | 18/18 |
| 全部照片：沒有『Contrast > +10 且 Blacks > +20』的矛盾組合 | 18/18 | 18/18 |

自我一致（模型自己的診斷 → 自己的數值方向）：
- 35B-A3B：55/57；不一致：night_street/lift_shadows_s101: diag cool -> Temp > 0; portrait_studio/base_s101: diag cool -> Temp > 0
- PE-I2I：49/57；不一致：landscape_lighthouse/base_s202: diag over -> Exposure < 0; night_street/base_s202: diag cool -> Temp > 0; night_street/lift_shadows_s101: diag under -> Exposure > 0; night_street/lift_shadows_s101: diag cool -> Temp > 0; night_street/lift_shadows_s202: diag over -> Exposure < 0; night_street/lift_shadows_s202: diag cool -> Temp > 0; street_rain/cool_cine_s101: diag cool -> Temp > 0; street_rain/cool_cine_s202: diag cool -> Temp > 0

## 想要／不想要

### food_breakfast：想要「a warm, bright, airy Japanese-style fresh look (日系清新)」，不想要「oversaturated colours」

- **35B-A3B** 中性兩次平均：Exposure +0.3, Contrast +20, Highlights -20, Shadows +35, Whites -12.5, Blacks -15, Temp +6, Tint +1, Vibrance +17.5, Sat +2.5, Clarity +15, Dehaze +10, Texture +7.5
  - seed 101（5/6）：Temp > 0 ✓、Temp > 中性兩次平均 ✗、Exposure >= 中性平均（明亮） ✓、Saturation <= 0（不過飽和） ✓、Saturation+Vibrance <= 中性平均 ✓、Contrast <= 中性平均（清新＝柔） ✓
    - 數值：Exposure +0.4, Contrast +15, Shadows +45, Whites +15, Blacks -15, Temp +5, Vibrance +10, Clarity +5, Texture +5
    - intent：To create a bright, airy Japanese-style fresh look by lifting shadows and exposure while adding a subtle warmth to the already appetizing colors.
  - seed 202（3/6）：Temp > 0 ✓、Temp > 中性兩次平均 ✗、Exposure >= 中性平均（明亮） ✓、Saturation <= 0（不過飽和） ✗、Saturation+Vibrance <= 中性平均 ✗、Contrast <= 中性平均（清新＝柔） ✓
    - 數值：Exposure +0.6, Contrast +15, Highlights -20, Shadows +20, Whites +25, Blacks -15, Temp +5, Tint -5, Vibrance +20, Sat +5, Clarity +10, Dehaze +5, Texture +10
    - intent：Create a bright, airy, and appetizing Japanese-style fresh look by lifting exposure, softening shadows, adding warmth, and boosting clarity without oversaturating.
- **PE-I2I** 中性兩次平均：Contrast +13.5, Highlights -12.5, Shadows +18.5, Whites -6.5, Blacks -12.5, Vibrance +10, Clarity +9, Texture +4
  - seed 101（6/6）：Temp > 0 ✓、Temp > 中性兩次平均 ✓、Exposure >= 中性平均（明亮） ✓、Saturation <= 0（不過飽和） ✓、Saturation+Vibrance <= 中性平均 ✓、Contrast <= 中性平均（清新＝柔） ✓
    - 數值：Exposure +1.2, Contrast -30, Highlights -20, Shadows +40, Whites +10, Blacks -20, Temp +15, Tint +5, Vibrance +10, Sat -10, Clarity +10, Dehaze +15, Texture +5
    - intent：a warm, bright, airy Japanese-style fresh look with lifted shadows, clean bright whites, soft contrast and a gentle warm cast, while keeping saturation natural and never oversaturated.
  - seed 202（5/6）：Temp > 0 ✓、Temp > 中性兩次平均 ✓、Exposure >= 中性平均（明亮） ✓、Saturation <= 0（不過飽和） ✓、Saturation+Vibrance <= 中性平均 ✗、Contrast <= 中性平均（清新＝柔） ✓
    - 數值：Exposure +0.7, Contrast +10, Highlights -10, Shadows +15, Whites -10, Blacks -10, Temp +8, Vibrance +15, Clarity +8, Dehaze +5
    - intent：A warm, bright, airy Japanese-style fresh look with clean white plate and egg whites, gently lifted exposure, soft warm color temperature, and restrained saturation that keeps colors natural rather than oversaturated.

### street_rain：想要「a cool-toned, cinematic film look」，不想要「warm or yellow tones」

- **35B-A3B** 中性兩次平均：Exposure +0.5, Contrast +22.5, Highlights -15, Shadows +12.5, Whites +10, Blacks -25, Temp +5, Tint +2.5, Vibrance +15, Sat +5, Clarity +17.5, Dehaze +12.5, Texture +10, SatRed +5
  - seed 101（3/3）：Temp < 0 ✓、Temp < 中性兩次平均 ✓、Orange/Yellow 飽和度沒有加（<=0） ✓
    - 數值：Exposure +0.6, Contrast +25, Highlights -20, Shadows +30, Whites +10, Blacks -15, Temp -8, Tint -5, Vibrance +15, Clarity +10, Dehaze +10, SatOrange -5
    - intent：Brighten and punch up the image to a cool-toned, cinematic film look.
  - seed 202（3/3）：Temp < 0 ✓、Temp < 中性兩次平均 ✓、Orange/Yellow 飽和度沒有加（<=0） ✓
    - 數值：Exposure +0.7, Contrast +25, Highlights -25, Shadows +45, Whites -15, Blacks -10, Temp -15, Tint -10, Vibrance +25, Clarity +25, Dehaze +15, Texture +10
    - intent：To create a moody, cool-toned cinematic image by lifting exposure, recovering highlights, and adding a distinct blue-green cast to the shadows and overall scene.
- **PE-I2I** 中性兩次平均：Exposure +0.4, Contrast +17.5, Highlights -11, Shadows +11.5, Whites -4, Blacks -13.5, Temp +10.5, Tint +2, Vibrance +13.5, Clarity +12, Dehaze +7.5, Texture +7.5
  - seed 101（3/3）：Temp < 0 ✓、Temp < 中性兩次平均 ✓、Orange/Yellow 飽和度沒有加（<=0） ✓
    - 數值：Exposure +0.6, Contrast +25, Highlights -15, Shadows +15, Blacks -20, Temp -15, Vibrance +10, Clarity +15, Dehaze +10, Texture +10
    - intent：a cool-toned cinematic film look: lift the underexposed shadows just enough to recover detail while deepening the blacks for punch, strengthen midtone contrast and clarity so the rainy alley reads crisp and moody, and shift the white balance cooler to remove any warm cast, keeping the overall palette blue-cold and filmic without over-darkening or over-sharpening into a processed look.
  - seed 202（3/3）：Temp < 0 ✓、Temp < 中性兩次平均 ✓、Orange/Yellow 飽和度沒有加（<=0） ✓
    - 數值：Exposure +0.7, Contrast +18, Highlights -12, Shadows +10, Whites -8, Blacks -14, Temp -16, Tint -6, Vibrance +8, Clarity +12, Dehaze +6, Texture +8, HueRed -6, SatRed -4, LumRed -4, HueOrange -8, SatOrange -6, LumOrange -5, HueYellow -10, SatYellow -8, LumYellow -8, HueGreen -4, SatGreen -3, LumGreen -3, HueAqua -6, SatAqua -5, LumAqua -4, HueBlue -12, SatBlue -10, LumBlue -10
    - intent：a cool-toned, cinematic film look with clean deep blues and cyans, controlled contrast, recovered shadow and highlight detail, and no warm or yellow cast anywhere in the frame.

### night_street：想要「recover the shadows so the dark areas show detail」，不想要「a flat, washed-out, matte look」

- **35B-A3B** 中性兩次平均：Exposure +0.9, Contrast +25, Highlights -40, Shadows +37.5, Whites +10, Blacks -20, Temp +6, Tint +2.5, Vibrance +15, Clarity +20, Dehaze +12.5, Texture +12.5, HueBlue -5, SatBlue -10, LumBlue -5
  - seed 101（4/4）：Shadows >= +30 ✓、Shadows > 中性兩次平均 ✓、Blacks <= 0（不霧面） ✓、Contrast >= -10（不扁平） ✓
    - 數值：Exposure +0.5, Contrast +15, Highlights -30, Shadows +60, Whites +10, Blacks -20, Temp -15, Tint +5, Vibrance +10, Clarity +10, Dehaze +15, SatBlue -10, LumBlue -20
    - intent：To reveal the rich textures in the night-time architecture by brightening the shadows, while restoring contrast and clarity for a crisp, vibrant look.
  - seed 202（4/4）：Shadows >= +30 ✓、Shadows > 中性兩次平均 ✓、Blacks <= 0（不霧面） ✓、Contrast >= -10（不扁平） ✓
    - 數值：Exposure +0.9, Contrast +10, Highlights -20, Shadows +50, Whites +15, Blacks -15, Temp +10, Tint +5, Vibrance +20, Clarity +25, Dehaze +15
    - intent：To reveal the rich textures of the stone architecture and the details of the street while maintaining the deep, atmospheric mood of a night scene, free from flatness or color casts.
- **PE-I2I** 中性兩次平均：Exposure +0.6, Contrast +12, Highlights -13, Shadows +9, Whites -8, Blacks -12, Temp -1, Vibrance +9, Clarity +8, Dehaze +5, Texture +6
  - seed 101（4/4）：Shadows >= +30 ✓、Shadows > 中性兩次平均 ✓、Blacks <= 0（不霧面） ✓、Contrast >= -10（不扁平） ✓
    - 數值：Highlights -10, Shadows +30, Blacks -10
    - intent：recover the shadow detail in the dark areas of this night street scene so the stone walls, cobblestones, and building facades show visible texture and detail, while keeping the rich night mood, deep clean blacks, and the existing warm window lights and purple fortress glow intact, producing a detailed, dimensional night photograph rather than a flat, washed-out, matte look.
  - seed 202（4/4）：Shadows >= +30 ✓、Shadows > 中性兩次平均 ✓、Blacks <= 0（不霧面） ✓、Contrast >= -10（不扁平） ✓
    - 數值：Exposure +0.3, Highlights -20, Shadows +40
    - intent：recover the crushed shadow detail in the night street scene so the dark stone walls, cobblestones and alley reveal visible texture while keeping the deep blue night atmosphere, with controlled highlights on the lamps and a rich, detailed, non-flat result.

## 每張照片（seed 101 / 202）

### portrait_studio

- **35B-A3B s101**（13.5s）：Portrait of a man wearing a dark teal zip-up top.｜WB cool / blue｜曝光 underexposed｜反差 low
  - 問題：The overall image is too dark.; The skin in the shadows (cheek, neck) is crushed.; The teal sweater is dark and muddy, lacking texture.; There is a blue color cast on the skin and the grey background.
  - 數值：Exposure +0.8, Contrast +10, Shadows +35, Whites +10, Blacks -15, Temp -15, Tint +5, Vibrance +10, Clarity +15, Dehaze +15, Texture +10, HueGreen -5, SatGreen +15, LumBlue -10
  - intent：Brighten the image and lift the shadows to reveal the texture of the sweater and skin, while removing the blue cast for natural skin tones.
- **35B-A3B s202**（9.95s）：Portrait of a model looking down.｜WB cool / blue｜曝光 underexposed｜反差 low
  - 問題：The image is too dark overall, losing detail in the shadows.; The background is a cool blue-grey, and the overall tone is slightly cool.; The fabric texture on the jacket is flat and lacks definition.; Skin tones are dark and slightly muddy.; The mood is moody and dramatic.
  - 數值：Exposure +0.6, Contrast +15, Highlights -10, Shadows +40, Whites +5, Blacks -10, Temp +5, Tint -5, Vibrance +10, Clarity +15, Dehaze +15, Texture +15, SatOrange +5, LumOrange +10, HueGreen -5, SatGreen +10, LumGreen -5, SatBlue -10, LumBlue -5
  - intent：I'm aiming for a moody, cinematic look that brightens the subject, reveals the jacket's texture, and keeps the cool blue background atmospheric.
- **PE-I2I s101**（10.49s）：A young Black male model with short afro-textured hair, head bowed in profile, wearing a dark teal / deep green high-collar textured zip jacket with tonal quilted panel stitching, shot against a plain cool grey-blue studio backdrop.｜WB cool / blue｜曝光 slightly underexposed｜反差 low
  - 問題：The image has a cool blue-grey colour cast on both the model's skin and the background, pushing the whites toward blue.; The overall exposure is slightly dark, with the jacket and shadow areas sinking into murky darkness.; Contrast is flat and muddy: shadow detail is lost in the jacket's folds, and the background lacks separation from the subject.; The jacket's teal fabric reads muted and murky rather than clean and rich, and the skin tone looks cool and dull rather than a healthy natural warmth.; Detail in the jacket's textured fabric is soft; the image looks a bit hazy and low in crispness.
  - 數值：Exposure +0.6, Contrast +12, Highlights -8, Shadows +10, Whites -6, Blacks -14, Temp +8, Tint +4, Vibrance +12, Sat +6, Clarity +9, Dehaze +6, Texture +8
  - intent：Restore a clean, naturally warm skin tone and a rich, clean teal fabric against a neutral grey-blue studio backdrop, with balanced exposure, recovered shadow and highlight detail, deeper clean blacks, and crisp fabric texture, while preserving the moody editorial atmosphere and the model's identity.
- **PE-I2I s202**（8.63s）：A young Black male model with short twisted/afro-textured hair, head bowed in a three-quarter profile looking down, wearing a dark green (teal) quarter-zip knit jacket with tonal quilted curved seam patterns, photographed against a plain cool grey-blue studio backdrop.｜WB cool / blue｜曝光 slightly underexposed｜反差 low
  - 問題：a cool blue color cast from the studio backdrop and lighting; overall underexposure with the subject's face and jacket sinking into shadow; low contrast with murky, flat midtones; shadows too deep to reveal detail in the jacket's quilted texture; skin tones reading cool and dull rather than warm and natural
  - 數值：Exposure +0.7, Contrast +18, Highlights -12, Shadows +22, Whites -8, Blacks -20, Temp +16, Tint +8, Vibrance +12, Sat +6, Clarity +10, Dehaze +8, Texture +14, HueOrange +6, SatOrange +10, LumOrange +4, HueGreen -10, SatGreen +8
  - intent：A correctly exposed, warm-natural studio portrait with clean contrast, rich shadow detail, and natural warm skin tones against the cool grey backdrop.

### landscape_lighthouse

- **35B-A3B s101**（10.61s）：A lighthouse on rocky terrain at dusk, with a dramatic sky.｜WB neutral｜曝光 slightly underexposed｜反差 low
  - 問題：The overall image is too dark (underexposed).; The shadows on the rocks are crushed and lack detail.; The sky and distant mist are flat and grey.; The rocks lack texture and definition.
  - 數值：Exposure +0.8, Contrast +15, Highlights -15, Shadows +40, Whites +10, Blacks -10, Vibrance +15, Clarity +25, Dehaze +15, Texture +10, LumGreen -10, LumBlue -10
  - intent：To create a dramatic and moody landscape by brightening the scene, recovering shadow detail in the rocks, and adding punchy contrast and clarity to the main subject.
- **35B-A3B s202**（10.32s）：A lighthouse on rocky shores with dramatic, stormy clouds.｜WB neutral｜曝光 slightly underexposed｜反差 low
  - 問題：The image is too dark overall, losing detail in the foreground rocks.; The sky lacks drama; the clouds are flat and grey.; The water looks dull and lacks texture.; The image feels a bit 'muddy' due to atmospheric haze.; The white lighthouse is dull and could pop more against the dark background.
  - 數值：Exposure +0.4, Contrast +15, Highlights -30, Shadows +20, Whites +15, Blacks -15, Vibrance +10, Clarity +15, Dehaze +20
  - intent：To bring out the drama in the stormy scene by adding contrast and clarity, revealing texture in the rocks and water while maintaining the moody atmosphere.
- **PE-I2I s101**（8.85s）：a white lighthouse with a black gallery and red lantern room standing on a rocky granite islet surrounded by a dark sea under heavy storm clouds｜WB cool / blue｜曝光 slightly underexposed｜反差 low
  - 問題：a cool blue colour cast from the overcast storm light; somewhat flat, low contrast with a hazy, washed-out look; underexposed shadow areas on the rocks; muted, desaturated colours in the midtones
  - 數值：Exposure +0.5, Contrast +12, Highlights -10, Shadows +14, Whites -8, Blacks -14, Temp +6, Tint +4, Vibrance +12, Clarity +8, Dehaze +6, Texture +6
  - intent：a balanced, natural rendition of the stormy seascape: remove the cool blue cast and haze while lifting the underexposed rocks, restoring clean deep blacks, full contrast and believable natural colour saturation, so the scene reads as a crisp, well-exposed photograph of a dramatic overcast coastal scene.
- **PE-I2I s202**（9.85s）：a white lighthouse with a black lantern room and red top on a granite rocky island, surrounded by a dark sea with white foam waves under a heavy overcast storm sky with a warm break of light at the left horizon｜WB cool / blue｜曝光 slightly overexposed｜反差 low
  - 問題：the heavy overcast haze and fog washing out the scene, softening the rock textures and the horizon; the sky blown out to a flat white-grey in the bright break areas, with no detail; the rocks in the foreground and midground rendered dark and murky with lost shadow detail; the overall cool blue cast from the storm light, making the white lighthouse and the granite look dull and cool rather than warm natural stone; low contrast and flat tonal range making the image look washed out and hazy
  - 數值：Exposure +0.3, Contrast +18, Highlights -20, Shadows +12, Whites -8, Blacks -14, Temp +6, Tint +4, Vibrance +8, Sat +6, Clarity +14, Dehaze +22, Texture +10
  - intent：a clear, crisp, naturally warm coastal scene with the storm mood retained: haze lifted to reveal rock texture, highlights recovered so the bright sky break holds detail, shadows opened to reveal the dark granite, and a gentle warm cast restoring natural stone and white tones, while the dramatic overcast atmosphere and the lighthouse's mood remain fully intact.

### night_street

- **35B-A3B s101**（12.28s）：A narrow, cobblestone street in an old town at night, leading up towards a large, illuminated castle on the hill.｜WB neutral｜曝光 slightly underexposed｜反差 low
  - 問題：The overall image is too dark, losing detail in the shadows.; The contrast is low and muddy, making the stone textures look flat.; There are blown-out highlights in the sky and on the castle.; The street and building textures lack definition.; The purple lights on the castle are slightly oversaturated and muddy.
  - 數值：Exposure +0.55, Contrast +25, Highlights -40, Shadows +30, Whites +10, Blacks -15, Vibrance +10, Clarity +20, Dehaze +10, Texture +15, HueBlue -10, SatBlue -10
  - intent：To create a moody, atmospheric night scene that reveals the rich textures of the old stone buildings and the cobblestone street, while deepening the night sky and making the castle lights pop.
- **35B-A3B s202**（10.89s）：A historic cobblestone street in Quebec City at night, leading up to the illuminated Château Frontenac.｜WB cool / blue｜曝光 underexposed｜反差 low
  - 問題：The image is significantly underexposed; the stone walls and street are too dark.; The white balance is too cool (blue), making the stone walls look grey and lifeless instead of warm.; The contrast is low; the shadows are muddy and lack depth.; The purple lights on the castle are very bright and slightly clipped.; The overall image lacks clarity and texture in the stone and cobblestones.
  - 數值：Exposure +1.25, Contrast +25, Highlights -40, Shadows +45, Whites +10, Blacks -25, Temp +12, Tint +5, Vibrance +20, Clarity +20, Dehaze +15, Texture +10, SatBlue -10, LumBlue -10
  - intent：Brighten the scene to reveal the textures of the stone buildings while restoring a warm, inviting atmosphere and deepening the shadows for a crisp, dramatic night look.
- **PE-I2I s101**（9.91s）：a night street scene in an old stone town (Quebec City style), with cobblestone lane, stone buildings with lit windows and wall lamps, and a hilltop castle/chateau illuminated in purple/magenta in the dark night sky｜WB cool / blue｜曝光 slightly underexposed｜反差 low
  - 問題：a blue/cool color cast over the whole frame that flattens the warm stone and lamp light; muted, washed-out colors lacking punch; flat contrast with crushed detail in the dark night sky and murky shadows; soft, slightly hazy look in the midtones
  - 數值：Exposure +0.4, Contrast +12, Highlights -14, Shadows +8, Whites -8, Blacks -14, Temp +12, Vibrance +12, Clarity +8, Dehaze +4, Texture +6
  - intent：Restore a clean, balanced night photograph: correct the blue color cast to a neutral-to-warm balance that lets the warm window and lamp light read naturally, lift the exposure just enough to reveal shadow detail, deepen the blacks to clean rich night darkness while keeping the castle's purple illumination intact, and add controlled contrast and clarity so the stone walls, cobblestones, and lit windows gain crisp, punchy, natural color without looking over-processed.
- **PE-I2I s202**（8.84s）：a night photograph of a cobblestone alley in an old European stone city (Quebec City), with a hilltop castle/chateau lit in purple/magenta in the background｜WB cool / blue｜曝光 slightly underexposed｜反差 low
  - 問題：a cool blue color cast over the stone walls and street; overall exposure slightly dark; contrast too low and flat, shadows murky and lacking detail; highlights from the street lamps slightly blown out; the night scene feels hazy and washed-out rather than clean and deep
  - 數值：Exposure +0.7, Contrast +12, Highlights -12, Shadows +10, Whites -8, Blacks -10, Temp -14, Vibrance +6, Clarity +8, Dehaze +6, Texture +6
  - intent：a clean, properly exposed night scene: remove the cool blue cast, restore natural neutral-to-warm stone tones under the street lamps, lift the shadows to reveal detail while keeping deep clean blacks, recover the lamp highlights, and add gentle clarity and contrast so the photo reads as a crisp, well-balanced night photograph while preserving its night mood.

### street_rain

- **35B-A3B s101**（10.89s）：A rainy street scene with pedestrians walking under umbrellas.｜WB neutral｜曝光 underexposed｜反差 low
  - 問題：The overall image is too dark.; The blacks are muddy and lack punch.; Midtones are flat and lack definition.; The wet pavement and neon signs need to be more distinct.
  - 數值：Exposure +0.45, Contrast +25, Highlights -15, Shadows +10, Whites +10, Blacks -20, Vibrance +15, Sat +10, Clarity +20, Dehaze +15, Texture +10
  - intent：Brighten the scene and enhance the mood by adding clarity and punch to the midtones and shadows while recovering the bright neon signs.
- **35B-A3B s202**（10.12s）：A moody street scene in an alleyway on a rainy day, featuring pedestrians with umbrellas and neon signage.｜WB cool / blue｜曝光 underexposed｜反差 low
  - 問題：The image is too dark overall.; The white balance is too cool, giving the scene a dull, blueish cast.; The image looks flat and lacks contrast.; The black points are lifted, making the dark areas look muddy rather than deep.; The neon signs are dull and lack saturation.
  - 數值：Exposure +0.6, Contrast +20, Highlights -15, Shadows +15, Whites +10, Blacks -30, Temp +10, Tint +5, Vibrance +15, Clarity +15, Dehaze +10, Texture +10, SatRed +10
  - intent：Brighten the scene while correcting the blue cast and deepening the shadows to create a punchy, high-contrast look that makes the neon signs and wet reflections pop.
- **PE-I2I s101**（10.09s）：a rainy narrow commercial alley (side street) lined with shop signs and pedestrians holding umbrellas, viewed from behind walking away｜WB cool / blue｜曝光 slightly underexposed｜反差 low
  - 問題：the overall image has a cool blue colour cast from the overcast rainy light, with a flat, washed-out tonal range; low contrast and low clarity give a hazy, soft impression, with midtones lacking punch; the dark shopfronts and shadowed alley edges are crushed and lack detail, while the lit lamp and neon signs blow out highlights; saturation is muted, with the red and orange umbrellas and the warm sign glows appearing dull; the wet pavement reflections are soft and unclear, and fine textures (brick walls, sign lettering, umbrella fabric) read soft rather than crisp
  - 數值：Exposure +0.4, Contrast +15, Highlights -12, Shadows +8, Whites -8, Blacks -12, Temp +6, Tint +4, Vibrance +12, Clarity +14, Dehaze +10, Texture +10
  - intent：a crisp, clean, and naturally balanced rendering of this rainy alley, with the cool overcast cast corrected toward neutral, richer contrast and clarity, recovered shadow and highlight detail, and more vivid yet believable saturation, while fully preserving the rainy moody atmosphere.
- **PE-I2I s202**（9.69s）：a narrow wet pedestrian backstreet on a rainy day, viewed from behind with pedestrians walking away, many holding umbrellas (a prominent orange/red umbrella and a black umbrella), flanked by shopfronts and hanging signs including a heart-shaped "Golly Gosh Vintage Boutique" sign, a black lantern lamp, and signs for "GUINNESS", "HANLEY'S CORNISH PASTIES", "Only", and "TATTOO"; the wet stone pavement reflects the lights.｜WB cool / blue｜曝光 slightly underexposed｜反差 low
  - 問題：a cool blue colour cast on the whole frame (the grey sky and shaded stone walls read too blue); overall flat, low contrast with washed-out midtones; shadows that are dark but without detail, highlights that are dim; slightly underexposed overall; soft, hazy atmosphere that lacks crispness
  - 數值：Exposure +0.4, Contrast +20, Highlights -10, Shadows +15, Blacks -15, Temp +15, Vibrance +15, Clarity +10, Dehaze +5, Texture +5
  - intent：lift this rainy backstreet photo out of its flat, cool, underexposed state into a clear, balanced rendering with a corrected neutral-warm white balance, recovered shadow and highlight detail, richer contrast and deeper clean blacks, while keeping the moody rainy-day atmosphere and the wet reflections intact.

### food_breakfast

- **35B-A3B s101**（11.23s）：A full English breakfast plate on a wooden table.｜WB cool / blue｜曝光 slightly underexposed｜反差 low
  - 問題：Cool/Blue color cast in the shadows (wood table and napkin).; Overall image is slightly too dark.; Contrast is low, resulting in a 'flat' look.; Shadows in the wood grain are blocked up.
  - 數值：Exposure +0.35, Contrast +25, Highlights -10, Shadows +30, Whites -15, Blacks -25, Temp +12, Tint +2, Vibrance +15, Sat +5, Clarity +15, Dehaze +10, Texture +5
  - intent：Warm up the cool tones and brighten the image to reveal the appetizing colors of the food, while adding clarity and punch to the textures of the wood and food.
- **35B-A3B s202**（9.79s）：A plate of breakfast food (bacon, eggs, sausages, beans, toast) on a wooden table.｜WB neutral｜曝光 slightly underexposed｜反差 low
  - 問題：The image is a bit dark overall.; The colors are muted and lack vibrancy.; The contrast is low, making the food look flat.; The wooden table background is very dark and loses texture.; The white plate has blown-out highlights.
  - 數值：Exposure +0.3, Contrast +15, Highlights -30, Shadows +40, Whites -10, Blacks -5, Vibrance +20, Clarity +15, Dehaze +10, Texture +10
  - intent：A richer, more appetizing version of the breakfast plate where the food colors are vibrant and the textures are pronounced, while recovering detail from the dark table and bright plate.
- **PE-I2I s101**（9.22s）：a full English breakfast on a white square plate — two fried eggs with runny orange yolks, baked beans in tomato sauce, grilled sausages, toast topped with two pieces of bacon, the plate resting on a weathered dark wooden table with a knife and fork on a white napkin at the right｜WB neutral｜曝光 slightly underexposed｜反差 low
  - 問題：overall image is a bit dull and flat, lacking punch; shadows on the wooden table and under the food are crushed and murky; highlights on the white plate and egg whites are a touch bright but not clipping; muted, low-contrast rendering with no haze per se, just a flat, sleepy look
  - 數值：Exposure +0.4, Contrast +15, Highlights -10, Shadows +25, Whites -5, Blacks -15, Vibrance +12, Clarity +8
  - intent：a clean, appetising food-photo finish with correct exposure, lifted shadow detail on the dark wood, controlled highlights on the plate and egg whites, and richer, punchier yet natural colour.
- **PE-I2I s202**（10.05s）：a full English breakfast on a white square plate (bacon strips, toast, two fried eggs with runny orange yolks, baked beans in tomato sauce, two grilled sausages), with a knife and fork wrapped in a white paper napkin resting on the right side, all placed on a dark weathered wooden plank table｜WB neutral｜曝光 slightly overexposed｜反差 low
  - 問題：the overall exposure is a bit bright and flat, with the white plate and egg whites blown out and losing detail; contrast is low and the image looks washed out and milky, with the dark wooden table and shadows not deep enough; the whites of the plate and eggs are clipping to pure white with no highlight detail; shadow areas under the food and around the plate edges are murky and crushed rather than open, detailed darkness; local midtone contrast is soft and the food textures (bacon crispness, bean gloss, sausage crust, toast grain) lack crispness and detail definition
  - 數值：Exposure -0.4, Contrast +12, Highlights -15, Shadows +12, Whites -8, Blacks -10, Vibrance +8, Clarity +10, Texture +8
  - intent：restore a bright, flat food photo to a properly exposed, contrast-rich result with clean whites that retain highlight detail, deep open shadows, and crisp food texture, while keeping the natural daylight mood of the scene and all colors faithful to the original.

### interior_cafe

- **35B-A3B s101**（11.22s）：An ornate, vaulted architectural ceiling with painted ribs and hanging light fixtures.｜WB neutral｜曝光 underexposed｜反差 low
  - 問題：The image is too dark, losing detail in the shadowed corners and arches.; The overall look is flat and muddy due to low contrast and a slight haze.; The colors, particularly the greens and blues, appear dull.; The light bulbs are blown out (clipped highlights).
  - 數值：Exposure +0.75, Contrast +20, Highlights -30, Shadows +30, Whites -10, Blacks -15, Temp -3, Tint +5, Vibrance +25, Sat +5, Clarity +15, Dehaze +10, Texture +10, HueRed -5, SatRed -15, LumRed -10, HueYellow +5, SatYellow +5, LumYellow +5, SatGreen +15, LumGreen -10, SatAqua +10, SatBlue +10
  - intent：Brighten the scene and punch up the details to create a rich, vibrant, and sharp architectural shot while keeping the colors natural.
- **35B-A3B s202**（9.88s）：Architectural vaulted ceiling with decorative arches and hanging light fixtures.｜WB neutral｜曝光 underexposed｜反差 low
  - 問題：The image is too dark, losing detail in the shadows of the arches and columns.; The image looks flat and lacks punch due to low contrast.; The hanging lights are blown out (clipped highlights), losing their detail.; The overall image appears slightly hazy, reducing the sharpness of the architectural details.
  - 數值：Exposure +1.25, Contrast +35, Highlights -75, Shadows +80, Whites +20, Blacks -25, Clarity +35, Dehaze +35
  - intent：To create a clean, sharp, and well-balanced architectural shot that reveals the intricate details of the ceiling while restoring a natural sense of depth and contrast.
- **PE-I2I s101**（9.32s）：an upward-looking view of a Gothic-vaulted ceiling with ribbed arches, painted ornamental bands, and hanging chandeliers with glowing white globe lamps｜WB warm / orange-yellow｜曝光 slightly underexposed｜反差 low
  - 問題：a warm yellow/orange colour cast that makes the cream ceiling read too orange; overall flat, low contrast with the pale ceiling lacking depth; the bright lamp globes slightly overexposed and blown out; the shadowed vault recesses and dark ceiling rods crushed into murky black, losing detail in the ribbed arches and chandelier arms
  - 數值：Exposure +0.4, Contrast +12, Highlights -10, Shadows +10, Whites -5, Blacks -10, Temp -12, Tint -4, Vibrance +8, Clarity +8, Dehaze +5, Texture +6
  - intent：correct the warm orange colour cast to a neutral cream-white balance, lift the exposure slightly, deepen the shadows into clean rich blacks, recover highlight detail on the lamp globes, and add gentle contrast and clarity so the vaulted ceiling reads with full depth while keeping the scene's warm interior atmosphere intact.
- **PE-I2I s202**（10.43s）：an upward view of a grand vaulted ceiling with Gothic ribbed arches, painted decorative bands in muted green, blue and ochre, ornamental star-shaped bosses at the arch intersections, white marble columns with gilded capitals, and black metal chandeliers with glowing white glass shades hanging into the frame｜WB warm / orange-yellow｜曝光 slightly underexposed｜反差 low
  - 問題：a warm yellow-orange colour cast from the old tungsten lighting tints the whole ceiling; the overall exposure is a bit dark, with the chandelier shades and the shadowed vaults underlit; contrast is flat and the image looks washed-out and soft, with muted, low-saturation wall surfaces; the painted decorative bands (green, blue, ochre) look dull and faded rather than rich; detail in the darker recesses of the arches is lost while the glowing shades are bright and slightly clipped
  - 數值：Exposure +0.7, Contrast +12, Highlights -10, Shadows +10, Whites -8, Blacks -12, Temp -14, Vibrance +16, Sat +6, Clarity +8, Dehaze +8, Texture +6, SatGreen +4, SatAqua +4, SatBlue +6
  - intent：Correct the warm tungsten colour cast toward neutral daylight, brighten the exposure to lift the underlit vaults, deepen the blacks and recover shadow detail in the arch recesses while taming the bright chandelier shades, and enrich the muted painted green, blue and ochre decorative bands into clean, saturated, well-defined colours, so the ceiling reads crisp, balanced and vivid without losing its historic character.

### sunset_kite

- **35B-A3B s101**（10.48s）：A sunset over the ocean with silhouetted figures and a kite surfer.｜WB neutral｜曝光 underexposed｜反差 low
  - 問題：The foreground sand and water are too dark (underexposed), making the scene look muddy.; The dynamic range is compressed; the bright sky needs darkening to recover detail while the foreground needs brightening.; The image has low local contrast (flat) and appears hazy, lacking punch.
  - 數值：Exposure +0.4, Contrast +15, Highlights -35, Shadows +40, Whites +10, Blacks -15, Temp +5, Vibrance +10, Clarity +15, Dehaze +20, Texture +10, SatOrange +5, LumBlue -15
  - intent：Restore natural dynamic range by brightening the dark foreground and deepening the sun's glow, while adding contrast and clarity to make the sunset vibrant and punchy.
- **35B-A3B s202**（10.18s）：A beach sunset featuring kite surfers and silhouetted figures.｜WB warm / orange-yellow｜曝光 slightly underexposed｜反差 low
  - 問題：The image is slightly underexposed, losing detail in the water.; The bright sun is blown out (clipped), lacking detail.; The sky is a bit flat and hazy, lacking punch.; The overall color is slightly muddy and could be more vibrant.; The water is a bit flat and hazy.
  - 數值：Exposure +0.4, Contrast +20, Highlights -40, Shadows +20, Whites +10, Blacks -10, Temp +5, Tint +5, Vibrance +15, Sat +5, Clarity +15, Dehaze +15, Texture +10, SatRed +5, SatOrange +10, SatYellow +5, SatBlue -10, LumBlue -10
  - intent：To bring the photo out of the shadows and restore detail in the bright sky, while deepening the colors and adding clarity to create a more dramatic and vibrant sunset.
- **PE-I2I s101**（10.13s）：A sunset beach scene: the setting sun at the horizon center-left, a crescent-shaped kite silhouette in the upper-right sky, a surfer on the water at left, three people walking on the wet sand at right, a thin breakwater line at the far right horizon, and warm orange clouds across the sky.｜WB warm / orange-yellow｜曝光 slightly underexposed｜反差 low
  - 問題：a hazy, washed-out sky with low contrast and a milky veil over the clouds; shadows that are crushed to pure black on the silhouetted figures and the foreground sand, losing detail; overall flat contrast with a faded, hazy look; slightly underexposed with the sun's glow not fully recovered; muted, desaturated colors in the clouds and sea
  - 數值：Exposure +0.4, Contrast +25, Highlights -15, Shadows +20, Blacks -15, Temp +5, Vibrance +15, Clarity +10, Dehaze +12, Texture +5
  - intent：Restore this sunset beach photo with a conservative, professional grade: lift the hazy, washed-out veil to recover clean cloud detail and a crisp horizon, open the crushed silhouettes just enough to reveal shadow detail, deepen the blacks for punch while keeping the warm sunset glow and orange mood fully intact, and enrich the muted colors of the sky and sea so the image reads clear, vivid, and naturally finished.
- **PE-I2I s202**（10.53s）：A wide beach scene at sunset: the low sun sitting just above the horizon with a warm orange glow and a reflection path on the water, a crescent-shaped kite (kitesurfing kite) silhouette on the right side of the sky, a kitesurfer riding on the water at left, three people walking along the wet sand at the shoreline in the center-right, a thin line of breakwater/buoy line at the right horizon, and scattered clouds tinted orange and pink across the sky; the foreground is a smooth wet sandy beach.｜WB warm / orange-yellow｜曝光 slightly underexposed｜反差 low
  - 問題：the sky and overall image look hazy and washed-out with soft contrast; the sun area is slightly blown out and the highlights are not fully recovered; the shadowed figures on the sand and the water foreground are crushed into dark flat silhouettes lacking detail; the warm orange cast is heavy but the scene is a sunset so the warmth must be preserved; the midtones are dull and the colors are muted rather than rich
  - 數值：Exposure +0.4, Contrast +12, Highlights -12, Shadows +10, Whites -8, Blacks -10, Vibrance +15, Clarity +8, Dehaze +12
  - intent：Restore this sunset beach photo with a gentle dehaze and contrast recovery: lift the hazy washed-out veil to reveal clean, deeper blacks and richer orange-and-pink sky tones, recover highlight detail around the sun and dark shadow detail in the silhouetted figures and water, while keeping the warm sunset glow fully intact and the scene natural, not over-processed.

### portrait_balaclava

- **35B-A3B s101**（11.25s）：A close-up portrait of a beekeeper, with the face partially obscured by a mesh hat and veil.｜WB neutral｜曝光 slightly underexposed｜反差 low
  - 問題：The photo is slightly underexposed, making the face and fabric details a bit dark.; The contrast is low, giving the image a slightly flat look.; There is no significant color cast.
  - 數值：Exposure +0.3, Contrast +15, Highlights -10, Shadows +20, Whites +10, Blacks -10, Vibrance +10, Clarity +10, Dehaze +5
  - intent：Brighten the image and enhance contrast and texture to make the beekeeper's eyes and fabric details pop.
- **35B-A3B s202**（9.87s）：Portrait of a beekeeper wearing protective gear.｜WB neutral｜曝光 slightly underexposed｜反差 low
  - 問題：The image is slightly underexposed, making the eyes and face look dark.; The contrast is low, giving the photo a flat, muddy look.; The background is somewhat hazy and lacks separation from the subject.; The colors are a bit dull and desaturated.
  - 數值：Exposure +0.35, Contrast +20, Highlights -15, Shadows +15, Whites +5, Blacks -10, Temp +5, Tint -5, Vibrance +15, Clarity +10, Dehaze +15, LumGreen -10
  - intent：I aim to create a crisp, vibrant portrait that highlights the beekeeper's eyes and gear while making the subject stand out from a clean, less-hazy background.
- **PE-I2I s101**（9.39s）：a person (young woman) wearing a checkered sun-protection hat/hood with the fabric pulled up over the lower half of her face, only her eyes, nose bridge, and forehead visible, with a few stray hairs falling across her forehead｜WB warm / orange-yellow｜曝光 slightly overexposed｜反差 low
  - 問題：the warm orange-yellow color cast makes skin tones look orangey; the face is slightly overexposed with bright highlights on the forehead and nose bridge; the overall image is a bit flat and soft; the checkered fabric is a dominant element whose pattern could be rendered more crisply
  - 數值：Exposure -0.3, Contrast +10, Highlights -15, Whites -10, Blacks -10, Temp -12, Clarity +8, Texture +8
  - intent：correct the warm orange-yellow color cast to neutral natural skin tones, recover the overexposed facial highlights, and add slight contrast and clarity so the checkered fabric and skin texture render crisply, while keeping the photo's natural outdoor mood and not over-processing it.
- **PE-I2I s202**（9.94s）：a young person (girl) wearing a checkered sun-protective hat/hood with the fabric pulled up over the lower half of her face, only her eyes, brows and forehead visible, with fine stray hairs across the forehead, a faint squinting/wrinkled brow expression, warm late-afternoon sunlight hitting the skin from the front-left, background a soft out-of-focus green-and-tan bokeh (outdoor field), shallow depth of field.｜WB warm / orange-yellow｜曝光 slightly overexposed｜反差 high
  - 問題：the eyes look dull and slightly sun-squinted, with a tired, strained expression; the warm color cast is strong and the skin looks reddish-orange from the sunlight; the exposure is a bit bright, with highlight detail on the forehead and nose area; the background is extremely blurred with a slight haze/fog feel, reducing clarity; overall the photo feels a little hazy and low in clarity, with the fine details of the checkered fabric and hairs slightly soft.
  - 數值：Exposure -0.4, Contrast +10, Highlights -15, Shadows +5, Whites -8, Blacks -10, Temp -6, Tint -4, Vibrance +8, Clarity +12, Dehaze +8, Texture +8
  - intent：correct the overexposure and strong warm color cast, restore a natural, clean skin tone and clear eye detail, and add clarity and texture so the photo reads crisp and transparent while preserving the warm outdoor mood.

### food_bluecast_dark

- **35B-A3B s101**（11.35s）：A dimly lit interior dining scene looking out onto a garden and lake through a large window.｜WB cool / blue｜曝光 underexposed｜反差 low
  - 問題：The photo is significantly underexposed, lacking detail in the shadows.; There is a strong blue colour cast, likely from a mix of tungsten light inside and overcast daylight outside.; The shadows on the curtains and table are crushed and muddy.; The greens outside look dull and slightly cyan due to the cool cast.
  - 數值：Exposure +1.5, Contrast +15, Highlights -10, Shadows +60, Whites +5, Blacks -15, Temp +25, Tint -10, Vibrance +15, Clarity +10, Dehaze +15, HueGreen -15, SatGreen +10
  - intent：Brighten the interior details and remove the unnatural blue cast to create a realistic, warm, and inviting atmosphere.
- **35B-A3B s202**（9.88s）：A dimly lit interior dining area looking out onto a garden and lake.｜WB cool / blue｜曝光 underexposed｜反差 low
  - 問題：The image is significantly underexposed, losing detail in the curtains and interior.; There is a strong blue color cast, likely due to twilight conditions or camera white balance.; The image appears flat (low contrast) and slightly hazy.; The greens outside are dull and muddy.
  - 數值：Exposure +1.5, Contrast +20, Highlights -15, Shadows +40, Whites +10, Blacks -10, Temp +15, Tint +5, Vibrance +15, Clarity +15, Dehaze +10, HueGreen +10, SatGreen +15, LumBlue -10
  - intent：Brighten the scene to reveal interior details while neutralizing the blue twilight cast and revitalizing the lush greenery outside.
- **PE-I2I s101**（9.31s）：a dim interior dining scene: a table set for two with plates, cutlery, mugs and glasses of red drink, a small stained-glass table lamp, two chairs, floral curtains at both sides, and a large multi-pane window overlooking a green lawn, trees and water under an overcast sky｜WB cool / blue｜曝光 underexposed｜反差 low
  - 問題：overall exposure is too dark, interior and foreground table area underexposed with lost shadow detail; cool blue colour cast from the overcast window light; low contrast giving a flat, washed look; interior details in deep shadow (table setting, chairs, curtains)
  - 數值：Exposure +1.2, Contrast +20, Highlights -15, Shadows +40, Blacks -15, Temp +12, Vibrance +15, Clarity +10, Dehaze +10, Texture +5
  - intent：lift this dim, cool-casted interior photo into a properly exposed, neutral-to-warm natural look with recovered shadow detail and clean contrast, while keeping the calm overcast lakeside mood.
- **PE-I2I s202**（10.11s）：a dimly lit dining room interior centered on a table set with plates, cutlery, mugs, glasses of red drink, and a stained-glass table lamp, in front of a large wooden multi-pane window overlooking a lawn, trees, and a lake, with dark floral curtains at both sides and wooden chairs on either side of the table｜WB cool / blue｜曝光 underexposed｜反差 low
  - 問題：the whole image is significantly underexposed and murky, with the interior foreground nearly black and the window view washed out; a cool blue color cast over the entire frame; flat, low contrast with crushed dark shadows and no visible detail in the curtains, tablecloth, and window frames; the window view (lawn, trees, lake) looks hazy and washed out; the table lamp, drinks, and tabletop details are barely visible in the darkness
  - 數值：Exposure +1.6, Contrast +20, Highlights -15, Shadows +35, Blacks -15, Temp +10, Vibrance +15, Clarity +15, Dehaze +10, Texture +10
  - intent：brighten the underexposed interior to a clean, naturally exposed level while removing the cool blue cast, restoring a neutral warm-white balance, opening the shadowed curtains, tablecloth, and window frames to reveal their detail, and keeping the lake-and-lawn view natural and clear, so the scene reads as a softly lit, inviting dining room with a gentle evening mood.

