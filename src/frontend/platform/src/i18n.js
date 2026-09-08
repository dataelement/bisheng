import i18n from "i18next";
import Backend from 'i18next-http-backend';
import {
    initReactI18next
} from "react-i18next";
import json from "../package.json";

// Honor APP_CONFIG.disableJa (config.js): hide ja from auto-detection and
// strip any stale ja value out of localStorage so other paths don't re-apply.
export const JA_DISABLED = !!(window.APP_CONFIG && window.APP_CONFIG.disableJa);

// Map any tag onto a locale folder we actually ship. This has to cover values
// we did not write ourselves: the client app shares localStorage['i18nextLng']
// on the same origin but ships its English bundle as `en`, while ours is
// `en-US`. With `load: 'currentOnly'` an unnormalized `en` requests
// /locales/en/bs.json, gets a 404, and leaves every namespace empty — the page
// renders raw keys while the language picker still shows English, and
// getResourceBundle() returns undefined for anything reading a bundle directly.
const normalizeLanguage = (tag) => {
    const value = String(tag || '').toLowerCase();
    // Traditional variants have no bundle of their own here; zh-Hans is the
    // long-standing behaviour for every zh tag.
    if (value.startsWith('zh')) return 'zh-Hans';
    if (value.startsWith('ja')) return JA_DISABLED ? 'en-US' : 'ja';
    return 'en-US';
};

// Obtain user language preferences, supporting full language codes (e.g., zh-Hans, en-US)
const getBrowserLanguage = () => {
    const savedLanguage = localStorage.getItem('i18nextLng');
    if (savedLanguage) {
        if (JA_DISABLED && savedLanguage.toLowerCase().startsWith('ja')) {
            localStorage.removeItem('i18nextLng');
        } else {
            return normalizeLanguage(savedLanguage);
        }
    }

    const browserLang = navigator.language || navigator.userLanguage || 'en-US';
    return normalizeLanguage(browserLang);
};

const userLanguage = getBrowserLanguage();
const config = window.BRAND_CONFIG || {};

i18n.use(Backend)
    .use(initReactI18next)
    .init({
        partialBundledLanguages: true,
        // 'model' must be eager-loaded: SystemConfigBanners renders early in
        // the model-management page tree and its t() calls fire before any
        // lazy-load could resolve. With lazy load + i18next's default merge
        // (don't-overwrite) addResourceBundle, a stale model.json snapshot
        // already in the store will starve any newly-deployed key (the
        // historical bug that made systemConfig* keys render as raw strings).
        // 'api_errors' and 'shared' are generated from packages/locales (cross-app copy).
        ns: ['bs', 'flow', 'permission', 'orgSync', 'model', 'api_errors', 'shared'],
        defaultNS: 'bs',
        lng: userLanguage,
        fallbackLng: 'en-US',
        load: 'currentOnly',
        backend: {
            loadPath: __APP_ENV__.BASE_URL + '/locales/{{lng}}/{{ns}}.json?v=' + json.version,
            // Disable any per-key cross-request memoization in the backend
            // adapter so each fresh deploy actually overrides the in-memory
            // resource bundle for the language.
            requestOptions: {
                cache: 'no-cache',
            },
        },
        interpolation: {
            escapeValue: false, // react already safes from xss
            defaultVariables: {
                bisheng: config.brandName?.en || 'BISHENG',
                bishengZh: config.brandName?.zh || 'BISHENG',
                linsight: config.linsightAgentName?.en || 'Linsight',
                linsightZh: config.linsightAgentName?.zh || '灵思',
                linsightFull: 'Linsight',
                linsightFullZh: '灵思 Linsight',
                dailyFullName: 'Daily Mode',
                dailyFullNameZh: '日常模式',
            }
        }
    });

export default i18n;

// Dynamically load the namespace 
// i18n.loadNamespaces(['bs']);
