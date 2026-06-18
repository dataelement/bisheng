import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { resolveArtifactUrl } from "~/components/Linsight/Artifacts/artifactUtils";
import { LoadingIcon } from "~/components/ui/icon/Loading";

// The SPA index.html is returned as a fallback when the artifact file does not
// exist (dev server / gateway SPA-fallback). Rendering it inside the iframe
// would nest the whole app shell — including its loading spinner. Detect it so
// we keep our own centered loading state instead.
const isAppShellFallback = (html: string) =>
    html.includes('id="loading-container"') || html.includes('brandEntry.jsx');

export default function WebView() {
    const [searchParams] = useSearchParams();
    const url = searchParams.get('url');
    // Linsight HTML artifacts pass the owning session_version_id so the MinIO
    // object key can be resolved into a presigned share link (the key itself is
    // not directly servable).
    const vid = searchParams.get('vid');

    const [content, setContent] = useState('');
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        const fileUrl = decodeURIComponent(url || '');
        if (!fileUrl) return;

        let cancelled = false;
        const fetchTextFile = async () => {
            setLoading(true);
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
                if (!cancelled) setContent(isAppShellFallback(text) ? '' : text);
            } catch (err) {
                console.error('WebView failed to load html artifact:', err);
                if (!cancelled) setContent('');
            } finally {
                if (!cancelled) setLoading(false);
            }
        };

        fetchTextFile();
        return () => {
            cancelled = true;
        };
    }, [url, vid]);

    return (
        <div className="fixed inset-0">
            {(loading || !content) && (
                <div className="absolute inset-0 flex items-center justify-center bg-background">
                    <LoadingIcon className="size-20 text-primary" />
                </div>
            )}
            {content && (
                <iframe
                    srcDoc={content}
                    sandbox="allow-scripts"
                    className="size-full"
                    style={{ border: "none" }}
                ></iframe>
            )}
        </div>
    );
};
