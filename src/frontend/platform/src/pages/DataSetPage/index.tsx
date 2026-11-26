import { useCallback, useContext, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button, Pagination, SearchInput, Select, Tag, toast } from '@bisheng/ui';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/bs-ui/dialog';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/bs-ui/table';
import { bsConfirm } from '@/components/bs-ui/alertDialog/useConfirm';
import { useSelectLabels } from '@/components/bs-comp/formFields/useSelectLabels';
import { usePaginationLocale } from '@/hooks/usePaginationLocale';
import { userContext } from '@/contexts/userContext';
import { showApiError } from '@/controllers/request';
import { CatalogDataset, DatasetCategory, convertCatalogDataset, deleteCatalogDataset, downloadCatalogDataset, listDatasetCatalog } from '@/controllers/API/finetuneDatasets';
import { downloadFile } from '@/util/utils';
import { checkSassUrl } from '@/components/bs-comp/FileView';
import { DatasetImportDialog } from '@/pages/ModelPage/components/DatasetImportDialog';
import { SavedDatasetPreview } from '@/pages/ModelPage/components/SavedDatasetPreview';
import type { TrainingDataType } from '@/controllers/API/finetuneV2';

const categories: DatasetCategory[] = ['legacy', 'text', 'image_text', 'video_text'];
export default function DataSetPage() {
    const { user } = useContext(userContext);
    const [revision, setRevision] = useState(0);
    useEffect(() => {
        const reset = () => setRevision(value => value + 1);
        window.addEventListener('bisheng:management-scope-changed', reset);
        return () => window.removeEventListener('bisheng:management-scope-changed', reset);
    }, []);
    return <DataSetContent key={`${user?.user_id}:${user?.leaf_tenant_id ?? user?.tenant_id}:${revision}`} />;
}

function DataSetContent() {
    const { t } = useTranslation('model');
    const selectLabels = useSelectLabels();
    const paginationLocale = usePaginationLocale();
    const [rows, setRows] = useState<CatalogDataset[]>([]);
    const [total, setTotal] = useState(0);
    const [page, setPage] = useState(1);
    const [keyword, setKeyword] = useState('');
    const [category, setCategory] = useState<DatasetCategory | 'all'>('all');
    const [importType, setImportType] = useState<TrainingDataType>('text');
    const [importOpen, setImportOpen] = useState(false);
    const [preview, setPreview] = useState<CatalogDataset>();
    const [loading, setLoading] = useState(false);
    const [busy, setBusy] = useState(false);
    const [failed, setFailed] = useState(false);
    const [revision, setRevision] = useState(0);
    const active = useRef(true);
    useEffect(() => { active.current = true; return () => { active.current = false; }; }, []);
    const reload = useCallback(() => setRevision(value => value + 1), []);
    useEffect(() => {
        let current = true;
        setLoading(true); setFailed(false);
        void listDatasetCatalog({ page, limit: 20, keyword, ...(category !== 'all' ? { data_type: category } : {}) })
            .then(result => { if (current) { setRows(result.data); setTotal(result.total); } })
            .catch(() => { if (current) { setRows([]); setTotal(0); setFailed(true); } })
            .finally(() => { if (current) setLoading(false); });
        return () => { current = false; };
    }, [page, keyword, category, revision]);
    const handleConvert = async (row: CatalogDataset) => {
        setBusy(true);
        try {
            await convertCatalogDataset(row.id);
            if (active.current) { toast.show({ type: 'success', message: t('finetune.conversionSucceeded') }); reload(); }
        } catch (error) { showApiError(error); }
        finally { if (active.current) setBusy(false); }
    };
    const handleDownload = async (row: CatalogDataset) => {
        try {
            const result = await downloadCatalogDataset(row.id);
            if (active.current) await downloadFile(checkSassUrl(result.url), row.name + (row.url.endsWith('.zip') ? '.zip' : '.json'));
        } catch (error) { showApiError(error); }
    };
    const handleDelete = (row: CatalogDataset) => bsConfirm({ desc: t('bs:dataset.confirmDelete'), onOk: async next => {
        if (!active.current) { next(); return; }
        await deleteCatalogDataset(row.id);
        if (active.current) reload();
        next();
    } });
    return <div className="relative h-full px-2 py-4">
        <div className="h-[calc(100vh-128px-var(--license-banner-h,0px))] overflow-y-auto pb-10 space-y-4">
            <div className="flex justify-end gap-3 items-center flex-wrap">
                <SearchInput placeholder={t('bs:dataset.name')} onChange={event => { setKeyword(event.target.value); setPage(1); }} className="w-56" />
                <Select {...selectLabels} value={category} aria-label={t('finetune.datasetCategory')} className="w-40" onChange={value => { setCategory(value as DatasetCategory | 'all'); setPage(1); }} options={[{ value: 'all', label: t('finetune.allDatasetCategories') }, ...categories.map(value => ({ value, label: t(`finetune.type_${value}`) }))]} />
                <Button disabled={busy} onClick={() => setImportOpen(true)}>{t('finetune.datasetImport')}</Button>
            </div>
            {loading && <p role="status">{t('finetune.datasetLoading')}</p>}
            {failed && <div role="alert"><span>{t('finetune.datasetListFailed')}</span><Button variant="link" onClick={reload}>{t('finetune.datasetRefresh')}</Button></div>}
            <Table><TableHeader><TableRow>
                <TableHead>{t('bs:dataset.name')}</TableHead><TableHead>{t('finetune.datasetCategory')}</TableHead><TableHead>{t('finetune.datasetOrigin')}</TableHead>
                <TableHead>{t('bs:dataset.creationTime')}</TableHead><TableHead>{t('bs:dataset.createUser')}</TableHead><TableHead className="text-right">{t('bs:operations')}</TableHead>
            </TableRow></TableHeader><TableBody>{rows.map(row => <TableRow key={row.id}>
                <TableCell className="max-w-[240px] break-all">{row.name}</TableCell>
                <TableCell><Tag>{t(`finetune.type_${row.data_type}`)}</Tag></TableCell><TableCell>{t(`finetune.datasetSource_${row.source_type}`)}</TableCell>
                <TableCell>{row.create_time?.replace('T', ' ')}</TableCell><TableCell>{row.user_name || '--'}</TableCell>
                <TableCell><div className="flex justify-end gap-2 flex-wrap">
                    {row.data_type === 'legacy' && <Button size="small" variant="link" disabled={busy} onClick={() => void handleConvert(row)}>{t('finetune.convertToText')}</Button>}
                    <Button size="small" variant="link" onClick={() => setPreview(row)}>{t('finetune.previewSamples')}</Button>
                    <Button size="small" variant="link" disabled={row.dataset_report?.delivery === 'remote'} onClick={() => void handleDownload(row)}>{t('bs:dataset.download')}</Button>
                    <Button size="small" variant="link" color="danger" onClick={() => handleDelete(row)}>{t('bs:delete')}</Button>
                </div></TableCell>
            </TableRow>)}</TableBody></Table>
            {!loading && !failed && !rows.length && <p>{t('finetune.datasetEmpty')}</p>}
        </div>
        <div className="bisheng-table-footer px-6 bg-background-login"><div className="ml-auto"><Pagination locale={paginationLocale} current={page} pageSize={20} total={total} onChange={setPage} /></div></div>
        {importOpen && <DatasetImportDialog dataType={importType} onDataTypeChange={setImportType} onClose={() => setImportOpen(false)} onImported={() => { reload(); }} />}
        <Dialog open={Boolean(preview)} onOpenChange={value => { if (!value) setPreview(undefined); }}><DialogContent className="max-w-[720px] max-h-[80vh] overflow-y-auto">
            <DialogHeader><DialogTitle>{preview?.name}</DialogTitle></DialogHeader>
            {preview && (preview.dataset_report?.delivery === 'remote' && !preview.dataset_report.preview_url
                ? <p>{t('finetune.datasetRemoteZipNoPreview')}</p> : <SavedDatasetPreview versionId={preview.id} kind="catalog" />)}
        </DialogContent></Dialog>
    </div>;
}
