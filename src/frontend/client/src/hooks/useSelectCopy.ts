import { useLocalize } from '~/hooks';

/**
 * Localized panel copy for the shared `@bisheng/ui` Select, which ships no
 * copy of its own (English fallbacks only). Spread it onto every Select:
 * `<Select {...selectCopy} … />`.
 */
export default function useSelectCopy() {
  const localize = useLocalize();
  return {
    emptyText: localize('com_select.empty'),
    noMatchText: localize('com_select.no_match'),
    loadingText: localize('com_select.loading'),
    clearLabel: localize('com_select.clear'),
    removeLabel: localize('com_select.remove'),
  };
}
