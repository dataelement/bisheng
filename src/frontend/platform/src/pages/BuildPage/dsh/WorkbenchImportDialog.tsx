import { Button, Input, notification } from "@bisheng/ui";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog";
import { importWorkbenchBundle, previewWorkbenchBundle } from "@/controllers/API/dshWorkbenches";
import type { WorkbenchImport, WorkbenchPreview } from "@/controllers/API/dshWorkbenches";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { workbenchPreviewErrorMessage } from "./workbenchPreviewError";

interface WorkbenchImportDialogProps {
    tenant: number;
    onClose: () => void;
    onImported: () => void;
}

type Entry = {
    file: File;
    status: "pending" | "ready" | "rejected" | "duplicate" | "importing" | "completed" | "failed" | "validating";
    preview?: WorkbenchPreview;
    failure?: unknown;
    localError?: string;
    task?: WorkbenchImport;
};

function canImport(entry: Entry): boolean {
    return entry.status === "ready" || (entry.status === "duplicate" && entry.preview?.allowed === true);
}

const MAX_FILE = 100 * 1024 * 1024;

function rejectionReason(code: string): string | undefined {
    const reason = code.toLowerCase().replace(/^workbench_/, "");
    return reason === "lower_version" ? "workbenchLowerVersion"
        : reason === "version_conflict" ? "workbenchVersionConflict"
            : reason === "identity_conflict" ? "workbenchIdentityConflict" : undefined;
}

function previewReason(preview: WorkbenchPreview): string {
    return rejectionReason(preview.reason) || (!preview.allowed ? "workbenchBatch.status.rejected"
        : preview.allowed && preview.overwrite ? "overwriteVersion" : preview.duplicate ? "workbenchDuplicate" : "workbenchReady");
}

export function WorkbenchImportDialog({ tenant, onClose, onImported }: WorkbenchImportDialogProps) {
    const { t } = useTranslation(["dshMarket", "api_errors"]);
    const [files, setFiles] = useState<File[]>([]);
    const [entries, setEntries] = useState<Entry[]>([]);
    const [displayName, setDisplayName] = useState("");
    const [checking, setChecking] = useState(false);
    const [busy, setBusy] = useState(false);
    const [submitted, setSubmitted] = useState(false);
    const [progress, setProgress] = useState<number | null>(null);
    const request = useRef<AbortController | null>(null);
    const importLock = useRef(false);
    const needsRefresh = useRef(false);
    const batch = files.length > 1;
    const selectionError = files.length > 50 ? "workbenchBatch.countLimit" : null;

    useEffect(() => {
        const controller = new AbortController();
        request.current = controller;
        importLock.current = false;
        needsRefresh.current = false;
        setEntries([]); setChecking(false); setBusy(false); setProgress(null); setSubmitted(false);
        if (!files.length || selectionError) return () => { controller.abort(); request.current?.abort(); };
        const initial: Entry[] = files.map(file => ({
            file, status: "pending",
            localError: !file.name.toLowerCase().endsWith(".tgz") ? "workbenchPreview.fileType"
                : file.size > MAX_FILE ? "workbenchPreview.fileSize" : undefined,
        }));
        setEntries(initial);
        setChecking(true);
        // Keep one preview in flight so a selection cannot burst server resources.
        void (async () => {
            for (let index = 0; index < initial.length; index++) {
                if (controller.signal.aborted) return;
                let entry = initial[index];
                if (entry.localError) entry = { ...entry, status: "rejected" };
                else {
                    try {
                        const preview = await previewWorkbenchBundle(entry.file, tenant, controller.signal);
                        entry = { ...entry, preview, status: !preview.allowed ? "rejected" : batch && preview.duplicate ? "duplicate" : "ready" };
                    } catch (failure: unknown) {
                        entry = { ...entry, failure, status: "rejected" };
                    }
                }
                if (controller.signal.aborted) return;
                initial[index] = entry;
                setEntries([...initial]);
            }
            if (!controller.signal.aborted) setChecking(false);
        })();
        return () => { controller.abort(); request.current?.abort(); };
    }, [files, tenant, selectionError, batch]);

    function handleClose() {
        request.current?.abort();
        if (needsRefresh.current) { needsRefresh.current = false; onImported(); }
        onClose();
    }

    async function handleImport() {
        if (importLock.current || busy || checking || submitted || selectionError || displayName.length > 128 || !entries.some(canImport)) return;
        importLock.current = true;
        request.current?.abort();
        const controller = new AbortController();
        request.current = controller;
        setBusy(true); setSubmitted(true); setProgress(0);
        const result = [...entries];
        try {
            for (let index = 0; index < result.length; index++) {
                const entry = result[index];
                if (!canImport(entry)) continue;
                if (controller.signal.aborted) return;
                result[index] = { ...entry, status: "importing" };
                setEntries([...result]); setProgress(0);
                try {
                    const task = await importWorkbenchBundle(entry.file, tenant, batch ? "" : displayName, controller.signal,
                        percent => { if (!controller.signal.aborted) setProgress(percent); });
                    if (controller.signal.aborted) return;
                    result[index] = { ...entry, task, status: task.status };
                    needsRefresh.current = true;
                    if (!batch && task.status !== "validating") {
                        notification.open({ title: t(task.status === "failed" ? "workbenchValidationFailed" : "workbenchImported"),
                            description: [task.error_code, task.error].filter(Boolean).join(": "), ...(task.status === "failed" ? { type: "error" as const } : {}) });
                    }
                } catch (failure: unknown) {
                    if (controller.signal.aborted) return;
                    result[index] = { ...entry, failure, status: "failed" };
                }
                setEntries([...result]);
            }
            if (!controller.signal.aborted) {
                needsRefresh.current = false;
                onImported();
                if (!batch && result[0]?.status === "completed") onClose();
            }
        } finally {
            if (!controller.signal.aborted) { importLock.current = false; setBusy(false); setProgress(null); }
        }
    }

    const ready = entries.filter(canImport).length;
    return <Dialog open onOpenChange={open => { if (!open) handleClose(); }}><DialogContent className="max-h-[85vh] overflow-y-auto">
        <DialogHeader><DialogTitle>{t("workbenchImport")}</DialogTitle>
            <DialogDescription>{t("workbenchBatch.hint")}</DialogDescription></DialogHeader>
        <Input type="file" accept=".tgz,application/gzip" multiple disabled={busy} aria-label={t("workbenchImport")}
            onChange={event => {
                request.current?.abort();
                setEntries([]); setDisplayName(""); setSubmitted(false);
                setFiles(Array.from(event.target.files || []));
                event.target.value = "";
            }} />
        {!batch && <Input value={displayName} disabled={busy} maxLength={128} aria-label={t("workbenchDisplayName")}
            placeholder={t("workbenchDisplayName")} onChange={event => setDisplayName(event.target.value)} />}
        {selectionError && <p role="alert" className="text-sm text-red-600">{t(selectionError)}</p>}
        {selectionError && files.map((file, index) => <p key={index}>{file.name} · {(file.size / 1048576).toFixed(1)} MiB</p>)}
        {checking && <p role="status">{t("previewing")}</p>}
        {batch && entries.length > 0 && <p role="status">{t("workbenchBatch.summary", {
            total: entries.length, ready, rejected: entries.filter(entry => entry.status === "rejected").length,
            duplicate: entries.filter(entry => entry.status === "duplicate").length,
        })}</p>}
        {batch && submitted && <p role="status">{t("workbenchBatch.results", {
            completed: entries.filter(entry => entry.status === "completed").length,
            failed: entries.filter(entry => entry.status === "failed").length,
            rejected: entries.filter(entry => entry.status === "rejected").length,
        })}</p>}
        {entries.map((entry, index) => <div key={index} className="space-y-2 text-sm">
            <p>{entry.file.name} · {(entry.file.size / 1048576).toFixed(1)} MiB</p>
            {(batch || entry.task) && <p>{t("workbenchBatch.status." + entry.status)}</p>}
            {entry.localError && <p role="alert" className="text-sm text-red-600">{t(entry.localError)}</p>}
            {entry.failure !== undefined && <p role="alert" className="text-sm text-red-600 whitespace-pre-line">
                {workbenchPreviewErrorMessage(entry.failure, t)}</p>}
            {entry.preview && <div className="rounded-md border p-3 space-y-2 text-sm">
                <p className="font-medium">{entry.preview.suggested_display_name}</p>
                <p>{t("workbenchPackageName")}: {entry.preview.package_name}</p>
                <p>{entry.preview.current_version || t("workbenchFirstImport")} → {entry.preview.incoming_version}</p>
                <p>{t("workbenchIdentity")}: {entry.preview.workbench_key || entry.preview.legacy_id}</p>
                {entry.preview.identity_kind === "legacy" && <p className="text-amber-600">{t("workbenchLegacy")}</p>}
                <p className={entry.preview.allowed ? "text-muted-foreground" : "text-red-600"}>{t(previewReason(entry.preview))}</p>
                {!entry.preview.allowed && entry.preview.reason && !["lower_version", "version_conflict", "identity_conflict"].includes(entry.preview.reason) && <p>{entry.preview.reason}</p>}
                <p className="text-muted-foreground">{t("workbenchStaticOnly")}</p>
            </div>}
            {entry.task?.status === "failed" && <p role="alert" className="text-sm text-red-600 whitespace-pre-line">
                {rejectionReason(entry.task.error_code) && <>{t(rejectionReason(entry.task.error_code)!)}<br /></>}
                {entry.task.error_code}{entry.task.error ? ": " + entry.task.error : ""}</p>}
        </div>)}
        {progress !== null && <p role="status">{progress < 100 ? `${progress}%` : t("validating")}</p>}
        <div className="flex gap-3 justify-end"><Button variant="outlined" color="default" onClick={handleClose}>{t("cancel")}</Button>
            <Button disabled={busy || checking || submitted || selectionError !== null || ready === 0 || displayName.length > 128}
                onClick={() => void handleImport()}>{batch ? t("workbenchBatch.confirm", { count: ready }) : t("workbenchImport")}</Button></div>
    </DialogContent></Dialog>;
}
