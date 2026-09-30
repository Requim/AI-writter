import type { ThemeConfig } from 'antd'

/** 正式应用与隔离预览共用工作台主题，避免默认主题与业务页面分离。 */
export const workbenchTheme: ThemeConfig = {
  token: {
    colorPrimary: '#e64b32', colorInfo: '#3878bd', colorSuccess: '#238568',
    colorWarning: '#b87817', colorError: '#d63d43',
    colorText: '#24262b', colorTextSecondary: '#747881',
    colorBorder: '#e2e4e8', colorBorderSecondary: '#eceef1',
    colorBgContainer: '#ffffff', colorBgLayout: '#f6f7f9',
    borderRadius: 6, controlHeight: 36, fontSize: 14,
    fontFamily: '"Noto Sans SC", "PingFang SC", "Microsoft YaHei", sans-serif',
  },
  components: {
    Button: { primaryShadow: 'none', defaultShadow: 'none', fontWeight: 500 },
    Table: { headerBg: '#f8f9fb', headerColor: '#747881', cellPaddingBlockSM: 14 },
    Tabs: { horizontalItemGutter: 28, titleFontSize: 14 },
    Segmented: { trackBg: '#f3f4f6', itemSelectedBg: '#ffffff' },
    Drawer: { footerPaddingBlock: 16 },
  },
}
