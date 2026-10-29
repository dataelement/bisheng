import { useEffect } from 'react';
import i18n from '~/locales/i18n';
import { readDesktopLocale, subscribeDesktopLocale } from '~/locales/desktopLocale';

export function useDesktopLocale() {
  useEffect(() => {
    const apply = () => {
      const locale = readDesktopLocale();
      if (locale && i18n.language !== locale) {
        void i18n.changeLanguage(locale).catch((error: unknown) => {
          console.error('Failed to apply desktop language', error);
        });
      }
    };
    const unsubscribe = subscribeDesktopLocale(apply);
    apply();
    return unsubscribe;
  }, []);
}
