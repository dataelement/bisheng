import { useEffect, useState } from "react";
import '../../markdown.css';
import Markdown from '../Chat/Messages/Content/Markdown';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../ui";

export default function FilePreview({ files, fileId }) {

    const currentFile = files.find(file => file.file_id === fileId)
    // 获取文件扩展名
    const getFileExtension = (fileName: string): string => {
        const lastDot = fileName.lastIndexOf(".")
        return lastDot !== -1 ? fileName.substring(lastDot + 1) : ""
    }

    const render = () => {
        const { file_url, file_name } = currentFile
        const url = `${location.origin}/bisheng/${file_url}`
        const type = getFileExtension(file_name)

        if (!url) return <div className="flex justify-center items-center h-full text-gray-400">预览失败</div>
        switch (type) {
            case 'doc':
            case 'docx':
            case 'md': return <TxtFileViewer markdown filePath={url} />
            case 'csv': return <TxtFileViewer csv filePath={url} />
            case 'txt': return <TxtFileViewer filePath={url} />
            case 'html': return <TxtFileViewer html filePath={url} />
            case 'png':
            case 'jpg':
            case 'jpeg':
            case 'bmp': return <img
                className="border"
                src={url.replace(/https?:\/\/[^\/]+/, __APP_ENV__.BASE_URL)} alt="" />
            default:
                return <div className="flex justify-center items-center h-full text-gray-400">预览失败</div>
        }
    }


    return <div className="relative h-[calc(100vh-84px)] overflow-y-auto">
        {render()}
    </div>
};


const TxtFileViewer = ({ html = false, markdown = false, csv = false, filePath }) => {
    const [content, setContent] = useState('');
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    useEffect(() => {
        const fetchTextFile = async () => {
            try {
                setLoading(true);
                const response = await fetch(filePath.replace(/https?:\/\/[^\/]+/, __APP_ENV__.BASE_URL));

                if (!response.ok) {
                    throw new Error(`Failed to fetch file: ${response.status} ${response.statusText}`);
                }

                const text = await response.text();
                setContent(text);
                setError(null);
            } catch (err) {
                setError(err.message);
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
                Loading text file...
            </div>
        );
    }

    if (error) {
        return (
            <div className="p-4 text-sm text-red-500">
                Error loading file: {error}
            </div>
        );
    }

    if (html) return <iframe
        className="w-full h-full border"
        srcDoc={content}  // 使用srcdoc直接嵌入HTML内容
        sandbox="allow-scripts"
    />

    if (markdown) return <div className="bs-mkdown p-10">
        <Markdown content={content} isLatestMessage={true} webContent={false} />
    </div>

    if (csv) return <CsvTableViewer csvText={content} />

    return (
        <div className="p-4 text-sm whitespace-pre-wrap bg-gray-50 rounded border border-gray-200 h-full overflow-y-auto">
            {content || <span className="text-gray-400">(Empty file)</span>}
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