import i18n from "i18next";
import Backend from 'i18next-http-backend';
import {
    initReactI18next
} from "react-i18next";
import json from "../package.json";

const userLanguage = (localStorage.getItem('language') ||
    navigator.language ||
    navigator.userLanguage || 'en').substring(0, 2)

i18n.use(Backend)
    .use(initReactI18next)
    .init({
        partialBundledLanguages: true,
        ns: ['bs'],
        lng: 'zh', // userLanguage === 'zh' ? userLanguage : 'en', // 除中文即英文
        backend: {
            loadPath: __APP_ENV__.BASE_URL + '/locales/{{lng}}/{{ns}}.json?v=' + json.version
        },
        interpolation: {
            escapeValue: false // react already safes from xss
        }
    });

export default i18n;

// 动态的加载命名空间
// i18n.loadNamespaces(['bs']);