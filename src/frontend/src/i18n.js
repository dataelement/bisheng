import i18n from "i18next";
import {
    initReactI18next
} from "react-i18next";
import Backend from 'i18next-http-backend';

const userLanguage = (localStorage.getItem('language') ||
    navigator.language ||
    navigator.userLanguage || 'en').substring(0, 2)

i18n.use(Backend)
    .use(initReactI18next)
    .init({
        partialBundledLanguages: true,
        ns: ['bs'],
        lng: userLanguage === 'zh' ? userLanguage : 'en', // 除中文即英文
        backend: {
            loadPath: '/locales/{{lng}}/{{ns}}.json'
        },
        interpolation: {
            escapeValue: false // react already safes from xss
        }
    });

export default i18n;

// 动态的加载命名空间
// i18n.loadNamespaces(['bs']);