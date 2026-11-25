// @ts-strict-ignore
import { notification } from '@bisheng/ui';

import { getOfficeTokenApi } from "@/controllers/API/flow";
import { showApiError } from "@/controllers/request";
import { getOfficeReachableUrl } from "@/utils/officeUrl";
import i18next from "i18next";
import { useContext, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { locationContext } from "../../../contexts/locationContext";

interface WordProps {
    data: { key: string; path: string; source_kind?: 'empty'; preview_upload_ref?: string };
    workflow?: boolean;
}

export default function Word({ data, workflow = false }: WordProps) {
    const { appConfig } = useContext(locationContext);
    const { t } = useTranslation("flow");

    const wordUrl = appConfig.officeUrl;
    // The document server POSTs this callback itself — in local dev override the
    // origin via VITE_OFFICE_PUBLIC_ORIGIN (see utils/officeUrl).
    const backUrl = getOfficeReachableUrl(workflow ? "/api/v1/workflow/report/callback" : "/api/v1/report/callback");

    const editorConfig = {
        ...(data.source_kind === "empty" ? { source_kind: "empty" as const } : {}),
        ...(data.preview_upload_ref ? { preview_upload_ref: data.preview_upload_ref } : {}),
        // Editor width
        width: "100%",
        // Editor height
        height: "100%",
        // Editor type: word (document), cell (spreadsheet), slide (PPT)
        documentType: "word",
        // Document config
        document: {
            // File type
            fileType: "docx",
            // Document identifier
            key: data.key,
            // Document URL, absolute path
            url: data.path,
            // Document title
            title: "bisheng.docx",
            permissions: {
                changeHistory: true,
                comment: true,
                copy: true,
                download: true,
                edit: true,
                print: true,
                reader: true,
                rename: false,
                review: true,
            },
        },
        editorConfig: {
            callbackUrl: backUrl,
            lang: i18next.language === "zh-Hans" ? "zh-CN" : "en",
            mode: "edit",
            customization: {
                anonymous: { request: false, label: "" },
                comments: false,
                customer: false,
                help: false,
                chat: false,
                about: false,
                features: { spellcheck: false },
                forcesave: true,
                hideRightMenu: true,
                rightMenu: true,
                unit: "cm",
                uiTheme: "theme-dark",
                logo: {
                    image: location.origin + __APP_ENV__.BASE_URL + "/assets/bisheng/logo.jpeg",
                    imageDark: location.origin + __APP_ENV__.BASE_URL + "/assets/bisheng/logo.jpeg",
                    url: "https://example.com",
                },
            },
            plugins: {
                autostart: ["asc.{D2A0F3BE-CC8D-4956-BCD9-6CBEA6E8960E}"],
                // pluginsData: ['ommon-plugins/config.json']
            },
            user: {
                group: "Group1",
                id: "001",
                name: "",
            },
        },
    };

    useEffect(() => {
        let disposed = false;
        let editor: { destroyEditor: () => void } | undefined;
        let script: HTMLScriptElement | undefined;
        let sdkLoaded = false;
        const initEditor = async () => {
            try {
                const res = await getOfficeTokenApi(editorConfig);
                if (disposed) return;
                if (typeof res?.token !== "string" || !res.token.trim()
                    || !res.config || typeof res.config !== "object"
                    || res.config.documentType !== "word"
                    || !res.config.document || typeof res.config.document !== "object"
                    || !res.config.editorConfig || typeof res.config.editorConfig !== "object") {
                    throw new Error(String(t("wordEditorLoadFailed")));
                }
                editor = new window.DocsAPI.DocEditor("bsoffice", { ...res.config, token: res.token });
                window.editor = editor;
            } catch (error) {
                if (!disposed) showApiError(error);
            }
        };
        if (window.DocsAPI) {
            void initEditor();
        } else {
            if (!wordUrl) {
                notification.open({ type: "error", title: String(t("wordEditorLoadFailed") ?? ''), description: String(t("checkOfficeServiceConfig") ?? '') });
                return;
            }
            script = document.createElement("script");
            script.src = wordUrl + "/web-apps/apps/api/documents/api.js";
            script.onload = () => {
                sdkLoaded = true;
                void initEditor();
            };
            document.head.appendChild(script);
            script.onerror = () => {
                if (!disposed) notification.open({ type: "error", title: String(t("wordEditorLoadFailed") ?? ''), description: String(t("checkOfficeServiceConfig") ?? '') });
            };
        }
        return () => {
            disposed = true;
            if (script) {
                script.onload = null;
                script.onerror = null;
                // Even after loading, the SDK reads this tag to locate each new editor iframe.
                if (!sdkLoaded) script.remove();
            }
            editor?.destroyEditor();
            if (window.editor === editor) window.editor = undefined;
        };
    }, [data.key, data.path, data.source_kind, data.preview_upload_ref, workflow]);

    return (
        <div className="relative w-full h-full">
            <div className="absolute bg-[#252525] left-0 top-0 h-[26px] leading-[26px] w-full text-gray-400 text-center text-xs">
                ctrl+s to save
            </div>
            <div id="bsoffice"></div>
        </div>
    );
}
