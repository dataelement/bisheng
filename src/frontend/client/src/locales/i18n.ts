import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import LanguageDetector from 'i18next-browser-languagedetector';

// Import your JSON translations
import translationEn from './en/translation.json';
import translationJa from './ja/translation.json';
import translationZh_Hans from './zh-Hans/translation.json';
// Generated from packages/locales (cross-app copy) — never edit by hand.
import apiErrorsEn from './en/api_errors.gen.json';
import apiErrorsJa from './ja/api_errors.gen.json';
import apiErrorsZh_Hans from './zh-Hans/api_errors.gen.json';
import sharedEn from './en/shared.gen.json';
import sharedJa from './ja/shared.gen.json';
import sharedZh_Hans from './zh-Hans/shared.gen.json';

export const defaultNS = 'translation';

// 'shared' is a real namespace (addressed shared:<key>) so cross-app components
// in packages/* use one addressing form on both apps.
export const resources = {
  'en': { translation: { ...translationEn, api_errors: apiErrorsEn }, shared: sharedEn },
  'zh-Hans': { translation: { ...translationZh_Hans, api_errors: apiErrorsZh_Hans }, shared: sharedZh_Hans },
  'ja': { translation: { ...translationJa, api_errors: apiErrorsJa }, shared: sharedJa },
} as const;

const config = window.BRAND_CONFIG || {};

// APP_CONFIG.disableJa (config.js): drop any saved Japanese choice so
// LanguageDetector below doesn't auto-restore it on this load.
const jaDisabled = !!(window.APP_CONFIG && window.APP_CONFIG.disableJa);
if (jaDisabled) {
  try {
    const saved = localStorage.getItem('i18nextLng');
    if (saved && saved.toLowerCase().startsWith('ja')) {
      localStorage.removeItem('i18nextLng');
    }
  } catch { /* localStorage may be unavailable */ }
}

i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    fallbackLng: {
      'zh-TW': ['zh-Hant', 'en'],
      'zh-HK': ['zh-Hant', 'en'],
      'zh': ['zh-Hans', 'en'],
      // When ja is disabled at runtime, browser-detected ja* falls through
      // to English instead of loading the bundled Japanese resources.
      ...(jaDisabled ? { ja: ['en'], 'ja-JP': ['en'] } : {}),
      default: ['en'],
    },
    fallbackNS: 'translation',
    ns: ['translation', 'shared'],
    debug: false,
    defaultNS,
    resources,
    interpolation: {
      escapeValue: false,
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
    },
  });

export default i18n;
