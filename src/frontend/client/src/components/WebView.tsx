import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { resolveArtifactUrl } from "~/components/Linsight/Artifacts/artifactUtils";

export default function WebView() {
    const [searchParams] = useSearchParams();
    const url = searchParams.get('url');
    // Linsight HTML artifacts pass the owning session_version_id so the MinIO
    // object key can be resolved into a presigned share link (the key itself is
    // not directly servable).
    const vid = searchParams.get('vid');

    const [content, setContent] = useState('');

    useEffect(() => {
        const fileUrl = decodeURIComponent(url || '');
        if (!fileUrl) return;

        let cancelled = false;
        const fetchTextFile = async () => {
            try {
                // With a vid, resolve the object key -> presigned link (same path
                // the side preview panel uses). Without it, fall back to a plain
                // BASE_URL join, guarding the leading slash so we never produce
                // `/workspacelinsight/...` (the old missing-slash 404).
                const fetchUrl = vid
                    ? await resolveArtifactUrl(fileUrl, vid)
                    : `${__APP_ENV__.BASE_URL}/${fileUrl.replace(/^\/+/, '')}`;

                const response = await fetch(fetchUrl);
                if (!response.ok) {
                    throw new Error(`Failed to fetch file: ${response.status} ${response.statusText}`);
                }
                const text = await response.text();
                if (!cancelled) setContent(text);
            } catch (err) {
                console.error('WebView failed to load html artifact:', err);
                if (!cancelled) setContent('');
            }
        };

        fetchTextFile();
        return () => {
            cancelled = true;
        };
    }, [url, vid]);

    return <iframe srcDoc={content} sandbox="allow-scripts" width="100%" height="100%" style={{ border: "none" }}></iframe>;
};
