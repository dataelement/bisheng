import { Notifier, Toaster as SharedToaster } from '@bisheng/ui';
import { useTranslation } from 'react-i18next';

export function Toaster() {
    const { t } = useTranslation('bs');
    return <>
        <SharedToaster closeLabel={t('close')} />
        <Notifier closeLabel={t('close')} expandLabel={t('sharedUi.expand')} />
    </>;
}
