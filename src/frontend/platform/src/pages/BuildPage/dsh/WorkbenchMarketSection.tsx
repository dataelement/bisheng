import { Button, notification, Pagination } from "@bisheng/ui";
import { usePaginationLocale } from "@/hooks/usePaginationLocale";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog";
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import { showApiError } from "@/controllers/request";
import { getMarketContext } from "@/controllers/API/dshMarket";
import {
    deleteMarketWorkbench, getMarketWorkbench, listMarketWorkbenches, listWorkbenchImports,
    resumeWorkbenchImport,
} from "@/controllers/API/dshWorkbenches";
import type { MarketWorkbench, MarketWorkbenchDetail, WorkbenchImport } from "@/controllers/API/dshWorkbenches";
import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { WorkbenchImportDialog } from "./WorkbenchImportDialog";

export function WorkbenchMarketSection() {
    const { t } = useTranslation(["dshMarket", "api_errors"]);
    const paginationLocale = usePaginationLocale();
    const [tenant, setTenant] = useState<number | null>(null);
    const [page, setPage] = useState(1);
    const [data, setData] = useState<{ data: MarketWorkbench[]; total: number }>({ data: [], total: 0 });
    const [imports, setImports] = useState<WorkbenchImport[]>([]);
    const [detail, setDetail] = useState<MarketWorkbenchDetail | null>(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(false);
    const [busy, setBusy] = useState(false);
    const [uploadOpen, setUploadOpen] = useState(false);
    const [refresh, setRefresh] = useState(0);
    const mounted = useRef(true);
    const deletion = useRef<AbortController | null>(null);
    const deleteLock = useRef(false);
    const detailRequest = useRef(0);

    const reload = useCallback(() => setRefresh(value => value + 1), []);
    useEffect(() => {
        mounted.current = true;
        return () => { mounted.current = false; deletion.current?.abort(); };
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
    async function openDetail(id: string) {
        const sequence = ++detailRequest.current;
        try {
            const result = await getMarketWorkbench(id);
            if (mounted.current && sequence === detailRequest.current) setDetail(result);
        } catch { if (mounted.current && sequence === detailRequest.current) setError(true); }
    }

    function handleDelete(row: MarketWorkbench) {
        if (tenant === null || deleteLock.current || busy) return;
        deleteLock.current = true;
        const controller = new AbortController();
        deletion.current = controller;
        let submitting = false;
        const active = () => mounted.current && !controller.signal.aborted;
        const release = () => { if (active()) { deleteLock.current = false; setBusy(false); } };
        bsConfirm({
            title: t("delete"), desc: t("workbenchDeleteConfirm", { name: row.display_name }),
            okTxt: t("delete"), canelTxt: t("cancel"), signal: controller.signal,
            onClose: () => { release(); controller.abort(); },
            onOk: async close => {
                if (!active() || submitting) return;
                submitting = true;
                setBusy(true);
                try {
                    await deleteMarketWorkbench(row.id, row.revision, tenant, controller.signal);
                    if (!active()) return;
                    detailRequest.current++;
                    setDetail(null);
                    notification.open({ title: t("workbenchDeleted"), description: "", type: "success" });
                    reload();
                    close();
                } catch (failure) {
                    if (active()) showApiError(failure);
                } finally { submitting = false; if (active()) setBusy(false); }
            },
        });
    }

    return <section className="space-y-6 pt-6">
        <header className="flex items-start justify-between gap-6">
            <div className="space-y-3"><h2 className="text-xl font-semibold">{t("workbenchTitle")}</h2>
                <p className="text-muted-foreground">{t("workbenchIntro")}</p></div>
            <Button className="shrink-0" disabled={tenant === null || busy} onClick={() => setUploadOpen(true)}>
                {t("workbenchImport")}
            </Button>
        </header>
        {error && <div role="alert" className="text-red-600 flex items-center gap-3">{t("loadFailed")}
            <Button variant="outlined" color="default" onClick={reload}>{t("retry")}</Button></div>}
        {loading ? <p role="status">{t("loading")}</p> : <div className="border rounded-lg overflow-x-auto">
            <table className="w-full text-sm text-left"><thead className="bg-muted"><tr>
                {["workbenchName", "version", "workbenchIdentity", "updated", "actions"].map(key =>
                    <th className="p-4" key={key}>{t(key)}</th>)}
            </tr></thead><tbody>{data.data.map(row => <tr key={row.id} className="border-t">
                <td className="p-4"><strong>{row.display_name}</strong><p className="text-muted-foreground max-w-md">{row.description}</p></td>
                <td className="p-4">{row.current_version.version}</td>
                <td className="p-4">{row.workbench_key || row.legacy_id}</td>
                <td className="p-4">{new Date(/(?:Z|[+-]\d{2}:\d{2})$/.test(row.updated_at) ? row.updated_at : `${row.updated_at}Z`).toLocaleString()}</td>
                <td className="p-4"><div className="flex gap-2"><Button variant="outlined" color="default" onClick={() => void openDetail(row.id)}>{t("details")}</Button>
                    <Button variant="outlined" color="danger" disabled={busy} onClick={() => handleDelete(row)}>{t("delete")}</Button></div></td>
            </tr>)}</tbody></table>
            {!data.data.length && <p className="p-10 text-center text-muted-foreground">{t("workbenchEmpty")}</p>}
        </div>}
        <Pagination
            locale={paginationLocale}
            current={page}
            pageSize={20}
            total={data.total}
            showTotal
            disabled={loading}
            onChange={(nextPage) => setPage(nextPage)}
        />
        {imports.some(job => job.status !== "completed") && <section className="border rounded-lg p-4 space-y-3">
            <h3 className="font-semibold">{t("imports")}</h3>
            {imports.filter(job => job.status !== "completed").map(job => <div key={job.id} className="flex gap-3 items-center text-sm">
                <span>{new Date(/(?:Z|[+-]\d{2}:\d{2})$/.test(job.created_at) ? job.created_at : `${job.created_at}Z`).toLocaleString()}</span>
                <span>{t(job.status)}</span><span>{job.error_code}</span>
                <Button variant="outlined" color="default" disabled={busy} onClick={async () => {
                    setBusy(true);
                    try { await resumeWorkbenchImport(job.id, tenant!); reload(); }
                    catch { setError(true); }
                    finally { setBusy(false); }
                }}>{t("resume")}</Button>
            </div>)}</section>}
        {uploadOpen && tenant !== null && <WorkbenchImportDialog key={tenant} tenant={tenant}
            onClose={() => setUploadOpen(false)} onImported={reload} />}
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
