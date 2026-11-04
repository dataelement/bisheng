import { useTranslation } from 'react-i18next';

/**
 * Localized copy for the shared `Select`, which ships no strings of its own.
 * Spread it onto every Select: `<Select {...selectLabels} options={...} />`.
 */
export function useSelectLabels() {
    const { t } = useTranslation('bs');
    return {
        emptyText: t('sharedUi.selectEmpty'),
        noMatchText: t('sharedUi.selectNoMatch'),
        loadingText: t('sharedUi.selectLoading'),
        clearLabel: t('sharedUi.clear'),
        removeLabel: t('sharedUi.remove'),
    };
}
