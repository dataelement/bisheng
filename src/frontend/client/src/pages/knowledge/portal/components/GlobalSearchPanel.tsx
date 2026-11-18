import { useEffect, useRef, useState, type ReactNode } from "react";
import { ArrowUpRight, ChevronRight, File, Folder, Search, X } from "lucide-react";
import {
    type GlobalSearchFileResult,
    type GlobalSearchSpaceResult,
    globalSearchSpaceFilesApi,
} from "~/api/knowledge";
import { KnowledgeSpaceIcon } from "./SpaceIcons";
import s from "./GlobalSearchPanel.module.css";

interface Props {
    activeSpaceId?: string;
    onSelectSpace?: (spaceId: number, spaceLevel: string) => void;
    onSelectFile: (spaceId: number, fileId: number, fileName: string) => void;
}

interface SpaceGroup {
    spaceId: number;
    spaceName: string;
    files: GlobalSearchFileResult[];
}

interface LevelGroup {
    levelKey: string;
    levelLabel: string;
    levelOrder: number;
    spaces: SpaceGroup[];
}

const SHORT_LEVEL_LABELS: Record<string, string> = {
    public: "公共",
    department: "部门",
    team: "团队",
    team_ks: "科室",
    personal: "个人",
};

function formatShortLevelLabel(space: GlobalSearchSpaceResult): string {
    return SHORT_LEVEL_LABELS[space.space_level] ?? space.space_level_label.replace(/知识库$/, "");
}

function renderHighlightedText(text: string, rawKeyword: string): ReactNode {
    const trimmed = rawKeyword.trim();
    if (!trimmed) return text;
    const lowerText = text.toLowerCase();
    const lowerKeyword = trimmed.toLowerCase();
    const nodes: ReactNode[] = [];
    let cursor = 0;
    let matchIndex = lowerText.indexOf(lowerKeyword, cursor);

    while (matchIndex !== -1) {
        if (matchIndex > cursor) {
            nodes.push(text.slice(cursor, matchIndex));
        }
        const matchEnd = matchIndex + trimmed.length;
        nodes.push(
            <mark key={`${matchIndex}-${matchEnd}`} className={s.highlight}>
                {text.slice(matchIndex, matchEnd)}
            </mark>,
        );
        cursor = matchEnd;
        matchIndex = lowerText.indexOf(lowerKeyword, cursor);
    }

    if (cursor === 0) return text;
    if (cursor < text.length) {
        nodes.push(text.slice(cursor));
    }
    return nodes;
}

function buildTree(files: GlobalSearchFileResult[]): LevelGroup[] {
    const levelMap = new Map<string, LevelGroup>();
    for (const file of files) {
        let levelGroup = levelMap.get(file.space_level);
        if (!levelGroup) {
            levelGroup = {
                levelKey: file.space_level,
                levelLabel: file.space_level_label,
                levelOrder: file.space_level_order,
                spaces: [],
            };
            levelMap.set(file.space_level, levelGroup);
        }
        let spaceGroup = levelGroup.spaces.find((sg) => sg.spaceId === file.space_id);
        if (!spaceGroup) {
            spaceGroup = { spaceId: file.space_id, spaceName: file.space_name, files: [] };
            levelGroup.spaces.push(spaceGroup);
        }
        spaceGroup.files.push(file);
    }
    return Array.from(levelMap.values()).sort((a, b) => a.levelOrder - b.levelOrder);
}

export function GlobalSearchPanel({ activeSpaceId, onSelectSpace, onSelectFile }: Props) {
    const [keyword, setKeyword] = useState("");
    const [matchedSpaces, setMatchedSpaces] = useState<GlobalSearchSpaceResult[]>([]);
    const [spaceTotal, setSpaceTotal] = useState(0);
    const [results, setResults] = useState<GlobalSearchFileResult[]>([]);
    const [total, setTotal] = useState(0);
    const [loading, setLoading] = useState(false);
    const [open, setOpen] = useState(false);
    const [expandedLevels, setExpandedLevels] = useState<Record<string, boolean>>({});
    const [expandedSpaces, setExpandedSpaces] = useState<Record<number, boolean>>({});
    const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
    const requestSeqRef = useRef(0);
    const searchedKeywordRef = useRef("");
    const rootRef = useRef<HTMLDivElement>(null);
    const inputRef = useRef<HTMLInputElement>(null);

    useEffect(() => {
        if (debounceRef.current) clearTimeout(debounceRef.current);
        const trimmed = keyword.trim();
        if (!trimmed) {
            requestSeqRef.current += 1;
            searchedKeywordRef.current = "";
            setMatchedSpaces([]);
            setSpaceTotal(0);
            setResults([]);
            setTotal(0);
            setLoading(false);
            setOpen(false);
            return;
        }
        debounceRef.current = setTimeout(async () => {
            const reqSeq = ++requestSeqRef.current;
            setLoading(true);
            setOpen(true);
            try {
                const res = await globalSearchSpaceFilesApi(trimmed);
                if (reqSeq !== requestSeqRef.current) return;
                const nextSpaces = Array.isArray(res.spaces) ? res.spaces : [];
                const nextFiles = Array.isArray(res.data) ? res.data : [];
                searchedKeywordRef.current = trimmed;
                setMatchedSpaces(nextSpaces);
                setSpaceTotal(res.space_total ?? nextSpaces.length);
                setResults(nextFiles);
                setTotal(res.total ?? nextFiles.length);
                const levels: Record<string, boolean> = {};
                const spaces: Record<number, boolean> = {};
                for (const file of nextFiles) {
                    levels[file.space_level] = true;
                    spaces[file.space_id] = true;
                }
                setExpandedLevels(levels);
                setExpandedSpaces(spaces);
            } catch {
                if (reqSeq !== requestSeqRef.current) return;
                searchedKeywordRef.current = trimmed;
                setMatchedSpaces([]);
                setSpaceTotal(0);
                setResults([]);
                setTotal(0);
            } finally {
                if (reqSeq === requestSeqRef.current) {
                    setLoading(false);
                }
            }
        }, 350);
        return () => {
            if (debounceRef.current) clearTimeout(debounceRef.current);
        };
    }, [keyword]);

    useEffect(() => {
        if (!open) return;
        const handlePointerDown = (event: MouseEvent) => {
            if (rootRef.current && !rootRef.current.contains(event.target as Node)) {
                setOpen(false);
            }
        };
        const handleKeyDown = (event: KeyboardEvent) => {
            if (event.key === "Escape") {
                setOpen(false);
            }
        };
        document.addEventListener("mousedown", handlePointerDown);
        document.addEventListener("keydown", handleKeyDown);
        return () => {
            document.removeEventListener("mousedown", handlePointerDown);
            document.removeEventListener("keydown", handleKeyDown);
        };
    }, [open]);

    function handleClear() {
        requestSeqRef.current += 1;
        searchedKeywordRef.current = "";
        setKeyword("");
        setOpen(false);
        setMatchedSpaces([]);
        setSpaceTotal(0);
        setResults([]);
        setTotal(0);
        setLoading(false);
        inputRef.current?.focus();
    }

    function handleInputFocus() {
        const trimmed = keyword.trim();
        if (!trimmed) return;
        if (loading || searchedKeywordRef.current === trimmed) {
            setOpen(true);
        }
    }

    function handleSpaceClick(spaceId: number, spaceLevel: string) {
        onSelectSpace?.(spaceId, spaceLevel);
        setOpen(false);
    }

    function toggleLevel(levelKey: string) {
        setExpandedLevels((prev) => ({ ...prev, [levelKey]: !prev[levelKey] }));
    }

    function toggleSpace(spaceId: number) {
        setExpandedSpaces((prev) => ({ ...prev, [spaceId]: !prev[spaceId] }));
    }

    const tree = buildTree(results);
    const hasSpaces = matchedSpaces.length > 0;
    const hasFiles = results.length > 0;

    return (
        <div ref={rootRef} className={s.searchRoot}>
            <div className={s.searchBar}>
                <Search size={13} className={s.searchIcon} />
                <input
                    ref={inputRef}
                    className={s.searchInput}
                    placeholder="搜索知识库或文件"
                    value={keyword}
                    onFocus={handleInputFocus}
                    onChange={(e) => setKeyword(e.target.value)}
                />
                {keyword ? (
                    <button
                        type="button"
                        className={s.searchClear}
                        aria-label="清除搜索"
                        onClick={handleClear}
                    >
                        <X size={12} />
                    </button>
                ) : null}
            </div>

            {open ? (
                <div className={s.searchResults}>
                    {loading ? (
                        <div className={s.searchStatus}>搜索中...</div>
                    ) : !hasSpaces && !hasFiles ? (
                        <div className={s.searchStatus}>未找到匹配的知识库或文件</div>
                    ) : (
                        <>
                            {hasSpaces ? (
                                <div className={s.spaceSection}>
                                    <div className={s.searchSummary}>知识库 ({spaceTotal})</div>
                                    {matchedSpaces.map((space) => {
                                        const isCurrent = activeSpaceId !== undefined && String(space.space_id) === String(activeSpaceId);
                                        return (
                                            <button
                                                key={space.space_id}
                                                type="button"
                                                className={`${s.matchedSpaceRow} ${isCurrent ? s.matchedSpaceRowActive : ""}`}
                                                title={space.space_name}
                                                onClick={() => handleSpaceClick(space.space_id, space.space_level)}
                                            >
                                                <KnowledgeSpaceIcon className={s.matchedSpaceIcon} aria-hidden="true" />
                                                <span className={s.matchedSpaceName}>
                                                    {renderHighlightedText(space.space_name, keyword)}
                                                </span>
                                                <span className={s.matchedSpaceBadge}>
                                                    {formatShortLevelLabel(space)}
                                                </span>
                                            </button>
                                        );
                                    })}
                                </div>
                            ) : null}

                            {hasFiles ? (
                                <div className={hasSpaces ? s.fileSectionWithDivider : undefined}>
                                    <div className={s.searchSummary}>文件 ({total})</div>
                                    {tree.map((levelGroup) => (
                                        <div key={levelGroup.levelKey}>
                                            <button
                                                type="button"
                                                className={s.treeLevel}
                                                onClick={() => toggleLevel(levelGroup.levelKey)}
                                            >
                                                <ChevronRight
                                                    size={12}
                                                    className={`${s.chevron} ${expandedLevels[levelGroup.levelKey] ? s.chevronOpen : ""}`}
                                                />
                                                <span>{levelGroup.levelLabel}</span>
                                                <span className={s.treeCount}>
                                                    ({levelGroup.spaces.reduce((n, sg) => n + sg.files.length, 0)})
                                                </span>
                                            </button>
                                            {expandedLevels[levelGroup.levelKey] ? (
                                                levelGroup.spaces.map((spaceGroup) => (
                                                    <div key={spaceGroup.spaceId} className={s.treeSpaceBlock}>
                                                        <div className={s.treeSpaceRow}>
                                                            <button
                                                                type="button"
                                                                className={s.treeSpace}
                                                                onClick={() => toggleSpace(spaceGroup.spaceId)}
                                                            >
                                                                <ChevronRight
                                                                    size={11}
                                                                    className={`${s.chevron} ${expandedSpaces[spaceGroup.spaceId] ? s.chevronOpen : ""}`}
                                                                />
                                                                <span className={s.treeSpaceName}>
                                                                    {renderHighlightedText(spaceGroup.spaceName, keyword)}
                                                                </span>
                                                                <span className={s.treeCount}>({spaceGroup.files.length})</span>
                                                            </button>
                                                            {onSelectSpace ? (
                                                                <button
                                                                    type="button"
                                                                    className={s.treeSpaceEnter}
                                                                    title={`进入${spaceGroup.spaceName}`}
                                                                    aria-label={`进入${spaceGroup.spaceName}`}
                                                                    onClick={() => handleSpaceClick(spaceGroup.spaceId, levelGroup.levelKey)}
                                                                >
                                                                    <ArrowUpRight size={11} />
                                                                </button>
                                                            ) : null}
                                                        </div>
                                                        {expandedSpaces[spaceGroup.spaceId] ? (
                                                            spaceGroup.files.map((file) => (
                                                                <button
                                                                    key={file.file_id}
                                                                    type="button"
                                                                    className={s.treeFile}
                                                                    title={file.file_name}
                                                                    onClick={() =>
                                                                        onSelectFile(file.space_id, file.file_id, file.file_name)
                                                                    }
                                                                >
                                                                    {file.folder_path.length > 0 ? (
                                                                        <span className={s.treeFolderPath}>
                                                                            <Folder size={10} />
                                                                            {file.folder_path.join(" / ")}
                                                                        </span>
                                                                    ) : null}
                                                                    <span className={s.treeFileName}>
                                                                        <File size={11} />
                                                                        <span>{renderHighlightedText(file.file_name, keyword)}</span>
                                                                    </span>
                                                                </button>
                                                            ))
                                                        ) : null}
                                                    </div>
                                                ))
                                            ) : null}
                                        </div>
                                    ))}
                                </div>
                            ) : null}
                        </>
                    )}
                </div>
            ) : null}
        </div>
    );
}
