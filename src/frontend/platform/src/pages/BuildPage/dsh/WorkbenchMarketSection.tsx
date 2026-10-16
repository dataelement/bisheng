import { Button } from "@/components/bs-ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog";
import { Input } from "@/components/bs-ui/input";
import { toast } from "@/components/bs-ui/toast/use-toast";
import { getMarketContext } from "@/controllers/API/dshMarket";
import {
    getMarketWorkbench, importWorkbenchBundle, listMarketWorkbenches, listWorkbenchImports,
    previewWorkbenchBundle, resumeWorkbenchImport,
} from "@/controllers/API/dshWorkbenches";
import type { MarketWorkbench, MarketWorkbenchDetail, WorkbenchImport, WorkbenchPreview } from "@/controllers/API/dshWorkbenches";
import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

const MAX_UPLOAD = 8 * 1024 * 1024;

export function WorkbenchMarketSection() {
    const { t } = useTranslation("dshMarket");
    const [tenant, setTenant] = useState<number | null>(null);
    const [page, setPage] = useState(1);
    const [data, setData] = useState<{ data: MarketWorkbench[]; total: number }>({ data: [], total: 0 });
    const [imports, setImports] = useState<WorkbenchImport[]>([]);
    const [detail, setDetail] = useState<MarketWorkbenchDetail | null>(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(false);
    const [busy, setBusy] = useState(false);
    const [uploadOpen, setUploadOpen] = useState(false);
    const [file, setFile] = useState<File | null>(null);
    const [displayName, setDisplayName] = useState("");
    const [preview, setPreview] = useState<WorkbenchPreview | null>(null);
    const [previewError, setPreviewError] = useState<string | null>(null);
    const [checking, setChecking] = useState(false);
    const [progress, setProgress] = useState<number | null>(null);
    const [refresh, setRefresh] = useState(0);
    const upload = useRef<AbortController | null>(null);
    const mounted = useRef(true);

    const reload = useCallback(() => setRefresh(value => value + 1), []);
    useEffect(() => {
        mounted.current = true;
        return () => { mounted.current = false; upload.current?.abort(); };
    }, []);
    useEffect(() => {
        if (tenant !== null) return;
        let active = true;
        getMarketContext().then(value => { if (active) setTenant(value.tenant_id); })
            .catch(() => { if (active) setError(true); });
        return () => { active = false; };
    }, [tenant, refresh]);
    useEffect(() => {
        if (tenant === null) return;
        const controller = new AbortController();
        setLoading(true); setError(false);
        listMarketWorkbenches(tenant, page, controller.signal).then(result => {
            if (controller.signal.aborted) return;
            if (page > 1 && result.data.length === 0) setPage(Math.max(1, Math.ceil(result.total / 20)));
            setData(result);
        }).catch(() => { if (!controller.signal.aborted) setError(true); })
            .finally(() => { if (!controller.signal.aborted) setLoading(false); });
        return () => controller.abort();
    }, [tenant, page, refresh]);
    useEffect(() => {
        if (tenant === null) return;
        let active = true;
        listWorkbenchImports(tenant).then(result => { if (active) setImports(result); })
            .catch(() => { if (active) setError(true); });
        return () => { active = false; };
    }, [tenant, refresh]);
    useEffect(() => {
        setPreview(null); setPreviewError(null);
        if (!uploadOpen || !file || tenant === null) { setChecking(false); return; }
        if (!file.name.toLowerCase().endsWith(".tgz") || file.size > MAX_UPLOAD) {
            setPreviewError(""); setChecking(false); return;
        }
        const controller = new AbortController();
        setChecking(true);
        previewWorkbenchBundle(file, tenant, controller.signal).then(result => {
            if (!controller.signal.aborted) setPreview(result);
        }).catch((failure: unknown) => {
            if (controller.signal.aborted) return;
            const message = typeof failure === "object" && failure !== null && "status_message" in failure
                ? String(failure.status_message) : "";
            setPreviewError(message.match(/^WB-\d+/)?.[0] || "");
        })
            .finally(() => { if (!controller.signal.aborted) setChecking(false); });
        return () => controller.abort();
    }, [file, tenant, uploadOpen]);

    async function openDetail(id: string) {
        try {
            const result = await getMarketWorkbench(id);
            if (mounted.current) setDetail(result);
        } catch { if (mounted.current) setError(true); }
    }

    async function uploadFile() {
        if (!file || tenant === null || !preview?.allowed || checking || displayName.length > 128) return;
        if (!file.name.toLowerCase().endsWith(".tgz") || file.size > MAX_UPLOAD) {
            toast({ title: t("workbenchInvalidFile"), description: "", variant: "error" }); return;
        }
        const controller = new AbortController(); upload.current = controller;
        setBusy(true); setProgress(0);
        try {
            const task = await importWorkbenchBundle(file, tenant, displayName, controller.signal, setProgress);
            if (task.status === "failed") {
                toast({ title: t("workbenchValidationFailed"), description: task.error_code, variant: "error" });
            } else {
                toast({ title: t("workbenchImported"), description: "" });
                setUploadOpen(false); setFile(null); setDisplayName("");
            }
        } catch { if (!controller.signal.aborted && mounted.current) setError(true); }
        finally { if (mounted.current) { setBusy(false); setProgress(null); reload(); } }
    }

    const reason = preview?.reason === "lower_version" ? "workbenchLowerVersion"
        : preview?.reason === "version_conflict" ? "workbenchVersionConflict"
            : preview?.reason === "identity_conflict" ? "workbenchIdentityConflict"
                : preview?.duplicate ? "workbenchDuplicate" : "workbenchReady";

    return <section className="space-y-6 pt-6">
        <header className="flex items-start justify-between gap-6">
            <div className="space-y-3"><h2 className="text-xl font-semibold">{t("workbenchTitle")}</h2>
                <p className="text-muted-foreground">{t("workbenchIntro")}</p></div>
            <Button className="shrink-0" disabled={tenant === null || busy} onClick={() => setUploadOpen(true)}>
                {t("workbenchImport")}
            </Button>
        </header>
        {error && <div role="alert" className="text-red-600 flex items-center gap-3">{t("loadFailed")}
            <Button variant="outline" onClick={reload}>{t("retry")}</Button></div>}
        {loading ? <p role="status">{t("loading")}</p> : <div className="border rounded-lg overflow-x-auto">
            <table className="w-full text-sm text-left"><thead className="bg-muted"><tr>
                {["workbenchName", "version", "workbenchIdentity", "updated", "actions"].map(key =>
                    <th className="p-4" key={key}>{t(key)}</th>)}
            </tr></thead><tbody>{data.data.map(row => <tr key={row.id} className="border-t">
                <td className="p-4"><strong>{row.display_name}</strong><p className="text-muted-foreground max-w-md">{row.description}</p></td>
                <td className="p-4">{row.current_version.version}</td>
                <td className="p-4">{row.workbench_key || row.legacy_id}</td>
                <td className="p-4">{new Date(/(?:Z|[+-]\d{2}:\d{2})$/.test(row.updated_at) ? row.updated_at : `${row.updated_at}Z`).toLocaleString()}</td>
                <td className="p-4"><Button variant="outline" onClick={() => void openDetail(row.id)}>{t("details")}</Button></td>
            </tr>)}</tbody></table>
            {!data.data.length && <p className="p-10 text-center text-muted-foreground">{t("workbenchEmpty")}</p>}
        </div>}
        <div className="flex items-center justify-end gap-4"><span>{t("workbenchTotal", { count: data.total })}</span>
            {data.total > 20 && <><Button variant="outline" disabled={page === 1 || loading} onClick={() => setPage(value => value - 1)}>{t("previous")}</Button>
                <span>{page}</span><Button variant="outline" disabled={page * 20 >= data.total || loading} onClick={() => setPage(value => value + 1)}>{t("next")}</Button></>}</div>
        {imports.some(job => job.status !== "completed") && <section className="border rounded-lg p-4 space-y-3">
            <h3 className="font-semibold">{t("imports")}</h3>
            {imports.filter(job => job.status !== "completed").map(job => <div key={job.id} className="flex gap-3 items-center text-sm">
                <span>{new Date(/(?:Z|[+-]\d{2}:\d{2})$/.test(job.created_at) ? job.created_at : `${job.created_at}Z`).toLocaleString()}</span>
                <span>{t(job.status)}</span><span>{job.error_code}</span>
                <Button variant="outline" disabled={busy} onClick={async () => {
                    setBusy(true);
                    try { await resumeWorkbenchImport(job.id, tenant!); reload(); }
                    catch { setError(true); }
                    finally { setBusy(false); }
                }}>{t("resume")}</Button>
            </div>)}</section>}
        <Dialog open={uploadOpen} onOpenChange={open => { if (!busy) setUploadOpen(open); }}><DialogContent>
            <DialogHeader><DialogTitle>{t("workbenchImport")}</DialogTitle>
                <DialogDescription>{t("workbenchUploadHint")}</DialogDescription></DialogHeader>
            <Input type="file" accept=".tgz,application/gzip" disabled={busy} aria-label={t("workbenchImport")}
                onChange={event => { setPreview(null); setFile(event.target.files?.[0] || null); }} />
            <Input value={displayName} disabled={busy} maxLength={128} aria-label={t("workbenchDisplayName")}
                placeholder={t("workbenchDisplayName")} onChange={event => setDisplayName(event.target.value)} />
            {checking && <p role="status">{t("previewing")}</p>}
            {previewError !== null && <p role="alert" className="text-sm text-red-600">
                {t("workbenchPreviewFailed")}{previewError && ` (${previewError})`}
            </p>}
            {preview && <div className="rounded-md border p-3 space-y-2 text-sm">
                <p className="font-medium">{preview.suggested_display_name}</p>
                <p>{preview.current_version || t("workbenchFirstImport")} → {preview.incoming_version}</p>
                <p>{t("workbenchIdentity")}: {preview.workbench_key || preview.legacy_id}</p>
                {preview.identity_kind === "legacy" && <p className="text-amber-600">{t("workbenchLegacy")}</p>}
                <p className={preview.allowed ? "text-muted-foreground" : "text-red-600"}>{t(reason)}</p>
            </div>}
            {file && <p>{file.name} · {(file.size / 1048576).toFixed(1)} MiB</p>}
            {progress !== null && <p role="status">{progress < 100 ? `${progress}%` : t("validating")}</p>}
            <div className="flex gap-3 justify-end"><Button variant="outline" onClick={() => {
                upload.current?.abort(); if (!busy) setUploadOpen(false);
            }}>{t("cancel")}</Button><Button disabled={!file || busy || checking || !preview?.allowed || displayName.length > 128}
                onClick={() => void uploadFile()}>{t("workbenchImport")}</Button></div>
        </DialogContent></Dialog>
        <Dialog open={Boolean(detail)} onOpenChange={open => { if (!open) setDetail(null); }}>
            <DialogContent className="max-w-3xl max-h-[85vh] overflow-y-auto">
                {detail && <><DialogHeader><DialogTitle>{detail.display_name}</DialogTitle>
                    <DialogDescription>{detail.description}</DialogDescription></DialogHeader>
                    <div className="space-y-2 text-sm">
                        <p>{t("version")}: {detail.current_version.version}</p>
                        <p>{t("workbenchIdentity")}: {detail.workbench_key || detail.legacy_id}</p>
                        {detail.identity_kind === "legacy" && <p className="text-amber-600">{t("workbenchLegacy")}</p>}
                        <p>{t("workbenchStaticOnly")}</p>
                        <p>{t("workbenchPackageName")}: {detail.package_name}</p>
                        <p>{t("license")}: {detail.package_metadata.license || "—"}</p>
                        <p className="break-all">SHA-256: {detail.current_version.sha256}</p>
                    </div></>}
            </DialogContent>
        </Dialog>
    </section>;
}
