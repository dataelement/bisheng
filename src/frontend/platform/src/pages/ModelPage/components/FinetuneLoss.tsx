import { useTranslation } from 'react-i18next';
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
interface Props { samples?: unknown[] }
export function FinetuneLoss({ samples }: Props) {
    const { t } = useTranslation('model');
    const data = (samples || []).filter((item): item is { step: number; loss: number } => {
        if (!item || typeof item !== 'object') return false;
        const value = item as Record<string, unknown>;
        return typeof value.step === 'number' && Number.isFinite(value.step) && typeof value.loss === 'number' && Number.isFinite(value.loss);
    });
    if (!data.length) return null;
    return <section className="border-t pt-4 space-y-2"><h3>{t('finetune.lossCurve')}</h3><ResponsiveContainer width="100%" height={220}><LineChart data={data}><CartesianGrid vertical={false} /><XAxis dataKey="step" /><YAxis /><Tooltip /><Line dataKey="loss" type="linear" stroke="currentColor" dot={false} /></LineChart></ResponsiveContainer></section>;
}
