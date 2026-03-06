import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
} from "@/components/ui/table"; // 确保已安装 shadcn table
import {
    Download,
    Edit,
    FileImageIcon,
    FileUserIcon,
    FolderIcon,
    ImageIcon,
    MoreVertical,
    RefreshCw,
    SortDescIcon,
    Tag, Trash2
} from "lucide-react";
import {
    Checkbox,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger
} from "~/components";
import { cn } from "~/utils";
import FileIcon from "./FileIcon";
import TagGroup from "./TagGroup";
import { useState } from "react";

// --- 辅助组件：状态标签渲染 ---
const StatusBadge = ({ status }) => {
    const config = {
        SUCCESS: { label: "成功", color: "text-[#00b42a]", bg: "bg-[#e8ffea]", dot: "bg-[#00b42a]" },
        PROCESSING: { label: "处理中", color: "text-[#165dff]", bg: "bg-[#e8f3ff]", dot: "bg-[#165dff]" },
        FAILED: { label: "失败", color: "text-[#f53f3f]", bg: "bg-[#fff2f0]", dot: "bg-[#f53f3f]" },
    };
    const item = config[status] || config.PROCESSING;
    return (
        <div className={cn("inline-flex items-center gap-1.5 px-2 py-0.5 rounded-sm text-xs font-medium", item.bg, item.color)}>
            <span className={cn("size-1.5 rounded-full", item.dot)} />
            {item.label}
        </div>
    );
};

const SortableHeader = ({ children, className, sortKey, currentSort, onSort }) => {
    const isActive = currentSort?.key === sortKey;
    const direction = isActive ? currentSort.direction : "asc";

    return (
        <TableHead
            className={cn(
                "group relative p-0 pr-3 my-2 cursor-pointer select-none",
                "hover:bg-[#f2f3f5] transition-colors",
                className
            )}
            onClick={() => onSort(sortKey)}
        >
            <div className="flex items-center gap-1.5 border-l pl-3">
                <span className={cn("text-sm font-normal", isActive ? "text-[#1d2129]" : "text-[#4e5969]")}>
                    {children}
                </span>
                <SortDescIcon className={`size-4 group-hover:opacity-100 opacity-0 transition-opacity ${isActive ? "opacity-100 text-primary" : ""} ${direction === "asc" ? "rotate-180" : ""}`} />
            </div>
        </TableHead>
    );
};

function FileTableHeader() {
    const [sort, setSort] = useState({ key: "UPDATE_TIME", direction: "asc" });

    const handleSort = (key) => {
        setSort(prev => ({
            key,
            direction: prev.key === key && prev.direction === "asc" ? "desc" : "asc"
        }));
    };

    return (
        <TableHeader className="bg-[#f7f8fa] border-b border-[#e5e6eb]">
            <TableRow className="hover:bg-transparent border-none">
                {/* 复选框列没有分割线 */}
                <TableHead className="w-12 text-center p-0">
                    <Checkbox className="border-gray-400 checked:border-primary" />
                </TableHead>

                {/* 排序属性列 */}
                <SortableHeader
                    sortKey="NAME"
                    currentSort={sort}
                    onSort={handleSort}
                >
                    文件名
                </SortableHeader>

                <SortableHeader
                    sortKey="SIZE"
                    className="w-32"
                    currentSort={sort}
                    onSort={handleSort}
                >
                    文件大小
                </SortableHeader>

                {/* 标签列不需要排序，但需要分割线 */}
                <TableHead className="w-48 text-[#4e5969] font-normal p-0 pr-3">
                    <div className="flex items-center gap-1.5 border-l pl-3">
                        标签
                    </div>
                </TableHead>

                <SortableHeader
                    sortKey="UPDATE_TIME"
                    className="w-48"
                    currentSort={sort}
                    onSort={handleSort}
                >
                    更新时间
                </SortableHeader>

                <SortableHeader
                    sortKey="STATUS"
                    className="w-28"
                    currentSort={sort}
                    onSort={handleSort}
                >
                    状态
                </SortableHeader>

                <TableHead className="w-20 text-[#4e5969] font-normal p-0">
                    <div className="flex items-center gap-1.5 border-l pl-3">
                        操作
                    </div>
                </TableHead>
            </TableRow>
        </TableHeader>
    );
}

// --- 主表格组件 ---
export function FileTable({ files, selectedFiles, handleSelectAll, handleSelectFile, isAdmin, onDownload, onEditTags, onRename, onDelete, onRetry }) {
    return (
        <div className="border-t border-[#e5e6eb] overflow-hidden">
            <Table>
                <FileTableHeader />
                <TableBody>
                    {files.map((file) => (
                        <FileRow
                            key={file.id}
                            file={file}
                            isAdmin={isAdmin}
                            isSelected={selectedFiles.has(file.id)}
                            onSelect={(val) => handleSelectFile(file.id, val)}
                            onDownload={() => onDownload(file.id)}
                            onEditTags={() => onEditTags(file.id)}
                            onRename={() => onRename(file.id)}
                            onDelete={() => onDelete(file.id)}
                            onRetry={() => onRetry?.(file.id)}
                        />
                    ))}
                </TableBody>
            </Table>
        </div>
    );
}

// --- 行组件 ---
function FileRow({ file, isSelected, onSelect, isAdmin, onDownload, onEditTags, onRename, onDelete, onRetry }) {
    const isFolder = file.type === 'FOLDER';

    return (
        <TableRow className={cn(
            "group border-b-[#e5e6eb] transition-colors",
            isSelected ? "bg-primary/10 hover:bg-primary/10" : "hover:bg-[#f7f8fa]"
        )}>
            {/* 复选框 */}
            <TableCell className="text-center py-3 px-0">
                <div className="flex items-center justify-center">
                    <Checkbox
                        checked={isSelected}
                        onCheckedChange={onSelect}
                        className={`size-4 border-gray-400 ${isSelected ? "border-primary" : ""}`}
                    />
                </div>
            </TableCell>

            {/* 文件名 */}
            <TableCell className="py-3">
                <div className="flex items-center gap-2 min-w-0 text-gray-300 ">
                    <div className="bg-white rounded-sm size-5 flex items-center justify-center">
                        {isFolder && <FolderIcon className="size-4" />}
                        {file.thumbnail ? <FileImageIcon className="size-4" /> : <FileUserIcon className="size-4" />}
                    </div>
                    <span className="text-sm text-[#1d2129] truncate cursor-pointer hover:text-[#165dff]">
                        {file.name}
                    </span>
                </div>
            </TableCell>

            {/* 大小 */}
            <TableCell className="text-[#86909c] text-sm py-3">
                {isFolder ? "--" : (file.size ? (file.size / 1024 / 1024).toFixed(2) + "MB" : "0MB")}
            </TableCell>

            {/* 标签 (集成 SmartTag 逻辑) */}
            <TableCell className="py-3">
                <div className="flex items-center gap-1.5 overflow-hidden">
                    <TagGroup tags={file.tags} />
                </div>
            </TableCell>

            {/* 时间 */}
            <TableCell className="text-[#86909c] text-sm whitespace-nowrap py-3">
                {file.updatedAt}
            </TableCell>

            {/* 状态 */}
            <TableCell className="py-3">
                {isFolder ? <span className="text-[#86909c] text-sm">7/11</span> : <StatusBadge status={file.status} />}
            </TableCell>

            {/* 操作 - 使用 CSS group 控制隐显，彻底解决闪退 */}
            <TableCell className="text-right pr-4 py-3">
                <div className="invisible group-hover:visible flex justify-end">
                    <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                            <button className="size-7 flex items-center justify-center hover:bg-[#e5e6eb] rounded-md text-[#4e5969] transition-colors">
                                <MoreVertical className="size-4" />
                            </button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end" className="w-32">
                            <DropdownMenuItem onClick={onDownload}>
                                <Download className="size-4 mr-2" />下载
                            </DropdownMenuItem>
                            {isAdmin && (
                                <>
                                    <DropdownMenuSeparator />
                                    <DropdownMenuItem onClick={onEditTags}>
                                        <Tag className="size-4 mr-2" />编辑标签
                                    </DropdownMenuItem>
                                    <DropdownMenuItem onClick={onRename}>
                                        <Edit className="size-4 mr-2" />重命名
                                    </DropdownMenuItem>
                                    {file.status === 'FAILED' && (
                                        <DropdownMenuItem onClick={onRetry}>
                                            <RefreshCw className="size-4 mr-2" />重试
                                        </DropdownMenuItem>
                                    )}
                                    <DropdownMenuItem onClick={onDelete} className="text-[#f53f3f] focus:text-[#f53f3f] focus:bg-[#fff2f0]">
                                        <Trash2 className="size-4 mr-2" />删除
                                    </DropdownMenuItem>
                                </>
                            )}
                        </DropdownMenuContent>
                    </DropdownMenu>
                </div>
            </TableCell>
        </TableRow>
    );
}