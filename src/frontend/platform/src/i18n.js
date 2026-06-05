import i18n from "i18next";
import Backend from 'i18next-http-backend';
import {
    initReactI18next
} from "react-i18next";
import json from "../package.json";

// Honor APP_CONFIG.disableJa (config.js): hide ja from auto-detection and
// strip any stale ja value out of localStorage so other paths don't re-apply.
export const JA_DISABLED = !!(window.APP_CONFIG && window.APP_CONFIG.disableJa);

// Obtain user language preferences, supporting full language codes (e.g., zh-Hans, en-US)
const getBrowserLanguage = () => {
    const savedLanguage = localStorage.getItem('i18nextLng');
    if (savedLanguage) {
        const normalized = savedLanguage === 'zh' ? 'zh-Hans' : savedLanguage;
        if (JA_DISABLED && normalized === 'ja') {
            localStorage.removeItem('i18nextLng');
        } else {
            return normalized;
        }
    }

    const browserLang = navigator.language || navigator.userLanguage || 'en-US';
    // Map browser language codes to the languages we support
    if (browserLang.startsWith('zh')) return 'zh-Hans';
    if (browserLang.startsWith('ja') && !JA_DISABLED) return 'ja';
    return 'en-US';
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
        ns: ['bs', 'flow', 'permission', 'orgSync', 'model'],
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
                bisheng: config.brandName?.en,
                bishengZh: config.brandName?.zh,
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
