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
    ns: ['translation'],
    debug: false,
    defaultNS,
    resources,
    interpolation: {
      escapeValue: false,
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
    },
  });

export default i18n;
