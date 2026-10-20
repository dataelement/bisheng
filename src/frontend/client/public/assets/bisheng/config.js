// Application-wide runtime config (NOT branding).
// Branding now comes from the backend (/api/v1/brand/runtime-config) and is
// applied + cached by brand-runtime.js; there is no static BRAND_CONFIG here.
// Read by both the platform admin app and the client chat app.
window.APP_CONFIG = {
    // Hide Japanese from the language switcher and prevent it from being
    // auto-selected by browser/locale detection. Set to false to re-enable.
    disableJa: true
    // Skill Center preview (技能中心 + the chat input's 技能 entry) is off by default.
    // A deployment opts in by adding `skillCenterPreviewEnabled: true` here, or a build
    // does with VITE_SKILL_CENTER_PREVIEW=true. Leave the key OUT unless you mean to
    // pin it: an explicit value here wins over the build-time flag, so a literal
    // `false` would make that flag unusable.
};
