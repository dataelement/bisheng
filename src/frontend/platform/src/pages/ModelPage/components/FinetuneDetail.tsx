import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button, Tag } from '@bisheng/ui';
import EditLabel from '@/components/bs-ui/editLabel';
import { bsConfirm } from '@/components/bs-ui/alertDialog/useConfirm';
import { showApiError } from '@/controllers/request';
import { cancelTraining, getTrainingInfo, TrainingInfo } from '@/controllers/API/finetuneV2';
import { publishTaskApi, unPublishTaskApi, updataTaskNameApi } from '@/controllers/API/finetune';
import { FinetuneLoss } from './FinetuneLoss';
import { FinetuneValidation } from './FinetuneValidation';
import { downloadTrainingText } from './finetuneHelpers';

export const enum TaskStatus { TRAINING_IN_PROGRESS = 1, TRAINING_FAILED, TASK_ABORTED, TRAIN_SUCCESS, PUBLISH_SUCCESS }
export function BadgeView({ value, stage }: { value: number; stage?: string }) {
    const { t } = useTranslation('model');
    const keys = ['', 'trainingInProgress', 'trainingFailed', 'taskAborted', 'trainingSuccess', 'publishSuccess'];
    return <Tag>{t(`finetune.${stage === 'cancelling' ? 'cancelling' : keys[value] || 'unknownStatus'}`)}</Tag>;
}
interface Props { id: string; onDelete: () => void; onStatusChange: (status?: number) => void }
export function FinetuneDetail({ id, onDelete, onStatusChange }: Props) {
    const { t } = useTranslation('model');
    const [info, setInfo] = useState<TrainingInfo>();
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState('');
    const translate = useRef(t); translate.current = t;
    const statusChanged = useRef(onStatusChange); statusChanged.current = onStatusChange;
    const previousStatus = useRef<number>();
    const activeId = useRef(id); activeId.current = id;
    const handleRefresh = useCallback(async () => {
        try {
            const data = await getTrainingInfo(id);
            if (activeId.current !== id) return;
            setInfo(data); setError('');
            if (previousStatus.current != null && data.finetune.status !== previousStatus.current) statusChanged.current(data.finetune.status);
            previousStatus.current = data.finetune.status;
        } catch { if (activeId.current === id) setError(translate.current('finetune.refreshFailed')); }
    }, [id]);
    useEffect(() => {
        setInfo(undefined); previousStatus.current = undefined;
        let active = true;
        let timer: ReturnType<typeof setTimeout>;
        const poll = async () => { await handleRefresh(); if (active) timer = setTimeout(() => void poll(), 5000); };
        void poll();
        return () => { active = false; clearTimeout(timer); };
    }, [handleRefresh]);
    const handleStop = () => bsConfirm({ desc: t('finetune.confirmStopTraining'), onOk: async next => {
        next(); setBusy(true);
        try { await cancelTraining(id); await handleRefresh(); } catch (error) { showApiError(error); } finally { setBusy(false); }
    } });
    const handleDelete = () => bsConfirm({ desc: t('finetune.confirmDeleteModel', { name: info?.finetune.model_name }), onOk: next => { next(); onDelete(); } });
    const handlePublish = async (cancel: boolean) => {
        setBusy(true);
        try { await (cancel ? unPublishTaskApi(id) : publishTaskApi(id)); await handleRefresh(); } catch (error) { showApiError(error); } finally { setBusy(false); }
    };
    if (!info) return <p role="status">{error || t('finetune.loadingTask')}</p>;
    const task = info.finetune;
    const logs = info.train_log || (typeof info.log === 'string' ? info.log : JSON.stringify(info.log ?? '', null, 2));
    const config = info.config_snapshot || info.report?.train_config || task.report?.train_config || task.extra_params;
    const isV2 = task.contract_version === 2 || task.extra_params?.contract_version === 2;
    const completed = task.status === TaskStatus.TRAIN_SUCCESS || task.status === TaskStatus.PUBLISH_SUCCESS;
    return <div className="space-y-4 pb-8">
        <div className="flex flex-wrap gap-2 items-center"><EditLabel rule={[{pattern: /^(?=.*[a-zA-Z])(?=.*\d)?[a-zA-Z\d_-]+$/, message: t('finetune.enterModelName')}]} str={task.model_name} onChange={async name => { await updataTaskNameApi(id, name); setInfo(current => current ? {...current, finetune: {...current.finetune, model_name: name}} : current); statusChanged.current(task.status); }}>{name => <h2 className="text-lg font-semibold break-all">{name}</h2>}</EditLabel><BadgeView value={task.status} stage={task.stage} /><Button size="small" variant="outlined" disabled={busy} onClick={() => void handleRefresh()}>{t('finetune.refresh')}</Button>
            {task.status === TaskStatus.TRAINING_IN_PROGRESS ? <Button size="small" variant="outlined" disabled={busy || task.stage === 'cancelling'} onClick={handleStop}>{t('finetune.stop')}</Button> : <Button size="small" variant="outlined" disabled={busy} onClick={handleDelete}>{t('bs:delete')}</Button>}
            {!isV2 && completed && <Button size="small" disabled={busy} onClick={() => void handlePublish(task.status === TaskStatus.PUBLISH_SUCCESS)}>{t(task.status === TaskStatus.PUBLISH_SUCCESS ? 'finetune.cancelPublish' : 'finetune.publish')}</Button>}
        </div>
        {error && <p role="alert" className="text-sm text-red-500">{error}</p>}
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm"><dt>{t('finetune.taskId')}</dt><dd className="break-all">{task.id}</dd><dt>{t('finetune.baseModel')}</dt><dd>{task.base_model_name}</dd><dt>{t('finetune.dataType')}</dt><dd>{t(`finetune.type_${task.data_type || 'text'}`)}</dd><dt>{t('finetune.createTime')}</dt><dd>{task.create_time?.replace('T', ' ')}</dd><dt>{t('finetune.creator')}</dt><dd>{task.user_name}</dd><dt>{t('finetune.dataset')}</dt><dd>{[...(task.train_data || []), ...(task.preset_data || [])].map(file => file.name).join(', ')}</dd></dl>
        {task.reason && <p role="alert" className="text-sm text-red-500 break-words">{task.reason}</p>}
        <div className="border-t pt-4 space-y-2"><div className="flex justify-between items-center"><h3>{t('finetune.trainingLogs')}</h3><Button size="small" variant="outlined" onClick={() => downloadTrainingText(`${id}.log`, logs)}>{t('finetune.downloadLogs')}</Button></div><pre className="text-xs whitespace-pre-wrap break-all bg-muted rounded-md p-3 max-h-[320px] overflow-auto">{logs || t('finetune.awaitingLogs')}</pre></div>
        <FinetuneLoss samples={info.loss_data} />
        {config && <details><summary>{t('finetune.actualConfiguration')}</summary><pre className="text-xs whitespace-pre-wrap break-all p-3">{JSON.stringify(config, null, 2)}</pre><Button size="small" variant="outlined" onClick={() => downloadTrainingText(`${id}-config.json`, JSON.stringify(config, null, 2))}>{t('finetune.exportConfiguration')}</Button></details>}
        {task.artifact_report && <section className="border-t pt-4 space-y-2"><h3>{t('finetune.trainingArtifacts')}</h3><p>{t(task.artifact_report.complete ? 'finetune.artifactsComplete' : 'finetune.artifactsIncomplete')}</p><pre className="text-xs whitespace-pre-wrap break-all max-h-48 overflow-auto">{JSON.stringify(task.artifact_report, null, 2)}</pre></section>}
        {isV2 && completed && task.artifact_report?.complete && <FinetuneValidation key={id} task={task} />}
        {isV2 && completed && <p className="text-sm text-muted-foreground">{t('finetune.deploymentSeparate')}</p>}
    </div>;
}
