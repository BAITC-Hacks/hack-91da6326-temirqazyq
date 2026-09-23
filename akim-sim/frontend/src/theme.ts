import type { ThemeConfig } from 'antd'

/* antd управляется теми же токенами, что и остальной интерфейс: DESIGN.md остаётся
   единственным источником правды. Дефолтный вид antd намеренно не используется —
   иначе получилась бы типовая админка вместо системы stripe. */
export const antdTheme: ThemeConfig = {
  token: {
    colorPrimary: '#533afd',
    colorLink: '#533afd',
    colorInfo: '#533afd',
    colorSuccess: '#0ca30c',
    colorWarning: '#fab219',
    colorError: '#d03b3b',

    colorText: '#0d253d',
    colorTextSecondary: '#273951',
    colorTextTertiary: '#4f5b70',
    colorTextQuaternary: '#5d6d86',
    colorTextDescription: '#4f5b70',

    colorBgContainer: '#ffffff',
    colorBgLayout: '#f6f9fc',
    colorBgElevated: '#ffffff',
    colorBgSpotlight: '#0d253d',       // фон подсказок — тёмный, как в нашем Hint
    colorFillAlter: '#eef3f8',
    colorFillSecondary: '#eef3f8',
    colorBorder: '#a8c3de',
    colorBorderSecondary: '#e3e8ee',

    borderRadius: 8,
    borderRadiusLG: 12,
    borderRadiusSM: 6,
    fontFamily: "Inter, system-ui, -apple-system, 'Segoe UI', sans-serif",
    fontSize: 14,
    controlHeight: 36,
    boxShadow: 'rgba(0, 55, 112, 0.08) 0 1px 3px',
    boxShadowSecondary: 'rgba(0, 55, 112, 0.08) 0 8px 24px, rgba(0, 55, 112, 0.04) 0 2px 6px',
    wireframe: false,
  },
  components: {
    Table: {
      headerBg: '#eef3f8',
      headerColor: '#4f5b70',
      headerSplitColor: 'transparent',
      rowHoverBg: '#f6f9fc',
      borderColor: '#e3e8ee',
      cellPaddingBlock: 10,
      cellPaddingInline: 12,
      fontSize: 13,
    },
    Tooltip: {
      colorBgSpotlight: '#0d253d',
      colorTextLightSolid: '#e7edf5',
      borderRadius: 8,
      fontSize: 13,
    },
    Select: { optionSelectedBg: '#eeecff' },
    Segmented: { itemSelectedBg: '#eeecff', itemSelectedColor: '#4434d4', trackBg: '#eef3f8' },
    Empty: { colorTextDescription: '#4f5b70' },
  },
}
