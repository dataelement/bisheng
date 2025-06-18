import { useState, useEffect } from 'react';
import { MarkdownView } from './PreviewParagraph';

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

    if (markdown) return <MarkdownView noHead data={{ text: content }} />

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

export default TxtFileViewer;