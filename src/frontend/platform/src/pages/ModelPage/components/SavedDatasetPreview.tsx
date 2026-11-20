import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { DatasetSample, getTrainingDatasetMedia, getTrainingDatasetPreview } from '@/controllers/API/finetuneDatasets';

interface Props { versionId: string }
export function SavedDatasetPreview({ versionId }: Props) {
    const { t } = useTranslation('model');
    const [samples, setSamples] = useState<DatasetSample[]>([]);
    const [loading, setLoading] = useState(true);
    const [failed, setFailed] = useState(false);
    useEffect(() => {
        let active = true;
        const urls: string[] = [];
        setSamples([]); setFailed(false); setLoading(true);
        void getTrainingDatasetPreview(versionId).then(async response => {
            const rows = await Promise.all(response.samples.slice(0, 3).map(async sample => ({ ...sample,
                media: await Promise.all(sample.media.slice(0, 2).map(async media => {
                    const blob = await getTrainingDatasetMedia(versionId, media.url);
                    if (!active) return { ...media, url: '' };
                    const url = URL.createObjectURL(blob); urls.push(url); return { ...media, url };
                })) })));
            if (active) setSamples(rows);
        }).catch(() => { if (active) setFailed(true); }).finally(() => { if (active) setLoading(false); });
        return () => { active = false; urls.forEach(url => URL.revokeObjectURL(url)); };
    }, [versionId]);
    return <details className="pt-2"><summary className="text-sm cursor-pointer">{t('finetune.previewSamples')}</summary>
        {loading && <p role="status" className="text-sm">{t('finetune.datasetPreviewLoading')}</p>}
        {failed && <p role="alert" className="text-sm">{t('finetune.previewUnavailable')}</p>}
        {samples.map((sample, index) => <div key={index} className="border-t mt-2 pt-2 space-y-2">
            {sample.messages.map((message, position) => <p className="text-sm whitespace-pre-wrap break-words" key={position}><strong>{message.role}: </strong>{message.content}</p>)}
            {sample.media.filter(media => media.url).map(media => media.type === 'video'
                ? <video key={media.url} src={media.url} controls preload="metadata" className="max-h-40 max-w-full" aria-label={media.name} />
                : <img key={media.url} src={media.url} alt={media.name} className="max-h-40 max-w-full" />)}
        </div>)}
    </details>;
}
