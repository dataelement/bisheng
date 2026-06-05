window.BRAND_CONFIG = {
    brandName: {
        zh: "BISHENG",
        en: "BISHENG"
    },
    linsightAgentName: {
        zh: "灵思",
        en: "Linsight"
    },
    URLLoadingIcon: "",
    loadingIcon: "",
    loadingAnimation: ""
};

// Application-wide runtime config (separate from BRAND_CONFIG above).
// Read by both the platform admin app and the client chat app.
window.APP_CONFIG = {
    // Hide Japanese from the language switcher and prevent it from being
    // auto-selected by browser/locale detection. Set to false to re-enable.
    disableJa: true
};
