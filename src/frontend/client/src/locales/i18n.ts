import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import LanguageDetector from 'i18next-browser-languagedetector';

// Import your JSON translations
import translationEn from './en/translation.json';
import translationJa from './ja/translation.json';
import translationZh_Hans from './zh-Hans/translation.json';

export const defaultNS = 'translation';

export const resources = {
  'en': { translation: translationEn },
  'zh-Hans': { translation: translationZh_Hans },
  'ja': { translation: translationJa },
} as const;

const config = window.BRAND_CONFIG || {};

i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    fallbackLng: {
      'zh-TW': ['zh-Hant', 'en'],
      'zh-HK': ['zh-Hant', 'en'],
      'zh': ['zh-Hans', 'en'],
      default: ['en'],
    },
    fallbackNS: 'translation',
    ns: ['translation'],
    debug: false,
    defaultNS,
    resources,
    interpolation: {
      escapeValue: false,
      defaultVariables: {
        bisheng: config.brandName?.en,
        bishengZh: config.brandName?.zh,
        linsight: config.linsightAgentName?.en,
        linsightZh: config.linsightAgentName?.zh,
        linsightFull: config.linsightFullName?.en,
        linsightFullZh: config.linsightFullName?.zh
      }
    },
  });

export default i18n;