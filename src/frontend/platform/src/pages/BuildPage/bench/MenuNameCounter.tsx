import { useTranslation } from 'react-i18next';
import { MENU_NAME_MAX_WIDTH, menuNameWidth } from './menuDisplayName';

interface MenuNameCounterProps {
    value: string;
}

export function MenuNameCounter({ value }: MenuNameCounterProps) {
    const { t } = useTranslation();
    return (
        <span className="whitespace-nowrap text-[12px] tabular-nums" title={t('chatConfig.menuNameLengthHint')}>
            {menuNameWidth(value || '')} / {MENU_NAME_MAX_WIDTH}
        </span>
    );
}
