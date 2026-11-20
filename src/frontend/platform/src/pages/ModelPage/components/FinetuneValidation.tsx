import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@bisheng/ui';
import { Input, Textarea } from '@bisheng/ui';
import { Label } from '@/components/bs-ui/label';
import { Checkbox } from '@bisheng/ui';
import { captureAndAlertRequestErrorHoc } from '@/controllers/request';
import { runTrainingInference, TrainingTask, uploadValidationMedia } from '@/controllers/API/finetuneV2';
import { inferenceAnswer } from './finetuneHelpers';

interface Props { task: TrainingTask }
export function FinetuneValidation({ task }: Props) {
    const { t } = useTranslation('model');
    const [prompt, setPrompt] = useState('');
    const [file, setFile] = useState<File>();
    const [preview, setPreview] = useState('');
    const [compare, setCompare] = useState(false);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState('');
    const [answer, setAnswer] = useState('');
    const [baseAnswer, setBaseAnswer] = useState('');
    useEffect(() => {
        if (!file) { setPreview(''); return; }
        const url = URL.createObjectURL(file); setPreview(url);
        return () => URL.revokeObjectURL(url);
    }, [file]);
    const needsMedia = task.data_type === 'image_text' || task.data_type === 'video_text';
    const handleValidate = async () => {
        setError(''); setAnswer(''); setBaseAnswer('');
        if (!prompt.trim() || (needsMedia && !file)) { setError(t('finetune.validationInputRequired')); return; }
        if (file && file.size > 20 * 1024 * 1024) { setError(t('finetune.uploadSizeLimit')); return; }
        setBusy(true);
        try {
            const media = needsMedia && file ? await uploadValidationMedia(task.id, file) : undefined;
            const input = { prompt: prompt.trim(), media_url: media?.url, generation: { max_new_tokens: 128 } };
            if (compare) setBaseAnswer(inferenceAnswer(await runTrainingInference(task.id, { ...input, baseline: true })));
            setAnswer(inferenceAnswer(await runTrainingInference(task.id, { ...input, baseline: false })));
        } catch (failure) { setError(t('finetune.inferenceFailed')); await captureAndAlertRequestErrorHoc(Promise.reject(failure)); }
        finally { setBusy(false); }
    };
    return <section className="border-t pt-4 space-y-3"><h2 className="font-medium">{t('finetune.tryNewSample')}</h2><p className="text-sm text-muted-foreground">{t('finetune.newSampleHint')}</p>
        <Label htmlFor="validation-prompt">{t('finetune.validationPrompt')}</Label><Textarea id="validation-prompt" rows={3} disabled={busy} value={prompt} onChange={event => setPrompt(event.target.value)} />
        {needsMedia && <><Label htmlFor="validation-media">{t(task.data_type === 'video_text' ? 'finetune.newVideo' : 'finetune.newImage')}</Label><Input id="validation-media" type="file" disabled={busy} accept={task.data_type === 'video_text' ? '.mp4,.webm,.mov' : '.png,.jpg,.jpeg,.webp'} onChange={event => setFile(event.target.files?.[0])} />{preview && (task.data_type === 'video_text' ? <video src={preview} controls className="max-h-56 max-w-full" /> : <img src={preview} alt={t('finetune.newImage')} className="max-h-56 max-w-full" />)}</>}
        <div className="flex items-center gap-2"><Checkbox id="compare-base" disabled={busy} checked={compare} onCheckedChange={value => setCompare(value === true)} /><Label htmlFor="compare-base">{t('finetune.compareBase')}</Label></div>
        <Button disabled={busy} onClick={() => void handleValidate()}>{t(busy ? 'finetune.inferenceRunning' : 'finetune.runReloadInference')}</Button>
        {error && <p role="alert" className="text-sm text-red-500">{error}</p>}
        {baseAnswer && <div><h3>{t('finetune.baseAnswer')}</h3><pre className="whitespace-pre-wrap break-words border rounded-md p-3">{baseAnswer}</pre></div>}
        {answer && <div><h3>{t('finetune.adapterAnswer')}</h3><pre className="whitespace-pre-wrap break-words border rounded-md p-3">{answer}</pre><p className="text-sm text-muted-foreground">{t('finetune.inferenceQualityHint')}</p></div>}
        {!answer && task.inference_validation && <details><summary>{t('finetune.lastValidation')}</summary><pre className="whitespace-pre-wrap break-all text-xs">{JSON.stringify(task.inference_validation, null, 2)}</pre></details>}
    </section>;
}
