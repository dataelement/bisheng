import { useEffect, useRef, useState } from "react";
import { ChevronRight, File, Folder, Search, X } from "lucide-react";
import { type GlobalSearchFileResult, globalSearchSpaceFilesApi } from "~/api/knowledge";
import s from "./GlobalSearchPanel.module.css";

interface Props {
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

export function GlobalSearchPanel({ onSelectFile }: Props) {
    const [keyword, setKeyword] = useState("");
    const [results, setResults] = useState<GlobalSearchFileResult[]>([]);
    const [total, setTotal] = useState(0);
    const [loading, setLoading] = useState(false);
    const [open, setOpen] = useState(false);
    const [expandedLevels, setExpandedLevels] = useState<Record<string, boolean>>({});
    const [expandedSpaces, setExpandedSpaces] = useState<Record<number, boolean>>({});
    const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
    const inputRef = useRef<HTMLInputElement>(null);

    useEffect(() => {
        if (debounceRef.current) clearTimeout(debounceRef.current);
        const trimmed = keyword.trim();
        if (!trimmed) {
            setResults([]);
            setTotal(0);
            setOpen(false);
            return;
        }
        debounceRef.current = setTimeout(async () => {
            setLoading(true);
            setOpen(true);
            try {
                const res = await globalSearchSpaceFilesApi(trimmed);
                setResults(res.data);
                setTotal(res.total);
                const levels: Record<string, boolean> = {};
                const spaces: Record<number, boolean> = {};
                for (const file of res.data) {
                    levels[file.space_level] = true;
                    spaces[file.space_id] = true;
                }
                setExpandedLevels(levels);
                setExpandedSpaces(spaces);
            } catch {
                setResults([]);
                setTotal(0);
            } finally {
                setLoading(false);
            }
        }, 350);
        return () => {
            if (debounceRef.current) clearTimeout(debounceRef.current);
        };
    }, [keyword]);

    function handleClear() {
        setKeyword("");
        setOpen(false);
        setResults([]);
        inputRef.current?.focus();
    }

    function toggleLevel(levelKey: string) {
        setExpandedLevels((prev) => ({ ...prev, [levelKey]: !prev[levelKey] }));
    }

    function toggleSpace(spaceId: number) {
        setExpandedSpaces((prev) => ({ ...prev, [spaceId]: !prev[spaceId] }));
    }

    const tree = buildTree(results);

    return (
        <div className={s.searchRoot}>
            <div className={s.searchBar}>
                <Search size={13} className={s.searchIcon} />
                <input
                    ref={inputRef}
                    className={s.searchInput}
                    placeholder="搜索所有知识库文件"
                    value={keyword}
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
                    ) : results.length === 0 ? (
                        <div className={s.searchStatus}>未找到匹配文件</div>
                    ) : (
                        <>
                            <div className={s.searchSummary}>共 {total} 个文件</div>
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
                                                <button
                                                    type="button"
                                                    className={s.treeSpace}
                                                    onClick={() => toggleSpace(spaceGroup.spaceId)}
                                                >
                                                    <ChevronRight
                                                        size={11}
                                                        className={`${s.chevron} ${expandedSpaces[spaceGroup.spaceId] ? s.chevronOpen : ""}`}
                                                    />
                                                    <span className={s.treeSpaceName}>{spaceGroup.spaceName}</span>
                                                    <span className={s.treeCount}>({spaceGroup.files.length})</span>
                                                </button>
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
                                                                <span>{file.file_name}</span>
                                                            </span>
                                                        </button>
                                                    ))
                                                ) : null}
                                            </div>
                                        ))
                                    ) : null}
                                </div>
                            ))}
                        </>
                    )}
                </div>
            ) : null}
        </div>
    );
}
