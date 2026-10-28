import { Select } from '@bisheng/ui';
import { useSelectLabels } from '@/components/bs-comp/formFields/useSelectLabels';
import { useTranslation } from 'react-i18next';
import { usagePresetRange, type UsagePreset, type UsageRange } from './usageRange';

interface UsageRangeSelectProps {
  preset: UsagePreset;
  onChange: (preset: UsagePreset, range: UsageRange) => void;
}

export function UsageRangeSelect({ preset, onChange }: UsageRangeSelectProps) {
  const { t } = useTranslation();
  const selectLabels = useSelectLabels();
  return (
    <Select
      {...selectLabels}
      className="w-32"
      aria-label={t('dsh.usageRange')}
      value={preset}
      options={(['today', '30d', 'year'] as const).map((value) => ({
        value,
        label: t(`dsh.range.${value}`),
      }))}
      onChange={(value) => {
        const next = value as UsagePreset;
        onChange(next, usagePresetRange(next));
      }}
    />
  );
}
