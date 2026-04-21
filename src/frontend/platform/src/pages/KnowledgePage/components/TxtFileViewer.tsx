import { useState, useEffect } from 'react';
import { MarkdownView } from './PreviewParagraph';

declare const __APP_ENV__: any;

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
            <div className="flex h-full min-h-0 items-center justify-center p-4 text-sm text-gray-500">
                Loading text file...
            </div>
        );
    }

    if (error) {
        return (
            <div className="flex h-full min-h-0 items-center justify-center p-4 text-sm text-red-500">
                Error loading file: {error}
            </div>
        );
    }

    if (markdown) return <div className="h-full min-h-0 overflow-y-auto"><MarkdownView noHead data={{ text: content }} /></div>

    if (html) return <iframe
        className="h-full w-full border"
        srcDoc={content}  // 使用srcdoc直接嵌入HTML内容
        sandbox="allow-scripts"
    />

    return (
        <div className="h-full min-h-0 overflow-y-auto p-4 text-sm whitespace-pre-wrap bg-gray-50 rounded border border-gray-200">
            {content || <span className="text-gray-400">(Empty file)</span>}
        </div>
    );
};

export default TxtFileViewer;
