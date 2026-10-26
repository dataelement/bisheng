import { Button } from "~/components/ui/Button";
import { useLocalize } from "~/hooks";

/** Temporary customer-side capability probe; remove after validation. */
export function DirectoryDownloadProbeLink() {
    const localize = useLocalize();
    const baseUrl = __APP_ENV__.BASE_URL.replace(/\/$/, "");

    return (
        <div className="shrink-0 px-4">
            <Button asChild variant="link" size="small">
                <a href={`${baseUrl}/static/directory-download-probe/index.html`} target="_self">
                    {localize("com_knowledge.directory_download_probe")}
                </a>
            </Button>
        </div>
    );
}
