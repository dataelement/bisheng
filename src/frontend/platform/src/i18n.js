import i18n from "i18next";
import Backend from 'i18next-http-backend';
import {
    initReactI18next
} from "react-i18next";
import json from "../package.json";

// Obtain user language preferences, supporting full language codes (e.g., zh-Hans, en-US) 
const getBrowserLanguage = () => {
    const savedLanguage = localStorage.getItem('i18nextLng');
    if (savedLanguage) return savedLanguage;

    const browserLang = navigator.language || navigator.userLanguage || 'en-US';
    // Map browser language codes to the languages we support 
    if (browserLang.startsWith('zh')) return 'zh-Hans';
    if (browserLang.startsWith('ja')) return 'ja';
    return 'en-US';
};

const userLanguage = getBrowserLanguage();

i18n.use(Backend)
    .use(initReactI18next)
    .init({
        partialBundledLanguages: true,
        ns: ['bs', 'flow'],
        lng: userLanguage,
        fallbackLng: 'en-US',
        backend: {
            loadPath: __APP_ENV__.BASE_URL + '/locales/{{lng}}/{{ns}}.json?v=' + json.version
        },
        interpolation: {
            escapeValue: false // react already safes from xss
        }
    });

export default i18n;

// Dynamically load the namespace 
// i18n.loadNamespaces(['bs']);