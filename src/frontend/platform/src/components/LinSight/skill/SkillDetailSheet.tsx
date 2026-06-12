// F035: skill detail — bundle file tree on the left, file content on the
// right. SKILL.md gets a Preview/Source toggle; bundle assets are read-only.
import { Badge } from "@/components/bs-ui/badge";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/bs-ui/sheet";
import { toast } from "@/components/bs-ui/toast/use-toast";
import { SkillDetail, skillApi } from "@/controllers/API/linsight";
import { FileText } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { getSkillErrorMessage } from "./skillErrors";

const SKILL_MD = 'SKILL.md';

interface SkillDetailSheetProps {
    detail: SkillDetail | null;
    onOpenChange: (open: boolean) => void;
}

export function SkillDetailSheet({ detail, onOpenChange }: SkillDetailSheetProps) {
    const { t } = useTranslation();
    const [selectedPath, setSelectedPath] = useState(SKILL_MD);
    const [mode, setMode] = useState<'preview' | 'source'>('preview');
    // Lazily-fetched bundle asset contents, keyed by path.
    const [assetCache, setAssetCache] = useState<Record<string, string>>({});

    useEffect(() => {
        setSelectedPath(SKILL_MD);
        setMode('preview');
        setAssetCache({});
    }, [detail?.name]);

    const handleSelectFile = (path: string) => {
        setSelectedPath(path);
        if (path === SKILL_MD || assetCache[path] !== undefined || !detail) return;
        skillApi.getSkillFile(detail.name, path)
            .then(res => setAssetCache(prev => ({ ...prev, [path]: res.content })))
            .catch(err => toast({ variant: 'error', description: getSkillErrorMessage(err, t) }));
    };

    if (!detail) return null;
    const isSkillMd = selectedPath === SKILL_MD;
    const content = isSkillMd
        ? (mode === 'preview' ? detail.preview : detail.source_text)
        : (assetCache[selectedPath] ?? '');

    return (
        <Sheet open={!!detail} onOpenChange={onOpenChange}>
            <SheetContent className="sm:max-w-[860px] w-[90vw] flex flex-col">
                <SheetHeader>
                    <SheetTitle className="flex items-center gap-2 flex-wrap">
                        <span>{detail.display_name}</span>
                        <span className="text-xs font-mono font-normal text-muted-foreground border rounded px-1.5 py-0.5">ID: {detail.name}</span>
                        <Badge variant={detail.enabled ? 'default' : 'secondary'} className="font-normal">
                            {detail.enabled ? t('skillManage.statusEnabled') : t('skillManage.statusDisabled')}
                        </Badge>
                    </SheetTitle>
                </SheetHeader>
                <p className="text-sm text-muted-foreground">{detail.description}</p>
                <div className="flex gap-3 flex-1 min-h-0 mt-2">
                    {/* bundle file tree */}
                    <div className="w-56 shrink-0 border rounded-md overflow-y-auto">
                        <p className="text-xs text-muted-foreground px-3 pt-2 pb-1">{t('skillManage.detailSheet.files')}</p>
                        {detail.files.map(file => (
                            <div
                                key={file.path}
                                onClick={() => handleSelectFile(file.path)}
                                className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-mono cursor-pointer truncate ${selectedPath === file.path ? 'bg-primary/10 text-primary border-l-2 border-primary' : 'hover:bg-muted'}`}
                            >
                                <FileText className="size-3 shrink-0" />
                                <span className="truncate" title={file.path}>{file.path}</span>
                            </div>
                        ))}
                    </div>
                    {/* file content */}
                    <div className="flex-1 min-w-0 flex flex-col">
                        <div className="flex items-center justify-between mb-1.5">
                            <span className="text-xs font-mono text-muted-foreground truncate">{selectedPath}</span>
                            {isSkillMd ? (
                                <div className="flex border rounded-md overflow-hidden text-xs">
                                    {(['preview', 'source'] as const).map(m => (
                                        <button
                                            key={m}
                                            onClick={() => setMode(m)}
                                            className={`px-3 py-1 ${mode === m ? 'bg-primary text-primary-foreground' : 'bg-background hover:bg-muted'}`}
                                        >
                                            {t(`skillManage.detailSheet.${m}`)}
                                        </button>
                                    ))}
                                </div>
                            ) : (
                                <span className="text-xs text-muted-foreground">{t('skillManage.detailSheet.readonlyAsset')}</span>
                            )}
                        </div>
                        <pre className="flex-1 overflow-auto border rounded-md p-3 text-xs whitespace-pre-wrap break-all bg-muted/30 font-mono">
                            {content}
                        </pre>
                    </div>
                </div>
            </SheetContent>
        </Sheet>
    );
}
