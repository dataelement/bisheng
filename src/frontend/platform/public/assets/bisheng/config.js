window.BRAND_CONFIG = {
    // 1. 系统品牌名称
    brandName: {
        zh: "首钢股份知库工作台",
        en: "首钢股份知库工作台"
    },

    // 2. 灵思智能体
    linsightAgentName: {
        zh: "灵思",
        en: "Linsight"
    },

    // 3. 灵思中英文结合展示名
    linsightFullName: {
        zh: "灵思Linsight",
        en: "Linsight"
    },
    dailyFullName: {
        zh: "日常模式",
        en: "Daily Mode"
    },

    // 4. Loading 图标配置
    // 支持相对路径 (如 /branding/loading.gif) 或 完整的 URL (如 https://cdn.com/icon.png)
    loadingIcon: "",
    loadingAnimation: "" // animate-spin | animate-ping | animate-pulse | animate-bounce
};

// Application-wide runtime config (separate from BRAND_CONFIG above).
// Read by both the platform admin app and the client chat app.
window.APP_CONFIG = {
    // Hide Japanese from the language switcher and prevent it from being
    // auto-selected by browser/locale detection. Set to false to re-enable.
    disableJa: true
};