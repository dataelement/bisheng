import { useTranslation } from 'react-i18next';
import { Label } from '@/components/bs-ui/label';
import { RadioGroup, Radio as RadioGroupItem } from '@bisheng/ui';
import type { TrainingMethod } from '@/controllers/API/finetuneV2';

interface Props { value: TrainingMethod; supported: string[]; onChange: (method: TrainingMethod) => void }
export const trainingMethods: TrainingMethod[] = ['lora', 'freeze', 'full'];
const labels: Record<TrainingMethod, string> = { lora: 'finetune.lora', freeze: 'finetune.freeze', full: 'finetune.fullFineTune' };
export const trainingMethodLabel = (method: string) => labels[method as TrainingMethod] ?? method;

// Methods the selected model does not offer stay visible but disabled, so the reason is explained instead of hidden.
export function TrainingMethodField({ value, supported, onChange }: Props) {
    const { t } = useTranslation('model');
    const unavailable = trainingMethods.filter(method => !supported.includes(method));
    return <div className="space-y-2">
        <Label>{t('finetune.trainingMethod')}</Label>
        <RadioGroup value={value} className="flex gap-6" onValueChange={next => onChange(next as TrainingMethod)}>
            {trainingMethods.map(method => <div key={method} className="flex items-center gap-2">
                <RadioGroupItem id={`method-${method}`} value={method} disabled={!supported.includes(method)} />
                <Label htmlFor={`method-${method}`}>{t(labels[method])}</Label>
            </div>)}
        </RadioGroup>
        <p className="text-sm text-muted-foreground">{t(`finetune.methodHint_${value}`)}</p>
        {unavailable.length > 0 && <p className="text-xs text-muted-foreground">
            {t('finetune.methodUnavailable', { methods: unavailable.map(method => t(labels[method])).join(t('finetune.listSeparator')) })}
        </p>}
    </div>;
}
