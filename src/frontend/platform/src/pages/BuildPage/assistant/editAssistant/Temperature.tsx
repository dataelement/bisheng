import { Slider } from '@bisheng/ui';
import { useTranslation } from 'react-i18next';

interface TemperatureProps {
    value: number;
    onChange: (value: number) => void;
}

// Model temperature must be read back exactly, so the slider carries a number box (Slider spec §5.1).
export default function Temperature({ value, onChange }: TemperatureProps) {
    const { t } = useTranslation();

    return <div className="mt-2">
        <Slider
            name="slider"
            value={value}
            min={0}
            max={2}
            step={0.1}
            valueDisplay="input"
            thumbLabel={t('build.temperature')}
            inputProps={{
                'aria-label': t('build.temperature'),
                increaseLabel: t('bs:sharedUi.increase'),
                decreaseLabel: t('bs:sharedUi.decrease'),
            }}
            onValueChange={(v) => onChange(v as number)}
        />
    </div>
};
