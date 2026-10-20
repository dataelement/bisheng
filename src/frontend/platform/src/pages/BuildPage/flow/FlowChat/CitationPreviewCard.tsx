import { CitationSourceIcon } from "@/components/bs-comp/chatComponent/CitationSourceIcon";
import {
type CitationPreview
} from "@/components/bs-comp/chatComponent/citationUtils";
import { type ChatCitation } from "@/controllers/API";
import { Outlined } from "bisheng-icons";

import i18next from "i18next";

export function CitationPreviewCard({
    preview,
    detail,
    isLoading,
    error,
    notPermitted,
    expired,
    onCardClick,
    onOpenDocumentPreview,
}: {
    preview: CitationPreview | null;
    detail?: ChatCitation | null;
    isLoading: boolean;
    error: boolean;
    notPermitted?: boolean;
    expired?: boolean;
    onCardClick?: () => void;
    onOpenDocumentPreview?: () => void;
}) {
    if (isLoading) {
        return (
            <div className="flex min-h-[120px] w-[320px] max-w-[calc(100vw-32px)] items-center justify-center rounded-lg border border-[#ECECEC] bg-white text-sm text-[#86909C] shadow-[0_4px_19px_rgba(34,34,34,0.07)]">
                <Outlined.Loading className="animate-spin mr-2 size-4" />
                {i18next.t("citation.loadingDetail")}
            </div>
        );
    }

    if (notPermitted) {
        return (
            <div className="w-[320px] max-w-[calc(100vw-32px)] rounded-lg border border-[#ECECEC] bg-white p-4 text-sm text-[#86909C] shadow-[0_4px_19px_rgba(34,34,34,0.07)]">
                {i18next.t("citation.noPermission")}
            </div>
        );
    }

    if (expired) {
        return (
            <div className="w-[320px] max-w-[calc(100vw-32px)] rounded-lg border border-[#ECECEC] bg-white p-4 text-sm text-[#86909C] shadow-[0_4px_19px_rgba(34,34,34,0.07)]">
                {i18next.t("citation.sourceExpired")}
            </div>
        );
    }

    if (error || !preview) {
        return (
            <div className="w-[320px] max-w-[calc(100vw-32px)] rounded-lg border border-[#ECECEC] bg-white p-4 text-sm text-[#86909C] shadow-[0_4px_19px_rgba(34,34,34,0.07)]">
                {i18next.t("citation.loadDetailFailed")}
            </div>
        );
    }

    const isWeb = preview.type === "web";
    const cardClassName = "group relative cursor-pointer w-[320px] max-w-[calc(100vw-32px)] overflow-hidden rounded-lg border border-[#ECECEC] bg-white text-[#1D2129] shadow-[0_4px_19px_rgba(34,34,34,0.07)]";
    const titleClassName = "min-w-0 flex-1 truncate text-[14px] font-medium leading-5 text-[#1D2129]";
    const titleContainerClassName = "border-b border-[#F2F3F5] bg-[#F7F7F7] px-4 py-3";
    const interactiveTitleClassName = `${titleClassName} transition-colors duration-200 group-hover:text-[#024DE3]`;
    const ragTitleClassName = "min-w-0 truncate text-[14px] font-medium leading-[22px] text-[#1D2129]";
    const formatSourceMeta = (value?: string) => {
        if (!value) {
            return "";
        }

        const normalizedValue = value.trim();
        const matched = normalizedValue.match(/^(\d{4}-\d{2}-\d{2})[T\s](\d{2}:\d{2})/);
        if (matched) {
            return `${matched[1]} ${matched[2]}`;
        }

        return normalizedValue;
    };
    const splitRagTitle = (value?: string) => {
        const normalizedValue = String(value || "").trim();
        const matched = normalizedValue.match(/^(.*?)(\.[a-zA-Z0-9]+)$/);

        if (!matched) {
            return {
                name: normalizedValue,
                extension: "",
            };
        }

        return {
            name: matched[1],
            extension: matched[2],
        };
    };
    const renderWebHoverIcon = () => (
        <svg
            width="16"
            height="16"
            viewBox="0 0 16 16"
            fill="none"
            xmlns="http://www.w3.org/2000/svg"
            className="hidden shrink-0 group-hover:block"
            aria-hidden="true"
        >
            <g clipPath="url(#citation-web-hover-icon-clip)">
                <path d="M16 0H0V16H16V0Z" fill="white" fillOpacity="0.01" />
                <path d="M5.33398 10.6667L11.0007 5" stroke="#1B61E6" strokeWidth="1.33333" strokeLinecap="round" strokeLinejoin="round" />
                <path d="M5 5H11V11" stroke="#1B61E6" strokeWidth="1.33333" strokeLinecap="round" strokeLinejoin="round" />
            </g>
            <defs>
                <clipPath id="citation-web-hover-icon-clip">
                    <rect width="16" height="16" fill="white" />
                </clipPath>
            </defs>
        </svg>
    );

    const renderLabelTag = () => (
        <div
            className={`absolute bottom-0 right-0 z-[1] flex h-6 whitespace-nowrap items-center justify-center gap-1 rounded-tl-xl rounded-tr-none rounded-br-lg rounded-bl-none px-2 py-0.5 text-[14px] font-normal leading-5 ${isWeb
                ? "min-w-[79px] bg-[#F7F3FF] text-[#8537F5]"
                : "min-w-[76px] bg-[#F5F8FF] text-[#024DE3]"
                }`}
        >
            {i18next.t(isWeb ? "citation.web" : "citation.document")}
        </div>
    );
    const formattedSourceMeta = isWeb ? formatSourceMeta(preview.sourceMeta) : "";
    const ragTitleParts = splitRagTitle(preview.title);

    const renderWebTitle = () => {
        const titleContent = (
            <>
                <span className="min-w-0 flex-1 truncate">{preview.title}</span>
                {preview.link && renderWebHoverIcon()}
            </>
        );

        return (
            <div className={`flex items-center gap-2 ${preview.link ? interactiveTitleClassName : titleClassName}`}>
                {titleContent}
            </div>
        );
    };

    const renderRagTitle = () => (
        <div className="flex h-[38px] items-center gap-2 bg-[#F7F7F7] px-3 py-2">
            <CitationSourceIcon detail={detail} preview={preview} type={preview.type} />
            <div className="flex min-w-0 flex-1 items-center gap-1">
                <span
                    className={`${onOpenDocumentPreview ? `${ragTitleClassName} transition-colors duration-200 group-hover:text-[#024DE3]` : ragTitleClassName} flex-1`}
                    title={preview.title}
                >
                    {ragTitleParts.name || preview.title}
                </span>
                {ragTitleParts.extension && (
                    <span className={`${onOpenDocumentPreview ? "shrink-0 text-[14px] font-medium leading-[22px] text-[#1D2129] transition-colors duration-200 group-hover:text-[#024DE3]" : "shrink-0 text-[14px] font-medium leading-[22px] text-[#1D2129]"}`}>
                        {ragTitleParts.extension}
                    </span>
                )}
            </div>
        </div>
    );

    const renderWebPreview = () => (
        <>
            <div className={titleContainerClassName}>
                {renderWebTitle()}
            </div>
            <div className="px-4 py-3 pb-0">
                <div className="border-l-2 border-[#E5E6EB] pl-3 text-[14px] leading-6 text-[#1D2129]">
                    <div className="line-clamp-4 whitespace-pre-wrap break-words">
                        {preview.snippet || i18next.t("citation.noSummary")}
                    </div>
                </div>
                <div className="mt-3 min-h-6 pr-[95px] text-[#999999]">
                    <div className="flex min-w-0 items-center gap-2 pb-0">
                        <CitationSourceIcon detail={detail} preview={preview} type={preview.type} ragIconVariant="knowledge" />
                        <span className="w-[90px] min-w-0 truncate text-[12px] font-medium leading-5">{preview.sourceName}</span>
                        {formattedSourceMeta && <span className="shrink-0 text-[12px] font-normal leading-5">{formattedSourceMeta}</span>}
                    </div>
                </div>
            </div>
        </>
    );

    const renderRagPreview = () => (
        <>
            {renderRagTitle()}
            <div className="px-4 py-3 pb-0">
                <div className="border-l-2 border-[#E5E6EB] pl-3 text-[14px] leading-6 text-[#1D2129]">
                    <div className="line-clamp-4 whitespace-pre-wrap break-words">
                        {preview.snippet || i18next.t("citation.noSummary")}
                    </div>
                </div>
                <div className="mt-3 min-h-6 pr-[95px] text-[#999999]">
                    <div className="flex min-w-0 items-center gap-2 pb-0">
                        <CitationSourceIcon detail={detail} preview={preview} type={preview.type} ragIconVariant="knowledge" />
                        <span className="w-[90px] min-w-0 truncate text-[12px] font-medium leading-5">{preview.sourceName}</span>
                        {formattedSourceMeta && <span className="shrink-0 text-[12px] font-normal leading-5">{formattedSourceMeta}</span>}
                    </div>
                </div>
            </div>
        </>
    );

    return (
        <div className={cardClassName} onClick={onCardClick}>
            {isWeb ? renderWebPreview() : renderRagPreview()}
            {renderLabelTag()}
        </div>
    );
}
