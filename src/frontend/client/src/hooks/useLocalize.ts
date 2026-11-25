import { useEffect } from 'react';
import { TOptions } from 'i18next';
import { useRecoilValue } from 'recoil';
import { useTranslation } from 'react-i18next';
import { resources } from '~/locales/i18n';
import { normalizeWorkspaceLanguage } from '~/locales/workspaceLanguage';
import store from '~/store';

export type TranslationKeys = keyof typeof resources.en.translation | any;

export default function useLocalize() {
  const lang = useRecoilValue(store.lang);
  const { t, i18n } = useTranslation();

  useEffect(() => {
    const language = normalizeWorkspaceLanguage(lang) || 'en';
    if (i18n.language !== language) {
      i18n.changeLanguage(language);
    }
  }, [lang, i18n]);

  return (phraseKey: TranslationKeys, options?: TOptions) => t(phraseKey, options);
}
