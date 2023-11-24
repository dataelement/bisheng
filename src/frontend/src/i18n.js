import i18n from "i18next";
import {
    initReactI18next
} from "react-i18next";
import Backend from 'i18next-http-backend';

i18n.use(Backend)
    .use(initReactI18next)
    .init({
        partialBundledLanguages: true,
        ns: ['bs'],
        lng: 'en',
        backend: {
            loadPath: '/locales/{{lng}}/{{ns}}.json'
        },
        interpolation: {
            escapeValue: false // react already safes from xss
        }
    });

export default i18n;