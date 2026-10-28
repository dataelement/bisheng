import { useEffect } from 'react';
import { TOptions } from 'i18next';
import { useRecoilValue } from 'recoil';
import { useTranslation } from 'react-i18next';
import { resources } from '~/locales/i18n';
import { readDesktopLocale } from '~/locales/desktopLocale';
import store from '~/store';

export type TranslationKeys = keyof typeof resources.en.translation | any;

export default function useLocalize() {
  const lang = useRecoilValue(store.lang);
  const { t, i18n } = useTranslation();

  useEffect(() => {
    // Newly mounted pages must not restore the saved web choice over the host's locale.
    const activeLang = readDesktopLocale() ?? lang;
    if (i18n.language !== activeLang) {
      void i18n.changeLanguage(activeLang).catch((error: unknown) => {
        console.error('Failed to apply interface language', error);
      });
    }
  }, [lang, i18n]);

  return (phraseKey: TranslationKeys, options?: TOptions) => t(phraseKey, options);
}
