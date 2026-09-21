import { Button } from "@/components/bs-ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog";
import { Input } from "@/components/bs-ui/input";
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import { toast } from "@/components/bs-ui/toast/use-toast";
import { userContext } from "@/contexts/userContext";
import { deleteMarketPlugin, getMarketContext, getMarketPlugin, importMarketBundle, listMarketImports, listMarketPlugins, resumeMarketImport } from "@/controllers/API/dshMarket";
import type { MarketImport, MarketPlugin } from "@/controllers/API/dshMarket";
import { canManageWorkbenchConfig } from "@/pages/ModelPage/manage/permissions";
import { useCallback, useContext, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

const MAX_UPLOAD = 256 * 1024 * 1024;

export function PluginMarketPage() {
    const { user } = useContext(userContext);
    const { t } = useTranslation("dshMarket");
    if (!canManageWorkbenchConfig(user)) return <div className="p-8">{t("forbidden")}</div>;
    return <TenantPluginMarket key={`${user.user_id}:${user.tenant_id}`} />;
}

function TenantPluginMarket() {
    const { t } = useTranslation("dshMarket");
    const [tenant, setTenant] = useState<number | null>(null);
    const [page, setPage] = useState(1);
    const [data, setData] = useState<{ data: MarketPlugin[]; total: number }>({ data: [], total: 0 });
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(false);
    const [detail, setDetail] = useState<MarketPlugin | null>(null);
    const [imports, setImports] = useState<MarketImport[]>([]);
    const [busy, setBusy] = useState(false);
    const [uploadOpen, setUploadOpen] = useState(false);
    const [file, setFile] = useState<File | null>(null);
    const [progress, setProgress] = useState<number | null>(null);
    const [refresh, setRefresh] = useState(0);
    const upload = useRef<AbortController | null>(null);

    useEffect(() => {
        if (tenant !== null) return;
        let active = true;
        getMarketContext().then(value => { if (active) setTenant(value.tenant_id); }).catch(() => { if (active) setError(true); });
        return () => { active = false; };
    }, [tenant, refresh]);
    const reload = useCallback(() => setRefresh(v => v + 1), []);
    useEffect(() => {
        if (tenant === null) return;
        const controller = new AbortController();
        setLoading(true); setError(false);
        listMarketPlugins({ page }, tenant, controller.signal)
            .then(result => {
                if (controller.signal.aborted) return;
                if (page > 1 && result.data.length === 0) setPage(Math.max(1, Math.ceil(result.total / 20)));
                setData(result);
            })
            .catch(() => { if (!controller.signal.aborted) setError(true); })
            .finally(() => { if (!controller.signal.aborted) setLoading(false); });
        return () => controller.abort();
    }, [page, tenant, refresh]);
    useEffect(() => {
        if (tenant === null) return;
        let active = true;
        listMarketImports(tenant).then(jobs => {
            if (active) setImports(jobs);
        }).catch(() => { if (active) setError(true); });
        return () => { active = false; };
    }, [tenant, refresh]);
    const mounted = useRef(true);
    useEffect(() => {
        mounted.current = true;
        return () => { mounted.current = false; upload.current?.abort(); };
    }, []);

    async function openDetail(id: string) {
        try {
            const result = await getMarketPlugin(id, tenant!);
            if (mounted.current) setDetail(result);
        } catch { setError(true); }
    }

    function remove(selected: MarketPlugin) {
        bsConfirm({ title: t("delete"), desc: t("deleteConfirm", { name: selected.display_name }),
            okTxt: t("delete"), canelTxt: t("cancel"), onOk: async (close: () => void) => {
                if (!mounted.current) return;
                setBusy(true);
                try {
                    await deleteMarketPlugin(selected);
                    if (mounted.current) {
                        setDetail(value => value?.id === selected.id ? null : value);
                        toast({ title: t("deleted"), description: "" }); reload();
                    }
                    close();
                } catch { if (mounted.current) setError(true); } finally { if (mounted.current) setBusy(false); }
            } });
    }

    async function uploadFile() {
        if (!file || tenant === null) return;
        if (!file.name.toLowerCase().endsWith(".zip") || file.size > MAX_UPLOAD) {
            toast({ title: t("invalidFile"), description: "", variant: "error" }); return;
        }
        const controller = new AbortController(); upload.current = controller;
        setBusy(true); setProgress(0);
        try {
            const task = await importMarketBundle(file, tenant, controller.signal, setProgress);
            if (task.status === "failed") toast({ title: t("validationFailed"), description: task.error, variant: "error" });
            else { toast({ title: t("imported"), description: "" }); setUploadOpen(false); setFile(null); }
        } catch { if (!controller.signal.aborted) setError(true); }
        finally { setBusy(false); setProgress(null); reload(); }
    }

    return <main className="h-full overflow-auto p-6 space-y-6">
        <header className="flex items-start justify-between gap-6">
            <div className="space-y-3">
                <h1 className="text-xl font-semibold">{t("title")}</h1>
                <p className="text-muted-foreground">{t("intro")}</p>
            </div>
            <Button className="shrink-0" disabled={tenant === null || busy} onClick={() => setUploadOpen(true)}>{t("import")}</Button>
        </header>
        {error && <div role="alert" className="text-red-600 flex items-center gap-3">{t("loadFailed")}<Button variant="outline" onClick={reload}>{t("retry")}</Button></div>}
        {loading ? <p role="status">{t("loading")}</p> : <div className="border rounded-lg overflow-x-auto">
            <table className="w-full text-sm text-left"><thead className="bg-muted"><tr>
                {["name", "version", "platform", "updated", "actions"].map(key => <th className="p-4" key={key}>{t(key)}</th>)}
            </tr></thead><tbody>{data.data.map(plugin => {
                const current = plugin.versions.find(v => v.id === plugin.current_version_id);
                const shownVersion = current || plugin.versions[0];
                return <tr key={plugin.id} className="border-t"><td className="p-4"><strong>{plugin.display_name}</strong><p className="text-muted-foreground max-w-md">{plugin.description}</p></td>
                    <td className="p-4">{shownVersion?.version || "—"}</td><td className="p-4">{Object.keys(shownVersion?.manifest.targets || {}).join(", ")}</td>
                    <td className="p-4">{new Date(`${plugin.updated_at}Z`).toLocaleString()}</td>
                    <td className="p-4"><div className="flex gap-2">
                        <Button variant="outline" disabled={busy} onClick={() => void openDetail(plugin.id)}>{t("details")}</Button>
                        <Button variant="outline" className="text-red-600" disabled={busy} onClick={() => remove(plugin)}>{t("delete")}</Button>
                    </div></td></tr>;
            })}</tbody></table>
            {!data.data.length && <p className="p-10 text-center text-muted-foreground">{t("empty")}</p>}
        </div>}
        <div className="flex items-center justify-end gap-4"><span>{t("total", { count: data.total })}</span>
            {data.total > 20 && <><Button variant="outline" disabled={page === 1 || loading} onClick={() => setPage(v => v - 1)}>{t("previous")}</Button>
            <span>{page}</span><Button variant="outline" disabled={page * 20 >= data.total || loading} onClick={() => setPage(v => v + 1)}>{t("next")}</Button></>}</div>
        {imports.some(job => job.status === "validating" || job.status === "failed") && <section className="border rounded-lg p-4 space-y-3"><h2 className="font-semibold">{t("imports")}</h2>
            {imports.filter(job => job.status === "validating" || job.status === "failed").map(job => <div key={job.id} className="flex gap-3 items-center text-sm">
                <span>{new Date(`${job.created_at}Z`).toLocaleString()}</span><span>{t(job.status)}</span><span>{job.error}</span>
                {job.status === "validating" && <Button variant="outline" disabled={busy} onClick={async () => {
                    setBusy(true); try { await resumeMarketImport(job.id, tenant!); reload(); } catch { setError(true); } finally { setBusy(false); }
                }}>{t("resume")}</Button>}</div>)}</section>}
        <Dialog open={uploadOpen} onOpenChange={open => { if (!busy) setUploadOpen(open); }}><DialogContent><DialogHeader>
            <DialogTitle>{t("import")}</DialogTitle><DialogDescription>{t("uploadHint")}</DialogDescription></DialogHeader>
            <details className="space-y-2 rounded-lg border p-3 text-sm">
                <summary className="cursor-pointer font-medium">{t("bundleGuide")}</summary>
                <p>{t("bundleSource")}</p><p>{t("bundleFormat")}</p><p>{t("bundleIdentity")}</p>
            </details>
            <Input type="file" accept=".zip,application/zip" disabled={busy} aria-label={t("import")} onChange={e => setFile(e.target.files?.[0] || null)} />
            {file && <p>{file.name} · {(file.size / 1048576).toFixed(1)} MiB</p>}
            {progress !== null && <p role="status">{progress < 100 ? `${progress}%` : t("validating")}</p>}
            <div className="flex gap-3 justify-end"><Button variant="outline" onClick={() => {
                upload.current?.abort(); if (!busy) setUploadOpen(false);
            }}>{t("cancel")}</Button><Button disabled={!file || busy} onClick={() => void uploadFile()}>{t("import")}</Button></div>
        </DialogContent></Dialog>
        <Dialog open={Boolean(detail)} onOpenChange={open => { if (!open && !busy) setDetail(null); }}><DialogContent className="max-w-3xl max-h-[85vh] overflow-y-auto">
            {detail && <><DialogHeader><DialogTitle>{detail.display_name}</DialogTitle><DialogDescription>{detail.description}</DialogDescription></DialogHeader>
                <h2 className="font-semibold">{t("versions")}</h2>{detail.versions.map(version => <section key={version.id} className="border rounded-md p-4 space-y-2">
                    <strong>{version.version}</strong>
                    <p>{t("publisher")}: {version.manifest.plugin.publisher} · {t("license")}: {version.manifest.plugin.license}</p>
                    <p>{t("platform")}: {Object.keys(version.manifest.targets).join(", ")} · Desktop ≥ {version.manifest.plugin.desktop_min}</p>
                    <p>{t("permissions")}: {version.manifest.plugin.permissions.join(", ") || "—"}</p>
                    <p className="break-all">{t("services")}: {version.manifest.plugin.services.join(", ") || "—"}</p>
                    <p className="whitespace-pre-wrap">{version.manifest.plugin.changelog}</p><p className="text-xs break-all">SHA-256: {version.digest}</p>
                </section>)}
                </>}
        </DialogContent></Dialog>
    </main>;
}
