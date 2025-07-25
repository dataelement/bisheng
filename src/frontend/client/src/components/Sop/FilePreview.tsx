import { useState, useEffect } from "react"

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
            case 'md':
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


const TxtFileViewer = ({ html = false, markdown = false, filePath }) => {
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

    return (
        <div className="p-4 text-sm whitespace-pre-wrap bg-gray-50 rounded border border-gray-200 h-full overflow-y-auto">
            {content || <span className="text-gray-400">(Empty file)</span>}
        </div>
    );
};