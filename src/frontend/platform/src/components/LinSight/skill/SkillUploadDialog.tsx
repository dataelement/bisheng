// F035: import a skill from a local file (.md or .zip/.skill bundle, archive root
// must contain SKILL.md) or from a public GitHub directory URL. The size check here
// covers the uploaded bytes only; the cap comes from 系统配置
// (linsight.skill_upload_max_size_mb) via /skill/upload-limit, so the copy and the
// server agree on the number. The backend separately caps the unpacked contents and
// reports that as its own error code — do not merge the two.
import { Button } from "@/components/bs-ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog";
import { Input } from "@/components/bs-ui/input";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/bs-ui/tabs";
import { toast } from "@/components/bs-ui/toast/use-toast";
import { skillApi, type SkillUploadLimit } from "@/controllers/API/linsight";
import { Check, FileArchive, FileText, FileUp, Loader2, X } from "lucide-react";
import { MouseEvent, useCallback, useEffect, useState } from "react";
import { useDropzone } from "react-dropzone";
import { useTranslation } from "react-i18next";
import { getSkillErrorMessage } from "./skillErrors";

const ACCEPTED_SUFFIXES = ['.md', '.zip', '.skill'];
// Fallback only — mirrors the backend default; the live value is fetched when the dialog opens.
const DEFAULT_UPLOAD_LIMIT: SkillUploadLimit = {
    max_size_bytes: 10 * 1024 * 1024,
    max_size_mb: 10,
    max_unpacked_bytes: 100 * 1024 * 1024,
    max_unpacked_mb: 100,
};
const GITHUB_URL_PREFIX = 'https://github.com/';

// Human-readable size so a 10MB bundle doesn't render as an unwieldy "10240.0 KB".
function formatBytes(bytes: number): string {
    if (bytes < 1024) return `${bytes} B`;
    const kb = bytes / 1024;
    return kb < 1024 ? `${kb.toFixed(1)} KB` : `${(kb / 1024).toFixed(2)} MB`;
}

// Hint the picked file's kind: a document glyph for .md, an archive glyph for bundles.
function fileIcon(name: string) {
    return name.toLowerCase().endsWith('.md') ? FileText : FileArchive;
}

type ImportMode = 'file' | 'github';

interface SkillUploadDialogProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    onUploaded: () => void;
}

export function SkillUploadDialog({ open, onOpenChange, onUploaded }: SkillUploadDialogProps) {
    const { t } = useTranslation();
    const [mode, setMode] = useState<ImportMode>('file');
    const [file, setFile] = useState<File | null>(null);
    const [uploading, setUploading] = useState(false);
    const [githubUrl, setGithubUrl] = useState('');
    const [importing, setImporting] = useState(false);
    const [limit, setLimit] = useState<SkillUploadLimit>(DEFAULT_UPLOAD_LIMIT);

    useEffect(() => {
        if (open) {
            setMode('file');
            setFile(null);
            setGithubUrl('');
            // Refresh the cap on every open: an admin may have just raised it in 系统配置.
            skillApi.getUploadLimit()
                .then((res) => { if (res && typeof res.max_size_bytes === 'number') setLimit(res); })
                .catch(() => { /* keep the fallback; the server still enforces its own cap */ });
        }
    }, [open]);

    const handleDrop = useCallback((accepted: File[]) => {
        const picked = accepted[0];
        if (!picked) return;
        const lower = picked.name.toLowerCase();
        if (!ACCEPTED_SUFFIXES.some(suffix => lower.endsWith(suffix))) {
            toast({ variant: 'error', description: t('skillManage.uploadDialog.unsupported') });
            return;
        }
        if (picked.size > limit.max_size_bytes) {
            toast({ variant: 'error', description: t('skillManage.errors.tooLarge', { size: limit.max_size_mb }) });
            return;
        }
        setFile(picked);
    }, [t, limit]);

    const { getRootProps, getInputProps, isDragActive } = useDropzone({ onDrop: handleDrop, multiple: false });

    const handleRemoveFile = (e: MouseEvent) => {
        e.stopPropagation();
        setFile(null);
    };

    const SelectedFileIcon = file ? fileIcon(file.name) : FileText;

    // The backend auto-normalizes an illegal frontmatter name into a legal skill
    // ID (e.g. "Presentations" -> "presentations") — tell the user when it did.
    const toastImported = (detail: { name: string; normalized_from?: string | null }) => {
        toast({
            variant: 'success',
            description: detail.normalized_from
                ? t('skillManage.uploadDialog.normalized', { from: detail.normalized_from, to: detail.name })
                : t('skillManage.saved'),
        });
    };

    const handleUpload = async () => {
        if (!file || uploading) return;
        setUploading(true);
        try {
            const detail = await skillApi.createSkillUpload(file);
            toastImported(detail);
            onOpenChange(false);
            onUploaded();
        } catch (err) {
            toast({ variant: 'error', description: getSkillErrorMessage(err, t) });
        } finally {
            setUploading(false);
        }
    };

    const githubUrlValid = githubUrl.trim().startsWith(GITHUB_URL_PREFIX);

    const handleGithubImport = async () => {
        const url = githubUrl.trim();
        if (!githubUrlValid || importing) return;
        setImporting(true);
        try {
            const detail = await skillApi.importSkillFromGithub(url);
            toastImported(detail);
            onOpenChange(false);
            onUploaded();
        } catch (err) {
            toast({ variant: 'error', description: getSkillErrorMessage(err, t) });
        } finally {
            setImporting(false);
        }
    };

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="sm:max-w-[560px]">
                <DialogHeader>
                    <DialogTitle>{t('skillManage.upload')}</DialogTitle>
                </DialogHeader>

                <Tabs value={mode} onValueChange={(v) => setMode(v as ImportMode)}>
                    <TabsList className="w-[220px]">
                        <TabsTrigger value="file" className="flex-1">{t('skillManage.uploadDialog.tabFile')}</TabsTrigger>
                        <TabsTrigger value="github" className="flex-1">{t('skillManage.uploadDialog.tabGithub')}</TabsTrigger>
                    </TabsList>

                    <TabsContent value="file" className="space-y-3">
                        <div
                            {...getRootProps()}
                            className={`cursor-pointer rounded-lg border-2 border-dashed px-6 py-8 text-center transition-colors ${file
                                ? 'border-status-green/60 bg-success-background'
                                : isDragActive
                                    ? 'border-primary bg-primary/5'
                                    : 'border-border hover:border-primary/50 hover:bg-muted/40'}`}
                        >
                            <input {...getInputProps()} />
                            {file ? (
                                <div className="animate-in fade-in zoom-in-95 duration-200">
                                    <div className="flex items-center gap-3 text-left">
                                        <div className="relative shrink-0">
                                            <div className="flex size-11 items-center justify-center rounded-lg bg-status-green/15 text-status-green">
                                                <SelectedFileIcon className="size-6" />
                                            </div>
                                            <span className="absolute -bottom-1 -right-1 flex size-5 items-center justify-center rounded-full bg-status-green text-white ring-2 ring-success-background">
                                                <Check className="size-3" strokeWidth={3} />
                                            </span>
                                        </div>
                                        <div className="min-w-0 flex-1">
                                            <p className="truncate text-sm font-medium text-foreground">{file.name}</p>
                                            <p className="mt-0.5 flex items-center gap-1.5 text-xs">
                                                <span className="font-medium text-success-foreground">{t('skillManage.uploadDialog.selected')}</span>
                                                <span className="text-muted-foreground">·</span>
                                                <span className="text-muted-foreground">{formatBytes(file.size)}</span>
                                            </p>
                                        </div>
                                        <button
                                            type="button"
                                            onClick={handleRemoveFile}
                                            aria-label={t('skillManage.uploadDialog.removeFile')}
                                            title={t('skillManage.uploadDialog.removeFile')}
                                            className="shrink-0 rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-foreground/5 hover:text-foreground"
                                        >
                                            <X className="size-4" />
                                        </button>
                                    </div>
                                    <p className="mt-3 text-xs text-muted-foreground">{t('skillManage.uploadDialog.reselectHint')}</p>
                                </div>
                            ) : (
                                <>
                                    <FileUp className={`mx-auto size-8 ${isDragActive ? 'text-primary' : 'text-muted-foreground'}`} />
                                    <p className="mt-2 text-sm">{t('skillManage.uploadDialog.dropHint')}</p>
                                    <p className="mt-1 text-xs text-muted-foreground">{t('skillManage.uploadDialog.dropSub')}</p>
                                </>
                            )}
                        </div>
                        <div className="text-xs text-muted-foreground space-y-1">
                            <p className="font-medium text-foreground">{t('skillManage.uploadDialog.requirementsTitle')}</p>
                            <ul className="list-disc pl-4 space-y-0.5">
                                <li>{t('skillManage.uploadDialog.reqMd')}</li>
                                <li>{t('skillManage.uploadDialog.reqZip')}</li>
                                <li>{t('skillManage.uploadDialog.reqSize', { size: limit.max_size_mb, unpacked: limit.max_unpacked_mb })}</li>
                            </ul>
                        </div>
                    </TabsContent>

                    <TabsContent value="github" className="space-y-3">
                        <div className="space-y-2">
                            <Input
                                value={githubUrl}
                                onChange={(e) => setGithubUrl(e.target.value)}
                                onKeyDown={(e) => { if (e.key === 'Enter') handleGithubImport(); }}
                                placeholder={t('skillManage.uploadDialog.githubUrlPlaceholder')}
                            />
                            <p className="text-xs text-muted-foreground">{t('skillManage.uploadDialog.githubHint')}</p>
                        </div>
                        <div className="text-xs text-muted-foreground space-y-1">
                            <p className="font-medium text-foreground">{t('skillManage.uploadDialog.requirementsTitle')}</p>
                            <ul className="list-disc pl-4 space-y-0.5">
                                <li>{t('skillManage.uploadDialog.githubReqHost')}</li>
                                <li>{t('skillManage.uploadDialog.githubReqDir')}</li>
                                <li>{t('skillManage.uploadDialog.reqSize', { size: limit.max_size_mb, unpacked: limit.max_unpacked_mb })}</li>
                            </ul>
                        </div>
                    </TabsContent>
                </Tabs>

                <DialogFooter>
                    <Button variant="outline" onClick={() => onOpenChange(false)}>{t('skillManage.form.cancel')}</Button>
                    {mode === 'file' ? (
                        <Button onClick={handleUpload} disabled={!file || uploading}>
                            {uploading && <Loader2 className="size-4 mr-1.5 animate-spin" />}
                            {t('skillManage.uploadDialog.confirm')}
                        </Button>
                    ) : (
                        <Button onClick={handleGithubImport} disabled={!githubUrlValid || importing}>
                            {importing && <Loader2 className="size-4 mr-1.5 animate-spin" />}
                            {t('skillManage.uploadDialog.confirm')}
                        </Button>
                    )}
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}
