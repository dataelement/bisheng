import { useTranslation } from 'react-i18next';

interface ArtifactFile { name: string; size: number; sha256: string }
interface Props { report: { complete?: boolean; files?: unknown[]; missing?: unknown[] } }

export function formatArtifactSize(bytes: number) {
    if (bytes >= 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024 / 1024).toFixed(1)} GB`;
    if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
    if (bytes >= 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${bytes} B`;
}

function artifactFiles(files: unknown[] | undefined): ArtifactFile[] {
    return (files || []).filter((file): file is ArtifactFile => {
        const item = file as Partial<ArtifactFile>;
        return typeof item?.name === 'string' && typeof item.size === 'number' && typeof item.sha256 === 'string';
    });
}

export function TrainingArtifacts({ report }: Props) {
    const { t } = useTranslation('model');
    const files = artifactFiles(report.files);
    const missing = (report.missing || []).filter((name): name is string => typeof name === 'string');
    return <section className="border-t pt-4 space-y-2">
        <h3>{t('finetune.trainingArtifacts')}</h3>
        <p>{t(report.complete ? 'finetune.artifactsComplete' : 'finetune.artifactsIncomplete')}</p>
        {missing.length > 0 && <p role="alert" className="text-sm text-red-500 break-words">
            {t('finetune.artifactsMissing', { files: missing.join(', ') })}
        </p>}
        {files.length > 0 && <table className="w-full text-xs">
            <thead>
                <tr className="text-left text-muted-foreground">
                    <th className="py-1 pr-4 font-normal">{t('finetune.artifactName')}</th>
                    <th className="py-1 pr-4 font-normal">{t('finetune.artifactSize')}</th>
                    <th className="py-1 font-normal">SHA-256</th>
                </tr>
            </thead>
            <tbody>
                {files.map(file => <tr key={file.name} className="border-t">
                    <td className="py-1 pr-4 break-all">{file.name}</td>
                    <td className="py-1 pr-4 whitespace-nowrap">{formatArtifactSize(file.size)}</td>
                    <td className="py-1 font-mono" title={file.sha256}>{file.sha256.slice(0, 16)}…</td>
                </tr>)}
            </tbody>
        </table>}
    </section>;
}
