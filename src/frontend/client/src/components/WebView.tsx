import { useEffect, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";

export default function WebView() {
    const [searchParams] = useSearchParams();
    const url = searchParams.get('url');

    const [content, setContent] = useState('');

    useEffect(() => {
        const baseUrl = `${__APP_ENV__.BASE_URL}${decodeURIComponent(url || '')}`
        const fetchTextFile = async () => {
            try {
                const response = await fetch(baseUrl);

                if (!response.ok) {
                    throw new Error(`Failed to fetch file: ${response.status} ${response.statusText}`);
                }

                const text = await response.text();
                setContent(text);
            } catch (err) {
                setContent('');
            }
        };

        fetchTextFile();
    }, [url]);

    return <iframe srcDoc={content} sandbox="allow-scripts" width="100%" height="100%" style={{ border: "none" }}></iframe>;
};
