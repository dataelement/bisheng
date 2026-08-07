import { useCallback, useEffect, useState } from "react";
import {
    FileStatus,
    getKnowledgeParseQueuePositionsApi,
    type KnowledgeParseQueuePositionItem,
    type UploadedFileRecord,
} from "~/api/knowledge";
import s from "../PortalKnowledgeWorkbench.module.css";

interface PortalUploadQueueStatusProps {
    status?: FileStatus;
    position?: KnowledgeParseQueuePositionItem;
}

function queuePositionKey(spaceId: string | number, fileId: string | number): string {
    return `${spaceId}:${fileId}`;
}

function isQueuePositionCandidate(record: UploadedFileRecord): boolean {
    return record.status === FileStatus.WAITING
        || record.status === FileStatus.PROCESSING
        || record.status === FileStatus.REBUILDING;
}

function uploadStatusLabel(status?: FileStatus): string {
    switch (status) {
        case FileStatus.PROCESSING:
            return "解析中";
        case FileStatus.SUCCESS:
            return "解析完成";
        case FileStatus.WAITING:
            return "等待解析";
        case FileStatus.FAILED:
            return "解析失败";
        case FileStatus.REBUILDING:
            return "重新解析";
        case FileStatus.TIMEOUT:
            return "解析超时";
        case FileStatus.VIOLATION:
            return "内容违规";
        default:
            return "--";
    }
}

function uploadStatusClassName(status?: FileStatus): string {
    switch (status) {
        case FileStatus.SUCCESS:
            return `${s.uploadRecordStatusBadge} ${s.uploadRecordStatusSuccess}`;
        case FileStatus.FAILED:
        case FileStatus.TIMEOUT:
        case FileStatus.VIOLATION:
            return `${s.uploadRecordStatusBadge} ${s.uploadRecordStatusDanger}`;
        case FileStatus.UPLOADING:
        case FileStatus.PROCESSING:
        case FileStatus.WAITING:
        case FileStatus.REBUILDING:
            return `${s.uploadRecordStatusBadge} ${s.uploadRecordStatusInfo}`;
        default:
            return s.uploadRecordStatusBadge;
    }
}

function queuePositionLabel(position?: KnowledgeParseQueuePositionItem): string | null {
    if (!position) return null;
    if (position.state === "queued" && position.aheadWaitingCount !== null) {
        return `排队中，前方约 ${position.aheadWaitingCount} 个等待任务`;
    }
    return null;
}

export function usePortalUploadQueuePositions(open: boolean, records: UploadedFileRecord[]) {
    const [positions, setPositions] = useState<Record<string, KnowledgeParseQueuePositionItem>>({});

    useEffect(() => {
        if (!open) {
            setPositions({});
            return;
        }

        const pendingBySpace = new Map<number, number[]>();
        records.forEach((record) => {
            if (!isQueuePositionCandidate(record)) return;
            const knowledgeId = Number(record.spaceId);
            const fileId = Number(record.id);
            if (!Number.isInteger(knowledgeId) || knowledgeId <= 0 || !Number.isInteger(fileId) || fileId <= 0) {
                return;
            }
            const fileIds = pendingBySpace.get(knowledgeId) ?? [];
            if (!fileIds.includes(fileId)) fileIds.push(fileId);
            pendingBySpace.set(knowledgeId, fileIds);
        });

        if (!pendingBySpace.size) {
            setPositions({});
            return;
        }

        let cancelled = false;
        void Promise.allSettled(
            Array.from(pendingBySpace.entries()).map(async ([knowledgeId, fileIds]) => ({
                knowledgeId,
                response: await getKnowledgeParseQueuePositionsApi(knowledgeId, fileIds),
            })),
        ).then((results) => {
            if (cancelled) return;
            const nextPositions: Record<string, KnowledgeParseQueuePositionItem> = {};
            results.forEach((result) => {
                if (result.status !== "fulfilled") return;
                const { knowledgeId, response } = result.value;
                response.items.forEach((item) => {
                    nextPositions[queuePositionKey(knowledgeId, item.fileId)] = item;
                });
            });
            setPositions(nextPositions);
        });

        return () => {
            cancelled = true;
        };
    }, [open, records]);

    return useCallback(
        (record: UploadedFileRecord) => positions[queuePositionKey(record.spaceId, record.id)],
        [positions],
    );
}

export function PortalUploadQueueStatus({ status, position }: PortalUploadQueueStatusProps) {
    const queueStatusText = queuePositionLabel(position);
    return (
        <span className={s.uploadRecordStatusCell}>
            <span className={uploadStatusClassName(status)}>{uploadStatusLabel(status)}</span>
            {queueStatusText ? (
                <span className={s.uploadRecordQueueStatus} title={queueStatusText}>
                    {queueStatusText}
                </span>
            ) : null}
        </span>
    );
}
