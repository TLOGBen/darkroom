| photo | 秒 | Qwen 尺寸 | flow 程式→Qwen p50/p95/p99 全圖 | flow p95 臉 | 各細節區 flow p95 | 錯位誤差 p99（a=100%）各區 | SSIM/MAE Qwen vs 原圖 |
|---|---|---|---|---|---|---|---|
| portrait_laughing | 153s | 928x1120 | 3.81/9.45/10.18 | 9.69 | eyes 8.81, hair 6.30, teeth 10.03 | eyes 94.7, hair 70.7, teeth 136.3 | 0.492/21.4 |
| portrait_oldman | 149s | 1248x832 | 0.37/2.76/3.54 | 2.59 | eyes 2.43, hair 3.60, mouth 1.88 | eyes 57.3, hair 65.8, mouth 42.8 | 0.677/15.0 |
| portrait_studio | 127s | 896x1152 | 0.04/6.05/8.42 | 4.11 | eye 4.02, hair 3.52, zip 6.14 | eye 77.0, hair 45.9, zip 41.9 | 0.770/11.6 |
| landscape_lighthouse | 134s | 1376x768 | 0.50/46.77/215.61 | 6.17 | tower 7.62, waves 1.09, rock 1.15 | tower 54.2, waves 48.4, rock 19.5 | 0.718/31.9 |
| fog_karst | 145s | 1248x832 | 2.26/4.16/5.55 | 3.04 | crag 3.15, fog 3.94, fields 2.97 | crag 73.9, fog 35.7, fields 44.2 | 0.412/23.4 |
