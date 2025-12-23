import { useEffect, useMemo, useState } from "react";
import '../../markdown.css';
import Markdown from '../Chat/Messages/Content/Markdown';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../ui";
import { useLocalize } from "~/hooks";
import { Input, Button, Label } from '~/components';
import FileIcon from "../ui/icon/File"
import { getLinsightFileDownloadApi } from "~/data-provider/data-provider/src/data-service";



interface FilePreviewProps {
    // 原有方式：通过 fileId 查找文件
    files?: any[]
    fileId?: string
    // 新增方式：直接传入文件对象
    currentDisplayFile?: any
    vid: string
}

export default function FilePreview({ files, fileId, currentDisplayFile, onDownloadFile, vid }: FilePreviewProps) {
    const localize = useLocalize();
    // 获取当前文件信息
    const currentFile = useMemo(() => {
        if (currentDisplayFile) {
            return currentDisplayFile
        }

        if (files && fileId) {
            const currentFile = files.find(file => file.file_id === fileId)
            return currentFile
        }

        return null
    }, [files, fileId, currentDisplayFile])

    // 获取文件扩展名
    const getFileExtension = (fileName: string): string => {
        const lastDot = fileName.lastIndexOf(".")
        return (lastDot !== -1 ? fileName.substring(lastDot + 1) : "").toLowerCase()
    }

    const render = () => {
        if (!currentFile && !currentFile?.file_url) {
            return <div className="flex justify-center items-center h-full text-gray-400">{localize('com_sop_preview_failed')}</div>
        }

        const { file_url, file_name } = currentFile
        const type = getFileExtension(file_name)

        // 对于直接文件模式，不需要 URL
        const url = `${location.origin}${file_url}`
        const handleClick = (e, url) => {
            e.stopPropagation();
            onDownloadFile({
                file_name: currentFile.file_name,
                file_url: url
            })
        }
        switch (type) {
            case 'xls':
            case 'xlsx':
            case 'doc':
            case 'docx':
                return <div className="flex flex-col items-center justify-center h-full">
                    <FileIcon
                        type={type}
                        className="w-20 h-20"
                    />
                    <div className="text-lg font-bold mt-2">{file_name}</div>
                    <div className="text-sm text-gray-500 m-4">{localize('com_preview_type_unsupported')}</div>
                    <Button variant="outline" onClick={(e) => handleClick(e, file_url)}>{localize('com_ui_download')}</Button>
                </div>
            case 'md':
                return <TxtFileViewer
                    vid={vid}
                    markdown
                    filePath={file_url}
                />
            case 'csv':
                return <TxtFileViewer
                    vid={vid}
                    csv
                    filePath={file_url}
                />
            case 'txt':
                return <TxtFileViewer
                    vid={vid}
                    filePath={file_url}
                />
            case 'html':
                return <TxtFileViewer
                    vid={vid}
                    html
                    filePath={file_url}
                />
            case 'svg':
                return (
                    <SvgViewer
                        fileUrl={file_url}
                        fileName={file_name}
                        onDownload={(url) => handleClick(null, url)}
                    />
                );
            case 'png':
            case 'jpg':
            case 'jpeg':
            case 'bmp':
                return <ImageFileViewer filePath={file_url} vid={vid} fileName={file_name} />
            default:
                return <div className="flex justify-center items-center h-full text-gray-400">{localize('com_sop_preview_failed')}</div>
        }
    }

    return <div className="relative h-[calc(100vh-84px)] overflow-y-auto">{render()}</div>
}

interface TxtFileViewerProps {
    html?: boolean
    markdown?: boolean
    csv?: boolean
    filePath?: string
    directContent?: string // 新增：直接传入的内容
}
const SvgViewer = ({ fileUrl, fileName, onDownload }: SvgViewerProps) => {
    const [svgContent, setSvgContent] = useState('');
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const localize = useLocalize();

    // 构建完整的后端URL
    const fullUrl = `${__APP_ENV__.BASE_URL}${fileUrl}`;

    useEffect(() => {
        // 用于清理请求的AbortController
        const abortController = new AbortController();

        const fetchSvgContent = async () => {
            try {
                setLoading(true);
                setError(null);

                const response = await fetch(fullUrl, {
                    signal: abortController.signal,
                    headers: {
                        'Accept': 'image/svg+xml' // 明确请求SVG类型
                    }
                });

                if (!response.ok) {
                    throw new Error(`HTTP ${response.status} - ${response.statusText}`);
                }

                // 直接获取SVG文本内容
                const content = await response.text();

                setSvgContent(content);
            } catch (err) {
                if (!abortController.signal.aborted) { // 排除手动取消的情况
                    setError(err instanceof Error ? err.message : '加载SVG失败');
                    console.error('SVG加载错误:', err);
                }
            } finally {
                if (!abortController.signal.aborted) {
                    setLoading(false);
                }
            }
        };

        fetchSvgContent();

        // 组件卸载时取消请求
        return () => abortController.abort();
    }, [fullUrl]);

    if (loading) {
        return (
            <div className="flex justify-center items-center h-full">
                <img
                    className="size-8 animate-spin"
                    src={`${__APP_ENV__.BASE_URL}/assets/load.webp`}
                    alt="加载中"
                />
                <span className="ml-2 text-sm text-gray-500">加载SVG文件...</span>
            </div>
        );
    }

    if (error) {
        return (
            <div className="flex flex-col items-center justify-center h-full p-6">
                <FileIcon type="svg" className="w-16 h-16 mb-4 text-gray-400" />
                <div className="text-red-500 text-sm mb-4">
                    {localize('com_sop_file_load_error')}: {error}
                </div>
                <Button
                    variant="outline"
                    onClick={() => onDownload(fullUrl)}
                >
                    {localize('com_ui_download')} {fileName}
                </Button>
            </div>
        );
    }

    return (
        <div className="relative h-full flex justify-center items-center p-4 overflow-hidden">
            {/* 直接渲染SVG内容，绕过标签限制 */}
            <div
                className="max-w-full max-h-[calc(100vh-200px)]"
                dangerouslySetInnerHTML={{ __html: svgContent }}
                onClick={(e) => e.stopPropagation()}
            />
        </div>
    );
};
const TxtFileViewer = ({ html = false, markdown = false, csv = false, filePath, vid }: TxtFileViewerProps) => {
    const [content, setContent] = useState('');
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const localize = useLocalize();

    useEffect(() => {
        if (!filePath) {
            setError('No file path or direct content provided');
            setLoading(false);
            return;
        }

        const fetchTextFile = async () => {
            try {
                setLoading(true);
                const res = await getLinsightFileDownloadApi(filePath, vid)
                const url = __APP_ENV__.BASE_URL + res.data.file_path
                const response = await fetch(url);
                if (!response.ok) {
                    throw new Error(`Failed to fetch file: ${response.status} ${response.statusText}`);
                }
                const text = await response.text();
                setContent(text);
                setError(null);
            } catch (err) {
                setError(err instanceof Error ? err.message : 'Unknown error');
                setContent('');
            } finally {
                setLoading(false);
            }
        };

        fetchTextFile();
    }, [filePath]);

    if (loading) {
        return (
            <div className="p-4 text-sm text-gray-500">
                <img className='size-5' src={__APP_ENV__.BASE_URL + '/assets/load.webp'} alt="" />
            </div>
        );
    }

    if (error) {
        return (
            <div className="p-4 text-sm text-red-500">
                {localize('com_sop_file_load_error')}: {error}
            </div>
        );
    }

    if (html) return <iframe
        className="w-full h-full border"
        srcDoc={content}
        sandbox="allow-scripts"
    />

    if (markdown) return <div className="bs-mkdown p-10">
        <Markdown content={content} isLatestMessage={true} webContent={false} />
    </div>

    if (csv) return <CsvTableViewer csvText={content} />

    return (
        <div className="p-4 text-sm whitespace-pre-wrap bg-gray-50 rounded border border-gray-200 h-full overflow-y-auto">
            {content || <span className="text-gray-400">({localize('com_sop_empty_file')})</span>}
        </div>
    );
};

interface ImageFileViewerProps {
    filePath: string;
    vid?: string | number;
    fileName?: string;
    className?: string;
}

const ImageFileViewer = ({ filePath, vid, fileName = 'image', className = "" }: ImageFileViewerProps) => {
    const [imageUrl, setImageUrl] = useState<string>('');
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const localize = useLocalize(); // 假设你已有这个 hook

    useEffect(() => {
        if (!filePath) {
            setError('No file path provided');
            setLoading(false);
            return;
        }

        const fetchImageSource = async () => {
            try {
                setLoading(true);
                const res = await getLinsightFileDownloadApi(filePath, vid);
                const url = __APP_ENV__.BASE_URL + res.data.file_path;

                setImageUrl(url);
                setError(null);
            } catch (err) {
                setError(err instanceof Error ? err.message : 'Unknown error');
            } finally {
                setLoading(false);
            }
        };

        fetchImageSource();
    }, [filePath, vid]);

    if (loading) {
        return (
            <div className="p-4 text-sm text-gray-500">
                <img className='size-5' src={__APP_ENV__.BASE_URL + '/assets/load.webp'} alt="" />
            </div>
        );
    }

    if (error) {
        return (
            <div className="p-4 text-sm text-red-500">
                {localize('com_sop_file_load_error')}: {error}
            </div>
        );
    }

    return (
        <div className={`flex justify-center items-center overflow-hidden ${className}`}>
            <img
                className="max-w-full h-auto border object-contain"
                src={imageUrl || "/placeholder.svg"}
                alt={fileName}
                onError={(e) => {
                    (e.target as HTMLImageElement).src = "/placeholder.svg";
                }}
            />
        </div>
    );
};

interface CsvTableViewerProps {
    csvText: string;
}

export function CsvTableViewer({ csvText }: CsvTableViewerProps) {
    // 改进的CSV解析：只有逗号后无空格才分割
    const parseCsv = (text: string) => {
        const rows = text.split('\n').filter(row => row.trim() !== '');
        return rows.map(row => {
            // 关键修改：使用负向零宽断言 (?<!\s) 确保逗号前没有空格
            const cells = row.split(/,(?!\s)/);
            return cells.map(cell => cell.trim());
        });
    };

    const parsedData = parseCsv(csvText);
    const headers = parsedData[0] || [];
    const rows = parsedData.slice(1);

    const isUrl = (str: string) => {
        try {
            new URL(str);
            return true;
        } catch {
            return false;
        }
    };

    return (
        <div className="rounded-md border mx-4">
            <Table>
                <TableHeader>
                    <TableRow>
                        {headers.map((header, index) => (
                            <TableHead key={index} className="font-medium">
                                {header}
                            </TableHead>
                        ))}
                    </TableRow>
                </TableHeader>
                <TableBody>
                    {rows.map((row, rowIndex) => (
                        <TableRow key={rowIndex}>
                            {row.map((cell, cellIndex) => (
                                <TableCell key={cellIndex}>
                                    {isUrl(cell) ? (
                                        <a
                                            href={cell}
                                            target="_blank"
                                            rel="noopener noreferrer"
                                            className="text-blue-600 hover:underline break-all"
                                        >
                                            {cell.length > 30 ? `${cell.substring(0, 30)}...` : cell}
                                        </a>
                                    ) : (
                                        cell
                                    )}
                                </TableCell>
                            ))}
                        </TableRow>
                    ))}
                </TableBody>
            </Table>
        </div>
    );
}
