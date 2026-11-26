import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { isApiError } from '@bisheng/api-client';
import { Button, Select, type SelectOption } from '@bisheng/ui';
import { QaKnowledgeSelect } from '@/components/bs-comp/selectComponent/QaKnowledgeSelect';
import { useSelectLabels } from '@/components/bs-comp/formFields/useSelectLabels';
import { Checkbox } from '@bisheng/ui';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/bs-ui/dialog';
import { Input } from '@bisheng/ui';
import { Label } from '@/components/bs-ui/label';
import { RadioGroup, Radio as RadioGroupItem } from '@bisheng/ui';
import { DatasetConnection, DatasetImportRequest, importQADataset, importTrainingDataset, RemoteDatasetSource, uploadCatalogDataset } from '@/controllers/API/finetuneDatasets';
import { TrainingDataType, TrainingFile } from '@/controllers/API/finetuneV2';

interface Props {
    dataType: TrainingDataType; onDataTypeChange?: (value: TrainingDataType) => void; onClose: () => void;
    onImported: (file: TrainingFile) => void; onBusyChange?: (busy: boolean) => void;
}
type Source = 'local' | 'qa' | RemoteDatasetSource;
const connectionFields: Record<RemoteDatasetSource, (keyof DatasetConnection)[]> = {
    ftp: ['username', 'password'], sftp: ['username', 'password', 'host_fingerprint'],
    s3: ['bucket', 'access_key', 'secret_key', 'session_token', 'region'],
};
const endpointProtocols: Record<RemoteDatasetSource, string[]> = { ftp: ['ftp:', 'ftps:'], sftp: ['sftp:'], s3: ['http:', 'https:'] };
const endpointPlaceholders: Record<RemoteDatasetSource, string> = {
    ftp: 'ftp://files.example.com:21', sftp: 'sftp://files.example.com:22', s3: 'https://s3.example.com',
};
const secretFields = new Set(['password', 'access_key', 'secret_key', 'session_token']);
// Mirrors the server limits: whole packages up to 2 GiB, JSON parsed whole up to 200 MiB, inline manifests up to 20 MiB.
const MiB = 1024 * 1024;
const uploadLimit = (file: File) => /\.jsonl?$/i.test(file.name) ? 200 * MiB : 2048 * MiB;
const inlineManifestLimit = 20 * MiB;

export function validDatasetEndpoint(endpoint: string, source: RemoteDatasetSource) {
    try {
        const url = new URL(endpoint);
        return endpointProtocols[source].includes(url.protocol)
            && Boolean(url.hostname) && !url.username && !url.password && !url.search && !url.hash && ['', '/'].includes(url.pathname);
    } catch { return false; }
}
export function safeDatasetImportError(failure: unknown, connection: Partial<DatasetConnection>, fallback: string, detailLabel = '') {
    let message = typeof failure === 'string' ? failure : failure instanceof Error ? failure.message : '';
    // Dataset and data-source rejections carry the offending sample, file or step; the code copy alone cannot locate it.
    const detail = isApiError(failure) && (failure.status_code === 10129 || failure.status_code === 10132) && typeof failure.status_message === 'string' ? failure.status_message.trim() : '';
    if (detail && detail !== message) message = message ? `${message} ${detailLabel}${detail}` : detail;
    if (!message) return fallback;
    for (const key of ['password', 'access_key', 'secret_key', 'session_token'] as const) {
        const secret = connection[key];
        if (secret) message = message.split(secret).join('••••');
    }
    return `${fallback} ${message.slice(0, 500)}`;
}
export function DatasetImportDialog({ dataType, onDataTypeChange, onClose, onImported, onBusyChange }: Props) {
    const { t } = useTranslation('model');
    const selectLabels = useSelectLabels();
    const [source, setSource] = useState<Source>('local');
    const [name, setName] = useState('');
    const [qaLibraries, setQaLibraries] = useState<SelectOption[]>([]);
    const importType: TrainingDataType = source === 'qa' ? 'text' : dataType;
    const [connection, setConnection] = useState<DatasetConnection>({ endpoint: '' });
    const [manifestSource, setManifestSource] = useState('remote');
    const [manifestPath, setManifestPath] = useState('');
    const [mediaRoot, setMediaRoot] = useState('');
    const [file, setFile] = useState<File>();
    const [busy, setBusy] = useState(false);
    const [progress, setProgress] = useState<number>();
    const [error, setError] = useState('');
    const active = useRef(true);
    useEffect(() => { active.current = true; return () => { active.current = false; }; }, []);
    const handleSourceChange = (value: Source) => {
        setSource(value); setConnection({ endpoint: '' }); setManifestPath(''); setMediaRoot(''); setFile(undefined); setQaLibraries([]); setError('');
    };
    const handleImport = async () => {
        setError('');
        if (source === 'local' && !file) { setError(t('finetune.datasetChooseFile')); return; }
        if (source === 'local' && file && file.size > uploadLimit(file)) { setError(t('finetune.datasetUploadSizeLimit')); return; }
        if (source !== 'local' && source !== 'qa' && file && file.size > inlineManifestLimit) { setError(t('finetune.datasetManifestSizeLimit')); return; }
        if (source === 'qa' && (!name.trim() || !qaLibraries.length)) { setError(t('finetune.datasetQaRequired')); return; }
        if (source !== 'local' && source !== 'qa') {
            if (!name.trim() || !validDatasetEndpoint(connection.endpoint, source) || (source === 's3' && !connection.bucket?.trim())
                || (source === 'sftp' && (!connection.username?.trim() || !connection.password))) {
                setError(t('finetune.datasetConnectionRequired')); return;
            }
            if (manifestSource === 'remote' ? !manifestPath.trim() : !file || !/\.jsonl?$/i.test(file.name)) {
                setError(t('finetune.datasetManifestRequired')); return;
            }
        }
        setBusy(true); onBusyChange?.(true);
        try {
            let imported: TrainingFile;
            if (source === 'qa') imported = await importQADataset(name.trim(), qaLibraries.map(option => Number(option.value)));
            else if (source === 'local' && file) imported = await uploadCatalogDataset(file, importType, name.trim() || file.name, percent => { if (active.current) setProgress(percent); });
            else {
                const request: DatasetImportRequest = { name: name.trim(), data_type: importType, source: source as RemoteDatasetSource, connection, media_root: mediaRoot.trim(),
                    ...(manifestSource === 'local' && file ? { manifest_text: await file.text(), manifest_filename: file.name }
                        : { manifest_path: manifestPath.trim() }) };
                imported = await importTrainingDataset(request);
            }
            if (!active.current) return;
            if (imported.dataset_report.data_type !== importType) { setError(t('finetune.datasetTypeMismatch')); return; }
            if (!imported.dataset_report.validated) { setError(t('finetune.uploadFailed')); return; }
            onImported(imported);
            setConnection({ endpoint: '' }); onClose();
        } catch (failure) {
            if (active.current) setError(safeDatasetImportError(failure, connection, t('finetune.datasetImportFailed'), t('finetune.datasetErrorDetail')));
        } finally { if (active.current) { setBusy(false); setProgress(undefined); } onBusyChange?.(false); }
    };
    const close = () => { if (!busy) { setConnection({ endpoint: '' }); onClose(); } };
    return <Dialog open onOpenChange={open => { if (!open) close(); }}>
        <DialogContent className="max-w-[600px] max-h-[calc(100vh-64px)] flex flex-col" onEscapeKeyDown={event => { if (busy) event.preventDefault(); }} onInteractOutside={event => event.preventDefault()}>
            <DialogHeader><DialogTitle>{t('finetune.datasetImport')}</DialogTitle><DialogDescription>{t('finetune.datasetImportHint')}</DialogDescription></DialogHeader>
            <form onSubmit={event => { event.preventDefault(); void handleImport(); }} className="flex flex-col min-h-0 gap-4">
                <fieldset disabled={busy} className="space-y-4 overflow-y-auto px-1">
                    {onDataTypeChange && <div className="space-y-1"><Label>{t('finetune.datasetCategory')}</Label><Select {...selectLabels} value={importType} disabled={source === 'qa'} onChange={value => onDataTypeChange(value as TrainingDataType)} aria-label={t('finetune.datasetCategory')} options={(['text', 'image_text', 'video_text'] as TrainingDataType[]).map(value => ({ value, label: t(`finetune.type_${value}`) }))} /></div>}
                    <div className="space-y-1"><Label htmlFor="dataset-name">{t('finetune.datasetImportName')}</Label><Input id="dataset-name" value={name} onChange={event => setName(event.target.value)} placeholder="support-examples" maxLength={100} /></div>
                    <RadioGroup value={source} onValueChange={handleSourceChange} className="flex flex-wrap gap-x-5 gap-y-3">
                        {(['local', 'ftp', 'sftp', 's3', 'qa'] as Source[]).map(value => <div className="flex items-center gap-2" key={value}><RadioGroupItem value={value} id={`dataset-source-${value}`} /><Label htmlFor={`dataset-source-${value}`}>{t(`finetune.datasetSource_${value}`)}</Label></div>)}
                    </RadioGroup>
                    {source === 'local' ? <div key="local-file" className="space-y-2">
                        <Label htmlFor="dataset-upload">{t('finetune.uploadDataset')}</Label>
                        <Input id="dataset-upload" type="file" accept={importType === 'text' ? '.json,.jsonl,.zip' : '.zip'} onChange={event => setFile(event.target.files?.[0])} />
                        <p className="text-sm text-muted-foreground">{t(`finetune.${importType === 'text' ? 'textPackageHint' : importType === 'image_text' ? 'imagePackageHint' : 'videoPackageHint'}`)}</p>
                        <p className="text-xs text-muted-foreground">{t('finetune.datasetUploadLimitHint')}</p>
                    </div> : source === 'qa' ? <div className="space-y-2">
                        <Label htmlFor="knowledgeLib">{t('finetune.datasetQaKnowledge')}</Label>
                        <QaKnowledgeSelect label={t('finetune.datasetQaKnowledge')} value={qaLibraries} onChange={setQaLibraries} />
                        <p className="text-sm text-muted-foreground">{t('finetune.datasetQaHint')}</p>
                    </div> : <>
                        <div className="space-y-1"><Label htmlFor="dataset-endpoint">{t('finetune.datasetEndpoint')}</Label><Input id="dataset-endpoint" value={connection.endpoint} autoComplete="off" onChange={event => setConnection(old => ({ ...old, endpoint: event.target.value }))} placeholder={endpointPlaceholders[source]} /><p className="text-xs text-muted-foreground">{t('finetune.datasetEndpointHint')}</p></div>
                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">{connectionFields[source].map(key => <div className="space-y-1" key={key}>
                            <Label htmlFor={`dataset-${key}`}>{t(`finetune.datasetConnection_${source === 'sftp' && (key === 'username' || key === 'password') ? `${key}_required` : key}`)}</Label><Input id={`dataset-${key}`} value={String(connection[key] ?? '')} type={secretFields.has(key) ? 'password' : 'text'} autoComplete="off" onChange={event => setConnection(old => ({ ...old, [key]: event.target.value }))} />
                        </div>)}</div>
                        {source === 'sftp' && <p className="text-xs text-muted-foreground">{t('finetune.datasetHostFingerprintHint')}</p>}
                        {source === 'ftp' && <div className="flex gap-2 items-center"><Checkbox id="dataset-tls" checked={connection.tls ?? false} onCheckedChange={value => setConnection(old => ({ ...old, tls: value === true }))} /><Label htmlFor="dataset-tls">{t('finetune.datasetTLS')}</Label></div>}
                        <p className="text-xs text-muted-foreground">{t('finetune.datasetCredentialsHint')}</p>
                        <RadioGroup value={manifestSource} onValueChange={value => { setManifestSource(value); setFile(undefined); }} className="flex flex-wrap gap-4">
                            {['remote', 'local'].map(value => <div className="flex items-center gap-2" key={value}><RadioGroupItem value={value} id={`manifest-source-${value}`} /><Label htmlFor={`manifest-source-${value}`}>{t(`finetune.datasetManifest_${value}`)}</Label></div>)}
                        </RadioGroup>
                        {manifestSource === 'remote' ? <div key="remote-manifest" className="space-y-1"><Label htmlFor="dataset-manifest">{t('finetune.datasetManifestPath')}</Label><Input id="dataset-manifest" value={manifestPath} onChange={event => setManifestPath(event.target.value)} placeholder="datasets/train.json" /></div>
                            : <div key="local-manifest" className="space-y-1"><Label htmlFor="dataset-local-manifest">{t('finetune.datasetLocalManifest')}</Label><Input id="dataset-local-manifest" type="file" accept=".json,.jsonl" onChange={event => setFile(event.target.files?.[0])} /></div>}
                        <div className="space-y-1"><Label htmlFor="dataset-media-root">{t('finetune.datasetMediaRoot')}</Label><Input id="dataset-media-root" value={mediaRoot} onChange={event => setMediaRoot(event.target.value)} placeholder="datasets/" /><p className="text-xs text-muted-foreground">{t('finetune.datasetRelativePathHint')}</p></div>
                    </>}
                </fieldset>
                {busy && <p role="status" className="text-sm">{progress !== undefined && progress < 100 ? t('finetune.datasetUploading', { percent: progress }) : t('finetune.datasetImportChecking')}</p>}
                {error && <p role="alert" className="text-sm text-red-500 break-words">{error}</p>}
                <DialogFooter><Button type="button" variant="outlined" disabled={busy} onClick={close}>{t('bs:cancel')}</Button><Button type="submit" disabled={busy}>{t('finetune.datasetImportAndCheck')}</Button></DialogFooter>
            </form>
        </DialogContent>
    </Dialog>;
}
