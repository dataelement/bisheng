import { useCallback, useEffect, useRef, useState } from "react";
import {
    listMyUploadedFilesApi,
    type UploadedFileRecord,
} from "~/api/knowledge";
import { NotificationSeverity } from "~/common";
import { isKnowledgeItemPending } from "../../knowledgeUtils";

const PAGE_SIZE = 20;

interface UsePortalUploadedFilesOptions {
    open: boolean;
    refreshKey: number;
    showToast: (toast: { message: string; severity: NotificationSeverity }) => void;
}

function mergeRecordsById(
    currentRecords: UploadedFileRecord[],
    latestRecords: UploadedFileRecord[],
): UploadedFileRecord[] {
    const currentById = new Map(currentRecords.map((record) => [record.id, record]));
    return latestRecords.map((record) => ({
        ...currentById.get(record.id),
        ...record,
    }));
}

export function usePortalUploadedFiles({
    open,
    refreshKey,
    showToast,
}: UsePortalUploadedFilesOptions) {
    const [records, setRecords] = useState<UploadedFileRecord[]>([]);
    const [total, setTotal] = useState(0);
    const [page, setPage] = useState(1);
    const [loading, setLoading] = useState(false);
    const openRef = useRef(open);
    const showToastRef = useRef(showToast);
    const loadedPageRef = useRef<number | null>(null);
    const requestSequenceRef = useRef(0);
    openRef.current = open;
    showToastRef.current = showToast;

    const loadRecords = useCallback(async (pageToLoad: number, preserveRows: boolean) => {
        if (!openRef.current) return;
        const requestSequence = ++requestSequenceRef.current;
        if (!preserveRows) setLoading(true);
        try {
            const res = await listMyUploadedFilesApi({ page: pageToLoad, pageSize: PAGE_SIZE });
            if (!openRef.current || requestSequence !== requestSequenceRef.current) return;
            setRecords((current) => (
                preserveRows ? mergeRecordsById(current, res.data) : res.data
            ));
            setTotal(res.total);
            setPage(pageToLoad);
            loadedPageRef.current = pageToLoad;
        } catch {
            if (!openRef.current || requestSequence !== requestSequenceRef.current) return;
            if (!preserveRows) {
                setRecords([]);
                setTotal(0);
            }
            showToastRef.current({ message: "上传记录加载失败", severity: NotificationSeverity.ERROR });
        } finally {
            if (!preserveRows && requestSequence === requestSequenceRef.current) setLoading(false);
        }
    }, []);

    useEffect(() => {
        if (!open) {
            requestSequenceRef.current += 1;
            loadedPageRef.current = null;
            setPage(1);
            return;
        }
        void loadRecords(page, loadedPageRef.current === page);
    }, [loadRecords, open, page, refreshKey]);

    useEffect(() => {
        if (!open || !records.some((record) => isKnowledgeItemPending(record))) return;
        const timer = setInterval(() => void loadRecords(page, true), 5000);
        return () => clearInterval(timer);
    }, [loadRecords, open, page, records]);

    const refreshRecords = useCallback(
        () => loadRecords(page, true),
        [loadRecords, page],
    );

    return {
        records,
        setRecords,
        total,
        page,
        setPage,
        loading,
        totalPages: Math.max(1, Math.ceil(total / PAGE_SIZE)),
        refreshRecords,
    };
}
