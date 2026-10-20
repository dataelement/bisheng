// Application-wide runtime config (NOT branding).
// Branding now comes from the backend (/api/v1/brand/runtime-config) and is
// applied + cached by brand-runtime.js; there is no static BRAND_CONFIG here.
// Read by both the platform admin app and the client chat app.
window.APP_CONFIG = {
    // Hide Japanese from the language switcher and prevent it from being
    // auto-selected by browser/locale detection. Set to false to re-enable.
    disableJa: true,
    // Skill Center preview (我的技能 / 技能广场 + the chat input's 技能 entry).
    // Off unless the deployment opts in; also honours VITE_SKILL_CENTER_PREVIEW at build time.
    skillCenterPreviewEnabled: true
};
