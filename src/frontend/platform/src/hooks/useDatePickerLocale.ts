import type { DatePickerOpenRangeLocale } from '@bisheng/ui';
import { enUS, ja, zhCN } from 'date-fns/locale';
import { useTranslation } from 'react-i18next';

const calendars: Record<string, DatePickerOpenRangeLocale['calendar']> = { en: enUS, ja, zh: zhCN };

export function useDatePickerLocale(): DatePickerOpenRangeLocale {
    const { t, i18n } = useTranslation('bs');
    const language = i18n.resolvedLanguage || i18n.language;
    const calendar = calendars[language?.split('-')[0] ?? ''] ?? enUS;
    const fullDate = new Intl.DateTimeFormat(calendar.code, { dateStyle: 'full', timeZone: 'UTC' });

    return {
        calendar,
        unlimited: t('datePicker.unlimited'),
        openCalendar: t('datePicker.openCalendar'),
        enterDate: t('datePicker.enterDate'),
        clear: t('datePicker.clear'),
        startDate: t('datePicker.startDate'),
        endDate: t('datePicker.endDate'),
        selectOtherDate: t('datePicker.selectOtherDate'),
        cancel: t('cancel'),
        confirm: t('confirm'),
        hour: t('datePicker.hour'),
        minute: t('datePicker.minute'),
        second: t('datePicker.second'),
        errors: {
            invalidDate: t('datePicker.errors.invalidDate'),
            invalidTime: t('datePicker.errors.invalidTime'),
            incompleteRange: t('datePicker.errors.incompleteRange'),
            reversedRange: t('datePicker.errors.reversedRange'),
            unavailable: t('datePicker.errors.unavailable'),
        },
        calendarLabels: {
            labelNav: () => t('datePicker.navigation'),
            labelPrevious: () => t('datePicker.previousMonth'),
            labelNext: () => t('datePicker.nextMonth'),
            labelMonthDropdown: () => t('datePicker.selectMonth'),
            labelYearDropdown: () => t('datePicker.selectYear'),
            labelDayButton: (date, { today, selected }) => [
                fullDate.format(date),
                today && t('datePicker.today'),
                selected && t('datePicker.selected'),
            ].filter(Boolean).join(', '),
        },
    };
}
