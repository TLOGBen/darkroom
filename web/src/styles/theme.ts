/**
 * darkroom 的 MUI 主題（MUI v7，CSS theme variables＋深色／淺色兩套 colorSchemes）。
 *
 * 設計依據：web/DESIGN.md。一句話：介面是中性灰（R = G = B），照片是畫面上唯一有顏色的東西；
 * 只有四個低彩度語意色（tweak 琥珀＝你的微調、clamp＝被夾住、err、ok）出現在小記號、細線與文字上。
 *
 * 資料怎麼流：
 *   1. `tokens`（本檔）＝數值的 TypeScript 版，跟 `_tokens.scss` 的 Sass map 同名同值。
 *      MUI 需要真正的色碼來算 palette（contrastText、channel、alpha），所以 palette 讀這裡。
 *   2. 元件的 styleOverrides 一律寫 `var(--dr-*)`（由 global.scss 輸出），不寫死色碼：
 *      深淺色切換時 MUI 只改 <html data-theme>，--dr-* 跟著同一個屬性切換，元件不用重新產生樣式。
 *      → 前提：main.tsx 一定要 import './styles/global.scss'。
 *   3. 主題切換：`cssVariables.colorSchemeSelector = '[data-theme="%s"]'`，與 _tokens.scss 的
 *      `:root[data-theme='light']` 同一個屬性。ThemeProvider 用 `defaultMode="dark"`（修圖預設深色）。
 *
 * 只 import @mui/material（規劃 §2：MUI 自帶 emotion，不另外拉樣式系統）。
 */
import { createTheme } from '@mui/material';
import type { ThemeOptions } from '@mui/material';

// ---------------------------------------------------------------------------------------------------------------------
// 型別擴充：自訂 palette 色（tweak、clamp、canvas）與 Typography 變體（readout、num、mono）
// ---------------------------------------------------------------------------------------------------------------------

declare module '@mui/material/styles' {
  interface Palette {
    /** 琥珀：你的微調（滑桿差值段、已微調的點、未儲存提示）。 */
    tweak: Palette['primary'];
    /** 夾值：數值超出範圍被夾住（方形把手、端蓋、數字）。 */
    clamp: Palette['primary'];
    /** 照片底色三段；跟主題無關，深淺色相同。 */
    canvas: { dark: string; black: string; mid: string };
  }
  interface PaletteOptions {
    tweak?: PaletteOptions['primary'];
    clamp?: PaletteOptions['primary'];
    canvas?: { dark: string; black: string; mid: string };
  }
  interface TypographyVariants {
    /** 強度讀數：整個介面唯一的大數字。 */
    readout: TypographyVariants['body1'];
    /** 會變動的數字：滑桿數值、尺寸、計數。 */
    num: TypographyVariants['body1'];
    /** 檔案路徑、xmp 鍵名。 */
    mono: TypographyVariants['body1'];
  }
  interface TypographyVariantsOptions {
    readout?: TypographyVariantsOptions['body1'];
    num?: TypographyVariantsOptions['body1'];
    mono?: TypographyVariantsOptions['body1'];
  }
}

declare module '@mui/material/Typography' {
  interface TypographyPropsVariantOverrides {
    readout: true;
    num: true;
    mono: true;
  }
}

// ---------------------------------------------------------------------------------------------------------------------
// tokens：跟 _tokens.scss 一一對應（改一邊就改另一邊）
// ---------------------------------------------------------------------------------------------------------------------

export const tokens = {
  color: {
    dark: {
      bgFrame: '#121212',
      bgPanel: '#191919',
      bgControl: '#202020',
      bgHover: '#2a2a2a',
      bgWell: '#121212',
      line: 'rgba(255, 255, 255, 0.07)',
      lineStrong: 'rgba(255, 255, 255, 0.12)',
      text: '#e6e6e6',
      text2: '#a9a9a9',
      text3: '#8a8a8a',
      selectBg: '#e6e6e6',
      selectFg: '#141414',
      track: '#3a3a3a',
      track2: '#4a4a4a',
      thumb: '#ececec',
      tweak: '#d9a85b',
      clamp: '#d27a7a',
      err: '#e06b6b',
      onErr: '#141414',
      ok: '#8fbf93',
    },
    light: {
      bgFrame: '#dedede',
      bgPanel: '#ebebeb',
      bgControl: '#f5f5f5',
      bgHover: '#d9d9d9',
      bgWell: '#ffffff',
      line: 'rgba(0, 0, 0, 0.08)',
      lineStrong: 'rgba(0, 0, 0, 0.16)',
      text: '#1c1c1c',
      text2: '#4d4d4d',
      text3: '#5f5f5f',
      selectBg: '#1c1c1c',
      selectFg: '#ffffff',
      track: '#c2c2c2',
      track2: '#a3a3a3',
      thumb: '#262626',
      tweak: '#8a5a12',
      clamp: '#a83e3e',
      err: '#b3261e',
      onErr: '#ffffff',
      ok: '#2f6b35',
    },
    canvas: { dark: '#151515', black: '#000000', mid: '#4a4a4a' },
    /** HSL 列標籤前的 6px 色點（舊 logic.js HUE_DOTS）。只用在色點，不上軌道。 */
    hue: {
      Red: '#e04848',
      Orange: '#e08a3c',
      Yellow: '#d9c43a',
      Green: '#4fb24f',
      Aqua: '#3fb8a8',
      Blue: '#4a7fe0',
      Purple: '#8c5fd6',
      Magenta: '#d65aa8',
    },
    /** 品牌暗房紅：只給 logo／banner／bootstrap 歡迎頁，編輯器裡不用。 */
    safelight: '#c0392b',
  },
  font: {
    ui: "'Segoe UI Variable Text', 'Segoe UI', 'Noto Sans TC', 'Microsoft JhengHei UI', 'Noto Sans CJK TC', 'PingFang TC', system-ui, sans-serif",
    num: "'Bahnschrift', 'DIN Alternate', 'Segoe UI Variable Small', 'Segoe UI', system-ui, sans-serif",
    mono: "'Cascadia Mono', 'Consolas', 'DejaVu Sans Mono', ui-monospace, monospace",
    numStretch: '87.5%',
  },
  size: { controlH: 26, rowH: 24, sectionH: 34, barH: 44, toolbarH: 38, libW: 280, slW: 390 },
  radius: { xs: 2, sm: 3, md: 5, lg: 8 },
  motion: { fast: 120, panel: 180, ease: 'cubic-bezier(0.2, 0, 0, 1)' },
  breakpoint: { narrow: 960, medium: 1280 },
} as const;

/** `var(--dr-<name>)`：元件樣式用這個取顏色，深淺色由 <html data-theme> 切換。 */
const v = (name: string) => `var(--dr-${name})`;

const fast = `${tokens.motion.fast}ms ${tokens.motion.ease}`;
const focusRing = { outline: `2px solid ${v('focus')}`, outlineOffset: 1 };
const numFace = {
  fontFamily: tokens.font.num,
  fontVariantNumeric: 'tabular-nums',
  fontStretch: tokens.font.numStretch,
} as const;

// ---------------------------------------------------------------------------------------------------------------------
// palette：MUI 內部計算用（contained 按鈕、Checkbox、alpha…）
// ---------------------------------------------------------------------------------------------------------------------

type Scheme = (typeof tokens.color)['dark'] | (typeof tokens.color)['light'];

function paletteFor(c: Scheme, mode: 'dark' | 'light') {
  return {
    // primary＝「選取／主要動作」：深色是白底黑字、淺色是黑底白字。刻意不用任何色相。
    primary: { main: c.selectBg, contrastText: c.selectFg },
    secondary: { main: c.text2, contrastText: c.selectFg },
    // info 也是中性灰：介面裡沒有「資訊藍」。
    info: { main: c.text2, contrastText: c.selectFg },
    warning: { main: c.tweak, contrastText: mode === 'dark' ? '#141414' : '#ffffff' },
    error: { main: c.err, contrastText: c.onErr },
    success: { main: c.ok, contrastText: mode === 'dark' ? '#141414' : '#ffffff' },
    tweak: { main: c.tweak, contrastText: mode === 'dark' ? '#141414' : '#ffffff' },
    clamp: { main: c.clamp, contrastText: '#ffffff' },
    canvas: tokens.color.canvas,
    background: { default: c.bgFrame, paper: c.bgPanel },
    text: { primary: c.text, secondary: c.text2, disabled: c.text3 },
    divider: c.line,
    action: {
      active: c.text,
      hover: c.bgHover,
      selected: mode === 'dark' ? 'rgba(255, 255, 255, 0.07)' : 'rgba(0, 0, 0, 0.07)',
      focus: mode === 'dark' ? 'rgba(255, 255, 255, 0.12)' : 'rgba(0, 0, 0, 0.12)',
      disabledOpacity: 0.4,
      hoverOpacity: 0.06,
    },
  };
}

// ---------------------------------------------------------------------------------------------------------------------
// components：外觀全部在這裡；DESIGN.md「元件規則」一節是這些覆寫的說明
// ---------------------------------------------------------------------------------------------------------------------

const components: ThemeOptions['components'] = {
  // 沒有漣漪：動效只回應操作、而且要安靜；漣漪是 Material 的招牌，跟修圖工具的語氣不合。
  MuiButtonBase: {
    defaultProps: { disableRipple: true, disableTouchRipple: true },
    styleOverrides: {
      root: { '&.Mui-focusVisible': focusRing },
    },
  },

  // ---- Button：一種按鈕、亮度分輕重，不用色相 -------------------------------------------------------------------
  MuiButton: {
    defaultProps: { variant: 'outlined', size: 'small', disableElevation: true },
    styleOverrides: {
      root: {
        minWidth: 0,
        height: tokens.size.controlH,
        padding: '0 10px',
        borderRadius: tokens.radius.md,
        fontSize: 13,
        fontWeight: 400,
        lineHeight: '24px',
        textTransform: 'none',
        whiteSpace: 'nowrap',
        transition: `background-color ${fast}, border-color ${fast}, color ${fast}`,
        '&.Mui-disabled': { opacity: 0.4 },
        // 切換鈕（A/B、裁切、縮圖格…）按下＝選取色，跟 preset 樹的「目前」同一個語言。
        '&[aria-pressed="true"]': {
          backgroundColor: v('select-bg'),
          borderColor: v('select-bg'),
          color: v('select-fg'),
        },
        // 按下狀態滑過時仍是選取色（只稍微亮一點）：outlined／text 的 :hover 會把底色換成 bg-hover，
        // 字色卻還是 select-fg（深色），變成深字配深底、字看不見。屬性＋偽類的權重高過單一 :hover，所以放這裡就蓋得過。
        '&[aria-pressed="true"]:hover': {
          backgroundColor: v('select-bg'),
          borderColor: v('select-bg'),
          color: v('select-fg'),
          filter: 'brightness(1.08)',
        },
        '& .MuiButton-startIcon': { marginLeft: -2, marginRight: 6 },
        '& .MuiButton-startIcon > *:nth-of-type(1), & .MuiButton-endIcon > *:nth-of-type(1)': { fontSize: 15 },
        variants: [
          // 危險動作（刪除匯出預設、清除編輯）：紅底，只在對話框的確認鈕用。
          {
            props: { variant: 'contained', color: 'error' },
            style: {
              backgroundColor: v('err'),
              color: v('on-err'),
              '&:hover': { backgroundColor: v('err'), filter: 'brightness(1.08)' },
            },
          },
        ],
      },
      // 預設：灰底細框
      outlined: {
        color: v('text'),
        backgroundColor: v('bg-control'),
        borderColor: v('line-strong'),
        '&:hover': { backgroundColor: v('bg-hover'), borderColor: v('line-strong') },
        '&.Mui-disabled': { color: v('text'), borderColor: v('line-strong') },
      },
      // 主要動作（一個畫面最多一顆：匯出、套用、儲存設定）：選取色實心
      contained: {
        color: v('select-fg'),
        backgroundColor: v('select-bg'),
        fontWeight: 600,
        boxShadow: 'none',
        '&:hover': { backgroundColor: v('select-bg'), boxShadow: 'none', filter: 'brightness(1.1)' },
        '&.Mui-disabled': { color: v('select-fg'), backgroundColor: v('select-bg') },
      },
      // 安靜鈕：沒有底、沒有框，滑過才浮出
      text: {
        color: v('text-2'),
        '&:hover': { backgroundColor: v('bg-hover'), color: v('text') },
        '&.Mui-disabled': { color: v('text-2') },
      },
    },
  },

  MuiIconButton: {
    defaultProps: { size: 'small' },
    styleOverrides: {
      root: {
        width: tokens.size.controlH,
        height: tokens.size.controlH,
        padding: 0,
        borderRadius: tokens.radius.md,
        color: v('text-2'),
        fontSize: 15,
        transition: `background-color ${fast}, color ${fast}`,
        '&:hover': { backgroundColor: v('bg-hover'), color: v('text') },
        '&.Mui-disabled': { color: v('text-2'), opacity: 0.4 },
        '&[aria-pressed="true"]': { backgroundColor: v('select-bg'), color: v('select-fg') },
        '& svg': { fontSize: 15 },
      },
    },
  },

  // 分段鈕（照片底色、裁切比例、色相／飽和度／明度）：相鄰共用邊線，選取＝選取色。
  MuiToggleButtonGroup: {
    defaultProps: { size: 'small' },
  },
  MuiToggleButton: {
    styleOverrides: {
      root: {
        height: 22,
        padding: '0 10px',
        fontSize: 12,
        lineHeight: '20px',
        textTransform: 'none',
        color: v('text-2'),
        backgroundColor: v('bg-panel'),
        borderColor: v('line-strong'),
        borderRadius: 4,
        '&:hover': { backgroundColor: v('bg-hover'), color: v('text') },
        '&.Mui-selected, &.Mui-selected:hover': {
          backgroundColor: v('select-bg'),
          borderColor: v('select-bg'),
          color: v('select-fg'),
        },
      },
    },
  },

  // ---- Slider：整個設計唯一花力氣的地方 --------------------------------------------------------------------------
  //
  // 2px 軌道、10px 中性把手。不用 MUI 的 track（從最小值長出來的那條），改用三個 CSS 變數畫：
  //   --dr-base：preset×強度落在哪（1px×8px 的刻度）
  //   --dr-lo ～ --dr-hi：從 preset 落點到把手的那段＝你的微調，琥珀色
  // 這三個值由元件用 style 寫在 Slider 根元素上（0%～100%，由 domain/edit 的 sliderVars 算，舊 logic.js 同名函式）。
  // MUI 的 rail 與 thumb 都用 left:% 定位在根元素裡，跟這三個百分比是同一個座標系，所以刻度一定對得上把手中心。
  //
  // 狀態 className（元件依資料加上）：
  //   dr-bipolar（min<0<max，畫中點刻度）、dr-adjusted（有微調：把手琥珀）、
  //   dr-clamped＋dr-at-min／dr-at-max（被夾住：方形灰把手＋該端端蓋）、dr-strength（強度轉盤）。
  MuiSlider: {
    defaultProps: { size: 'small', track: false, valueLabelDisplay: 'off' },
    styleOverrides: {
      root: {
        '--dr-base': '50%',
        '--dr-lo': '50%',
        '--dr-hi': '50%',
        height: 2,
        padding: '9px 0',
        borderRadius: 0,
        color: v('thumb'),
        cursor: 'pointer',
        // preset 落點刻度
        '&::before': {
          content: '""',
          position: 'absolute',
          left: 'var(--dr-base)',
          top: '50%',
          width: 1,
          height: 8,
          transform: 'translate(-0.5px, -50%)',
          backgroundColor: v('text-3'),
          pointerEvents: 'none',
          zIndex: 1,
        },
        // 雙向滑桿的中點刻度
        '&.dr-bipolar::after': {
          content: '""',
          position: 'absolute',
          left: '50%',
          top: '50%',
          width: 1,
          height: 6,
          transform: 'translate(-0.5px, -50%)',
          backgroundColor: v('track-2'),
          pointerEvents: 'none',
        },
        '&.dr-adjusted .MuiSlider-thumb': { backgroundColor: v('tweak') },
        '&.dr-clamped .MuiSlider-thumb': { borderRadius: 1, backgroundColor: v('text-2') },
        '&.dr-clamped .MuiSlider-rail::after': {
          content: '""',
          position: 'absolute',
          top: -4,
          width: 2,
          height: 10,
          backgroundColor: v('text-2'),
        },
        '&.dr-clamped.dr-at-max .MuiSlider-rail::after': { right: 0 },
        '&.dr-clamped.dr-at-min .MuiSlider-rail::after': { left: 0 },
        '&.Mui-disabled': { color: v('thumb'), opacity: 0.4, cursor: 'default' },

        // 強度轉盤（0～200%）：較高的點擊區；元件傳 marks=[{value:0,label:'0'},{value:100,label:'100'},{value:200,label:'200'}]，
        // 第二個 mark（data-index="1"，100%）畫成長刻度；每 25% 的小刻度由元件的 CSS module 用背景重複線畫。
        // 軌道左半 track、右半 track-2（>100% 那半比較亮），0..目前值 用 text-2 畫，不用琥珀（強度不是微調）。
        '&.dr-strength': {
          padding: '17px 0',
          '&::before': { display: 'none' },
          '& .MuiSlider-rail': {
            backgroundColor: 'transparent',
            backgroundImage: [
              `linear-gradient(90deg, transparent var(--dr-lo), ${v('text-2')} var(--dr-lo), ${v('text-2')} var(--dr-hi), transparent var(--dr-hi))`,
              `linear-gradient(90deg, ${v('track')} 50%, ${v('track-2')} 50%)`,
            ].join(', '),
          },
          '& .MuiSlider-thumb': { width: 12, height: 14, borderRadius: tokens.radius.xs },
          '& .MuiSlider-mark': { width: 1, height: 6, top: 'calc(50% + 6px)', backgroundColor: v('text-3') },
          '& .MuiSlider-mark[data-index="1"]': { height: 22, top: '50%', backgroundColor: v('text-2') },
        },
      },
      rail: {
        height: 2,
        opacity: 1,
        borderRadius: 0,
        backgroundColor: v('track'),
        backgroundImage: `linear-gradient(90deg, transparent var(--dr-lo), ${v('tweak')} var(--dr-lo), ${v('tweak')} var(--dr-hi), transparent var(--dr-hi))`,
      },
      thumb: {
        width: 10,
        height: 10,
        zIndex: 2,
        backgroundColor: v('thumb'),
        boxShadow: '0 0 0 1px rgba(0, 0, 0, 0.6)',
        // 只動 transform：拖動時把手位置不做動畫（預覽要跟手），滑過／按住才放大 1.25 倍。
        transition: `transform ${fast}`,
        '&::before': { boxShadow: 'none' },
        '&:hover, &.Mui-active': {
          boxShadow: '0 0 0 1px rgba(0, 0, 0, 0.6)',
          transform: 'translate(-50%, -50%) scale(1.25)',
        },
        '&.Mui-focusVisible': {
          boxShadow: `0 0 0 2px ${v('focus')}`,
          outline: 'none',
        },
      },
      mark: { backgroundColor: v('text-3'), width: 1, height: 6 },
      markActive: { backgroundColor: v('text-3'), opacity: 1 },
      markLabel: {
        ...numFace,
        top: 30,
        fontSize: 10,
        color: v('text-3'),
      },
      valueLabel: {
        ...numFace,
        fontSize: 11,
        backgroundColor: v('bg-control'),
        color: v('text'),
        borderRadius: tokens.radius.sm,
      },
    },
  },

  // ---- Paper：面板是平的；只有浮在上面的東西（選單、對話框、提示）才有影子 ---------------------------------------
  MuiPaper: {
    defaultProps: { elevation: 0 },
    styleOverrides: {
      root: {
        // MUI 深色模式會依 elevation 疊一層白色漸層，這會讓灰階不再是 R=G=B，關掉。
        backgroundImage: 'none',
        backgroundColor: v('bg-panel'),
        color: v('text'),
      },
      outlined: { borderColor: v('line') },
      rounded: { borderRadius: tokens.radius.lg },
    },
  },

  MuiPopover: {
    styleOverrides: {
      paper: {
        backgroundColor: v('bg-control'),
        border: `1px solid ${v('line-strong')}`,
        borderRadius: tokens.radius.lg,
        boxShadow: v('shadow-float'),
      },
    },
  },
  MuiMenu: {
    styleOverrides: {
      paper: {
        minWidth: 160,
        backgroundColor: v('bg-control'),
        border: `1px solid ${v('line-strong')}`,
        borderRadius: tokens.radius.lg,
        boxShadow: v('shadow-float'),
      },
      list: { padding: 4 },
    },
  },
  MuiMenuItem: {
    styleOverrides: {
      root: {
        minHeight: 28,
        padding: '0 10px',
        borderRadius: 4,
        fontSize: 13,
        '&:hover, &.Mui-focusVisible': { backgroundColor: v('bg-hover'), outline: 'none' },
        '&.Mui-selected, &.Mui-selected:hover': { backgroundColor: v('select-soft') },
      },
    },
  },

  // 右欄的分區（基本、曲線、HSL…）：標題是一行字＋一條細線，不是色塊。
  MuiAccordion: {
    defaultProps: { disableGutters: true, elevation: 0, square: true },
    styleOverrides: {
      root: {
        backgroundColor: 'transparent',
        borderBottom: `1px solid ${v('line')}`,
        '&::before': { display: 'none' },
      },
    },
  },
  MuiAccordionSummary: {
    styleOverrides: {
      root: {
        minHeight: tokens.size.sectionH,
        padding: '0 12px',
        gap: 6,
        fontWeight: 600,
        // 箭頭放左邊，跟 preset 樹的展開箭頭同一側
        flexDirection: 'row-reverse',
        '&:hover': { backgroundColor: v('bg-hover') },
        '&.Mui-focusVisible': { ...focusRing, outlineOffset: -2, backgroundColor: 'transparent' },
      },
      content: { margin: 0, alignItems: 'center', gap: 6 },
      expandIconWrapper: {
        color: v('text-3'),
        transition: `transform ${fast}`,
        '&.Mui-expanded': { transform: 'rotate(90deg)' },
      },
    },
  },
  MuiAccordionDetails: {
    styleOverrides: { root: { padding: '2px 12px 10px' } },
  },

  // ---- Tabs：設定頁的分頁＝細底線；className dr-segmented＝滑桿區內的小分段（例如 HSL 的 色相／飽和度／明度） ------
  MuiTabs: {
    defaultProps: { textColor: 'inherit' },
    styleOverrides: {
      root: {
        minHeight: 32,
        borderBottom: `1px solid ${v('line')}`,
        '&.dr-segmented': {
          minHeight: 22,
          borderBottom: 'none',
          margin: '6px 0 4px',
          '& .MuiTabs-indicator': { display: 'none' },
          '& .MuiTab-root': {
            minHeight: 22,
            height: 22,
            padding: '0 10px',
            fontSize: 12,
            border: `1px solid ${v('line-strong')}`,
            marginLeft: -1,
            backgroundColor: v('bg-panel'),
            color: v('text-2'),
          },
          '& .MuiTab-root:first-of-type': { marginLeft: 0, borderRadius: '4px 0 0 4px' },
          '& .MuiTab-root:last-of-type': { borderRadius: '0 4px 4px 0' },
          '& .MuiTab-root.Mui-selected': {
            backgroundColor: v('select-bg'),
            borderColor: v('select-bg'),
            color: v('select-fg'),
          },
        },
      },
      indicator: { height: 2, backgroundColor: v('text') },
    },
  },
  MuiTab: {
    styleOverrides: {
      root: {
        minHeight: 32,
        minWidth: 0,
        padding: '0 12px',
        fontSize: 13,
        fontWeight: 400,
        textTransform: 'none',
        color: v('text-2'),
        opacity: 1,
        transition: `color ${fast}`,
        '&:hover': { color: v('text') },
        '&.Mui-selected': { color: v('text') },
        '&.Mui-focusVisible': { ...focusRing, outlineOffset: -2 },
      },
    },
  },

  // ---- 輸入框：26px 高、凹下去的井、標籤寫在框外（不用浮動標籤） ------------------------------------------------
  MuiTextField: {
    defaultProps: { size: 'small', variant: 'outlined' },
  },
  MuiOutlinedInput: {
    styleOverrides: {
      root: {
        backgroundColor: v('bg-well'),
        borderRadius: tokens.radius.md,
        fontSize: 13,
        color: v('text'),
        '& .MuiOutlinedInput-notchedOutline': { borderColor: v('line-strong') },
        '&:hover .MuiOutlinedInput-notchedOutline': { borderColor: v('text-3') },
        '&.Mui-focused .MuiOutlinedInput-notchedOutline': { borderColor: v('focus'), borderWidth: 1 },
        '&.Mui-error .MuiOutlinedInput-notchedOutline': { borderColor: v('err') },
        '&.Mui-disabled': { opacity: 0.4 },
        '&.Mui-disabled .MuiOutlinedInput-notchedOutline': { borderColor: v('line-strong') },
      },
      input: {
        height: 18,
        padding: '4px 8px',
        '&::placeholder': { color: v('text-3'), opacity: 1 },
        // 數字欄靠右，跟滑桿數值同一條對齊線
        '&[type="number"]': { ...numFace, textAlign: 'right' },
      },
      multiline: { padding: '4px 8px' },
      inputMultiline: { padding: 0 },
      adornedStart: { paddingLeft: 8 },
      adornedEnd: { paddingRight: 8 },
    },
  },
  MuiInputAdornment: {
    styleOverrides: { root: { color: v('text-3'), fontSize: 12 } },
  },
  MuiSelect: {
    styleOverrides: {
      select: { minHeight: 0, lineHeight: '18px' },
      icon: { color: v('text-3'), fontSize: 18 },
    },
  },
  MuiFormLabel: {
    styleOverrides: {
      root: {
        fontSize: 12,
        color: v('text-2'),
        // 對焦時標籤不換色：顏色只留給狀態，對焦已經有框
        '&.Mui-focused': { color: v('text-2') },
        '&.Mui-error': { color: v('err') },
      },
    },
  },
  MuiInputLabel: {
    // 規則是不用浮動標籤；萬一有人用了 label，也讓它安靜一點。
    styleOverrides: { root: { fontSize: 12, color: v('text-2'), '&.Mui-focused': { color: v('text-2') } } },
  },
  MuiFormHelperText: {
    styleOverrides: {
      root: {
        margin: '4px 0 0',
        fontSize: 12,
        lineHeight: 1.45,
        color: v('text-3'),
        '&.Mui-error': { color: v('err') },
      },
    },
  },
  MuiCheckbox: {
    defaultProps: { size: 'small' },
    styleOverrides: {
      root: { padding: 4, color: v('text-3'), '&.Mui-checked': { color: v('text') } },
    },
  },
  MuiSwitch: {
    defaultProps: { size: 'small' },
    styleOverrides: {
      switchBase: {
        color: v('text-2'),
        '&.Mui-checked': { color: v('select-fg') },
        '&.Mui-checked + .MuiSwitch-track': { backgroundColor: v('select-bg'), opacity: 1 },
      },
      track: { backgroundColor: v('track-2'), opacity: 1 },
    },
  },

  // ---- Dialog：置中、560 寬、內容自己捲；820×600 的視窗也要每個控制項都碰得到 ------------------------------------
  MuiDialog: {
    defaultProps: { maxWidth: 'sm', transitionDuration: { enter: tokens.motion.panel, exit: tokens.motion.fast } },
    styleOverrides: {
      // 只改對話框自己的背幕（選單的背幕是透明的，不受影響）
      root: { '& .MuiBackdrop-root': { backgroundColor: v('scrim') } },
      paper: {
        margin: 16,
        maxHeight: 'calc(100% - 32px)',
        backgroundColor: v('bg-panel'),
        backgroundImage: 'none',
        border: `1px solid ${v('line-strong')}`,
        borderRadius: tokens.radius.lg,
        boxShadow: v('shadow-dialog'),
      },
      paperWidthSm: { maxWidth: 560 },
    },
  },
  MuiDialogTitle: {
    styleOverrides: {
      root: { padding: '12px 16px 8px', fontSize: 15, fontWeight: 600, lineHeight: 1.3 },
    },
  },
  MuiDialogContent: {
    styleOverrides: { root: { padding: '4px 16px 8px' } },
  },
  MuiDialogActions: {
    styleOverrides: {
      root: {
        padding: '10px 16px 14px',
        gap: 8,
        borderTop: `1px solid ${v('line')}`,
        '& > :not(style) ~ :not(style)': { marginLeft: 0 },
      },
    },
  },

  MuiTooltip: {
    defaultProps: { enterDelay: 500, disableInteractive: true },
    styleOverrides: {
      tooltip: {
        fontSize: 12,
        lineHeight: 1.45,
        padding: '4px 8px',
        color: v('text'),
        backgroundColor: v('bg-control'),
        border: `1px solid ${v('line-strong')}`,
        borderRadius: tokens.radius.sm,
        boxShadow: v('shadow-float'),
      },
    },
  },
  // 提示訊息（toast）：反轉色的一塊，底部置中；錯誤是紅底白字。
  MuiSnackbarContent: {
    styleOverrides: {
      root: {
        minWidth: 0,
        padding: '4px 14px',
        fontSize: 12,
        color: v('select-fg'),
        backgroundColor: v('select-bg'),
        borderRadius: 6,
        boxShadow: v('shadow-float'),
      },
    },
  },
  MuiDivider: {
    styleOverrides: { root: { borderColor: v('line') } },
  },
  MuiLinearProgress: {
    styleOverrides: {
      root: { height: 2, backgroundColor: v('track') },
      bar: { backgroundColor: v('text-2') },
    },
  },
  MuiTypography: {
    defaultProps: {
      variantMapping: { readout: 'span', num: 'span', mono: 'code' },
    },
  },
};

// ---------------------------------------------------------------------------------------------------------------------
// createTheme
// ---------------------------------------------------------------------------------------------------------------------

export const theme = createTheme({
  cssVariables: {
    // 跟 _tokens.scss 的 :root[data-theme='light'] 同一個屬性；MUI 的 InitColorSchemeScript 也寫這個屬性。
    colorSchemeSelector: '[data-theme="%s"]',
  },
  defaultColorScheme: 'dark',
  colorSchemes: {
    dark: { palette: paletteFor(tokens.color.dark, 'dark') },
    light: { palette: paletteFor(tokens.color.light, 'light') },
  },
  // theme.spacing(n) = 4n px：跟 _tokens.scss 的 4px 格一致（MUI 預設是 8）。
  spacing: 4,
  shape: { borderRadius: tokens.radius.md },
  breakpoints: {
    // md＝窄視窗分界（960）、lg＝中等視窗分界（1280），跟 _tokens.scss 的 $dr-bp-* 一致。
    values: { xs: 0, sm: 600, md: tokens.breakpoint.narrow, lg: tokens.breakpoint.medium, xl: 1600 },
  },
  typography: {
    fontFamily: tokens.font.ui,
    fontSize: 13,
    htmlFontSize: 16,
    fontWeightRegular: 400,
    fontWeightMedium: 500,
    fontWeightBold: 600,
    // 工具介面沒有大標題；h1 只給設定頁頁名，h2 給設定頁區塊與對話框標題。
    h1: { fontSize: '20px', fontWeight: 600, lineHeight: 1.3 },
    h2: { fontSize: '15px', fontWeight: 600, lineHeight: 1.3 },
    h3: { fontSize: '13px', fontWeight: 600, lineHeight: 1.45 },
    h4: { fontSize: '13px', fontWeight: 600, lineHeight: 1.45 },
    h5: { fontSize: '13px', fontWeight: 600, lineHeight: 1.45 },
    h6: { fontSize: '13px', fontWeight: 600, lineHeight: 1.45 },
    subtitle1: { fontSize: '13px', fontWeight: 600, lineHeight: 1.45 },
    subtitle2: { fontSize: '12px', fontWeight: 600, lineHeight: 1.45 },
    body1: { fontSize: '13px', lineHeight: 1.45 },
    body2: { fontSize: '12px', lineHeight: 1.45 },
    caption: { fontSize: '11px', lineHeight: 1.4 },
    button: { fontSize: '13px', fontWeight: 400, textTransform: 'none' },
    // 不用全大寫小標：overline 只是一行小字。
    overline: { fontSize: '11px', lineHeight: 1.4, letterSpacing: 0, textTransform: 'none' },
    readout: { ...numFace, fontSize: '22px', fontWeight: 350, lineHeight: 1 },
    num: { ...numFace, fontSize: '12px', lineHeight: 1.45 },
    mono: { fontFamily: tokens.font.mono, fontSize: '12px', lineHeight: 1.45 },
  },
  transitions: {
    duration: {
      shortest: tokens.motion.fast,
      shorter: tokens.motion.fast,
      short: tokens.motion.fast,
      standard: tokens.motion.panel,
      complex: tokens.motion.panel,
      enteringScreen: tokens.motion.panel,
      leavingScreen: tokens.motion.fast,
    },
    easing: {
      easeInOut: tokens.motion.ease,
      easeOut: tokens.motion.ease,
      easeIn: 'cubic-bezier(0.4, 0, 1, 1)',
      sharp: tokens.motion.ease,
    },
  },
  components,
});

export default theme;
