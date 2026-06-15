// F035: skill detail — bundle file tree on the left, file content on the
// right. SKILL.md gets a Preview/Source toggle; bundle assets are read-only.
// Visual tokens mirror the Claude Design `renderSkillDetail` spec: a clean
// white drawer, a pale-blue status pill, soft #ECEEF2 panes, and restrained
// Markdown typography (20px h1, 14px/1.7 body) rather than oversized prose.
import { Button } from "@/components/bs-ui/button";
import { Sheet, SheetContent, SheetTitle } from "@/components/bs-ui/sheet";
import { toast } from "@/components/bs-ui/toast/use-toast";
import { SkillDetail, skillApi } from "@/controllers/API/linsight";
import { FileText, Info, Pencil, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import { getSkillErrorMessage } from "./skillErrors";

const SKILL_MD = 'SKILL.md';

// Restrained Markdown typography matching the design's renderMarkdown() — small,
// quiet headings and 14px/1.7 body, not the oversized default `prose` scale.
const MD_COMPONENTS: Components = {
    h1: ({ children }) => <h1 className="text-[20px] leading-[1.35] font-bold tracking-tight text-[#161B26] dark:text-gray-100 mt-0 mb-3">{children}</h1>,
    h2: ({ children }) => <h2 className="text-[15.5px] leading-snug font-semibold text-[#1F2430] dark:text-gray-100 mt-[18px] mb-2">{children}</h2>,
    h3: ({ children }) => <h3 className="text-[14px] leading-snug font-semibold text-[#1F2430] dark:text-gray-100 mt-3.5 mb-1.5">{children}</h3>,
    p: ({ children }) => <p className="text-[14px] leading-[1.7] text-[#3F4654] dark:text-gray-300 my-0 mb-3">{children}</p>,
    ul: ({ children }) => <ul className="list-disc pl-5 my-2.5 space-y-1.5 text-[14px] leading-[1.7] text-[#3F4654] dark:text-gray-300">{children}</ul>,
    ol: ({ children }) => <ol className="list-decimal pl-5 my-2.5 space-y-1.5 text-[14px] leading-[1.7] text-[#3F4654] dark:text-gray-300">{children}</ol>,
    li: ({ children }) => <li className="leading-[1.7] pl-1">{children}</li>,
    a: ({ children, href }) => <a href={href} target="_blank" rel="noreferrer" className="text-primary underline underline-offset-2">{children}</a>,
    strong: ({ children }) => <strong className="font-semibold text-[#1F2430] dark:text-gray-100">{children}</strong>,
    em: ({ children }) => <em className="italic">{children}</em>,
    code: ({ children }) => <code className="px-1.5 py-0.5 rounded bg-muted text-[13px] font-mono text-[#1F2430] dark:text-gray-200">{children}</code>,
    pre: ({ children }) => <pre className="bg-[#1F2430] text-[#E6EAF2] rounded-[10px] p-3.5 overflow-x-auto text-[12.5px] leading-relaxed my-3 [&_code]:bg-transparent [&_code]:p-0 [&_code]:text-inherit">{children}</pre>,
    blockquote: ({ children }) => <blockquote className="border-l-2 border-border pl-3 text-muted-foreground my-3">{children}</blockquote>,
    hr: () => <hr className="my-4 border-border" />,
    table: ({ children }) => <table className="border-collapse my-3 text-[13px]">{children}</table>,
    th: ({ children }) => <th className="border border-border px-2.5 py-1.5 bg-muted text-left font-medium">{children}</th>,
    td: ({ children }) => <td className="border border-border px-2.5 py-1.5">{children}</td>,
};

interface SkillDetailSheetProps {
    detail: SkillDetail | null;
    onOpenChange: (open: boolean) => void;
    // Edit/delete are the detail view's only action hub — the list row has no
    // per-row actions, so these route back to the parent for orchestration.
    onEdit: (detail: SkillDetail) => void;
    onDelete: (detail: SkillDetail) => void;
}

export function SkillDetailSheet({ detail, onOpenChange, onEdit, onDelete }: SkillDetailSheetProps) {
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
    // Preview = rendered Markdown of the body; Source = raw SKILL.md (with frontmatter).
    const isRenderedPreview = isSkillMd && mode === 'preview';
    const rawContent = isSkillMd
        ? (mode === 'preview' ? detail.preview : detail.source_text)
        : (assetCache[selectedPath] ?? '');

    return (
        <Sheet open={!!detail} onOpenChange={onOpenChange}>
            <SheetContent className="sm:max-w-[860px] w-[92vw] p-0 gap-0 flex flex-col bg-background">
                <div className="flex flex-col flex-1 min-h-0 px-7 pt-6 pb-6">
                    {/* header — title + ID chip + status pill, edit/delete pushed to the right */}
                    <div className="flex items-center gap-2.5 flex-wrap pr-10">
                        <SheetTitle className="text-[19px] leading-tight font-semibold text-[#161B26] dark:text-gray-100 mb-0">
                            {detail.display_name}
                        </SheetTitle>
                        <span className="text-xs font-mono font-medium text-[#7A8194] dark:text-gray-400 border border-[#E5E6EB] dark:border-gray-700 rounded-md px-[7px] py-[3px] whitespace-nowrap">
                            ID: {detail.name}
                        </span>
                        <span className={`text-xs font-medium rounded-full px-[11px] py-1 whitespace-nowrap ${detail.enabled ? 'bg-[#E6EDFC] text-[#024DE3] dark:bg-primary/20 dark:text-primary' : 'bg-[#EEF0F3] text-[#6B7280] dark:bg-gray-800 dark:text-gray-400'}`}>
                            {detail.enabled ? t('skillManage.statusEnabled') : t('skillManage.statusDisabled')}
                        </span>
                        {/* calm ghost pair — same neutral weight as the file tree; delete reddens on hover only */}
                        <div className="ml-auto flex gap-1">
                            <Button variant="ghost" size="sm" className="h-8 text-[#5A6172] dark:text-gray-300 hover:text-[#1F2430] dark:hover:text-gray-100 hover:bg-[#F2F4F8] dark:hover:bg-gray-800" onClick={() => onEdit(detail)}>
                                <Pencil className="size-3.5 mr-1" />{t('skillManage.editAction')}
                            </Button>
                            <Button variant="ghost" size="sm" className="h-8 text-[#5A6172] dark:text-gray-300 hover:text-[#F5483B] hover:bg-[#FFF0EF] dark:hover:text-[#FF6B5E] dark:hover:bg-red-950/40" onClick={() => onDelete(detail)}>
                                <Trash2 className="size-3.5 mr-1" />{t('skillManage.deleteAction')}
                            </Button>
                        </div>
                    </div>
                    <p className="text-[13.5px] leading-relaxed text-[#6B7280] dark:text-gray-400 mt-2.5">{detail.description}</p>

                    <div className="flex gap-4 flex-1 min-h-0 mt-[18px]">
                        {/* bundle file tree */}
                        <div className="w-[220px] shrink-0 border border-[#ECEEF2] dark:border-gray-800 rounded-[11px] overflow-y-auto bg-[#FBFCFD] dark:bg-gray-900/40">
                            <p className="text-[11.5px] tracking-wider text-[#A6ACB8] px-3.5 pt-3 pb-2">{t('skillManage.detailSheet.files')}</p>
                            {detail.files.map(file => {
                                const on = selectedPath === file.path;
                                return (
                                    <div
                                        key={file.path}
                                        onClick={() => handleSelectFile(file.path)}
                                        className={`flex items-center gap-2 px-3.5 py-2 text-[12.5px] font-mono cursor-pointer border-l-2 transition-colors ${on ? 'border-primary bg-[#EEF2FF] dark:bg-primary/10 text-[#024DE3] dark:text-primary' : 'border-transparent text-[#5A6172] dark:text-gray-400 hover:bg-[#F2F4F8] dark:hover:bg-gray-800'}`}
                                    >
                                        <FileText className={`size-3.5 shrink-0 ${on ? 'text-primary' : 'text-[#9AA0AC]'}`} />
                                        <span className="truncate min-w-0" title={file.path}>{file.path}</span>
                                    </div>
                                );
                            })}
                        </div>

                        {/* file content */}
                        <div className="flex-1 min-w-0 flex flex-col">
                            <div className="flex items-center justify-between gap-3 mb-2.5">
                                <span className="text-[12.5px] font-mono text-[#9AA0AC] truncate">{selectedPath}</span>
                                {isSkillMd ? (
                                    <div className="inline-flex border border-[#E3E6EC] dark:border-gray-700 rounded-lg overflow-hidden shrink-0">
                                        {(['preview', 'source'] as const).map(m => (
                                            <button
                                                key={m}
                                                onClick={() => setMode(m)}
                                                className={`px-3.5 py-1.5 text-xs font-medium transition-colors ${mode === m ? 'bg-primary text-white' : 'bg-background text-[#6B7280] dark:text-gray-400 hover:bg-muted'}`}
                                            >
                                                {t(`skillManage.detailSheet.${m}`)}
                                            </button>
                                        ))}
                                    </div>
                                ) : (
                                    <span className="inline-flex items-center gap-1.5 text-xs text-[#A6ACB8] shrink-0">
                                        <Info className="size-3.5" />{t('skillManage.detailSheet.readonlyAsset')}
                                    </span>
                                )}
                            </div>
                            {isRenderedPreview ? (
                                <div className="flex-1 min-h-0 overflow-auto border border-[#ECEEF2] dark:border-gray-800 rounded-[11px] bg-background px-6 py-5">
                                    <ReactMarkdown remarkPlugins={[remarkGfm]} components={MD_COMPONENTS}>{detail.preview}</ReactMarkdown>
                                </div>
                            ) : (
                                <pre className="flex-1 min-h-0 overflow-auto border border-[#ECEEF2] dark:border-gray-800 rounded-[11px] bg-[#FBFCFD] dark:bg-gray-900/40 px-6 py-5 text-[12.5px] leading-[1.7] font-mono text-[#3A4358] dark:text-gray-300 whitespace-pre-wrap break-words">
                                    {rawContent}
                                </pre>
                            )}
                        </div>
                    </div>
                </div>
            </SheetContent>
        </Sheet>
    );
}
