import { useTranslation } from 'react-i18next';
import { Input } from '@bisheng/ui';
import { Label } from '@/components/bs-ui/label';
import type { DatasetCredentials, RemoteDatasetLocation } from '@/controllers/API/finetuneV2';

interface Props { location: RemoteDatasetLocation; value: DatasetCredentials; onChange: (value: DatasetCredentials) => void }
const fields: Record<RemoteDatasetLocation['type'], (keyof DatasetCredentials)[]> = {
    ftp: ['password'], sftp: ['password'], s3: ['access_key', 'secret_key', 'session_token'],
};

// Secrets live only in this form state and the one submit request; the platform never stores them.
export function DatasetSourceCredentials({ location, value, onChange }: Props) {
    const { t } = useTranslation('model');
    return <div className="space-y-2 rounded-md border p-3">
        <Label>{t('finetune.datasetSourceCredentials')}</Label>
        <p className="text-xs text-muted-foreground">{t('finetune.datasetSourceCredentialsHint', {
            source: t(`finetune.datasetSource_${location.type}`), endpoint: location.endpoint })}</p>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">{fields[location.type].map(key => <div className="space-y-1" key={key}>
            <Label htmlFor={`source-${key}`}>{t(`finetune.datasetConnection_${location.type === 'sftp' ? `${key}_required` : key}`)}</Label>
            <Input id={`source-${key}`} type="password" autoComplete="new-password" value={value[key] ?? ''}
                onChange={event => onChange({ ...value, [key]: event.target.value })} />
        </div>)}</div>
    </div>;
}
