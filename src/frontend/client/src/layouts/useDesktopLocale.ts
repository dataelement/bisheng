import { useClientEnvironment } from "~/hooks/useClientEnvironment";
import { useEffect } from "react";
import i18n from "~/locales/i18n";
import {
  changeInterfaceLanguage,
  readDesktopLocale,
  subscribeDesktopLocale,
} from "~/locales/desktopLocale";

export function useDesktopLocale() {
  const {
    channel,
    capabilities: { hasNativePresentation },
  } = useClientEnvironment();
  useEffect(() => {
    const apply = () => {
      const locale = readDesktopLocale();
      if (locale && i18n.language !== locale) {
        void changeInterfaceLanguage(i18n, locale).catch((error: unknown) => {
          console.error("Failed to apply desktop language", error);
        });
      }
    };
    const unsubscribe = subscribeDesktopLocale(apply);
    apply();
    return unsubscribe;
  }, [channel, hasNativePresentation]);
}
