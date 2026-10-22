import { Outlined } from 'bisheng-icons';
import { useMarkdownServices } from './MarkdownServices';
import type { ChatCitation, CitationPreview } from './types';
function DefaultSourceIcon() { return <Outlined.FileWord size={16} />; }
export function CitationPreviewCard({ preview, detail, isLoading, error, notPermitted, expired, onCardClick, onOpenDocumentPreview, }: {
    preview: CitationPreview | null;
    detail?: ChatCitation | null;
    isLoading: boolean;
    error: boolean;
    notPermitted?: boolean;
    expired?: boolean;
    onCardClick?: () => void;
    onOpenDocumentPreview?: () => void;
}) {
    const { localize, SourceIcon = DefaultSourceIcon } = useMarkdownServices();
const CitationSourceIcon = SourceIcon;
    if (isLoading) {
        return (<div className="flex min-h-[120px] w-[320px] max-w-[calc(100vw-32px)] items-center justify-center rounded-lg bg-white text-sm text-text-3 shadow-[0_4px_19px_rgba(34,34,34,0.07)]">
        <Outlined.Loading className="mr-2 size-4 animate-spin"/>
        {localize('shared:app_chat.citation.loading')}
      </div>);
    }
    if (notPermitted) {
        return (<div className="w-[320px] max-w-[calc(100vw-32px)] rounded-lg bg-white p-4 text-sm text-text-3 shadow-[0_4px_19px_rgba(34,34,34,0.07)]">
        {localize('shared:app_chat.citation.no_permission')}
      </div>);
    }
    if (expired) {
        return (<div className="w-[320px] max-w-[calc(100vw-32px)] rounded-lg bg-white p-4 text-sm text-text-3 shadow-[0_4px_19px_rgba(34,34,34,0.07)]">
        {localize('shared:app_chat.citation.source_expired')}
      </div>);
    }
    if (error || !preview) {
        return (<div className="w-[320px] max-w-[calc(100vw-32px)] rounded-lg bg-white p-4 text-sm text-text-3 shadow-[0_4px_19px_rgba(34,34,34,0.07)]">
        {localize('shared:app_chat.citation.no_detail')}
      </div>);
    }
    const isWeb = preview.type === 'web';
    const cardClassName = 'group relative cursor-pointer w-[320px] max-w-[calc(100vw-32px)] overflow-hidden rounded-lg bg-white text-text-1 shadow-[0_4px_19px_rgba(34,34,34,0.07)]';
    const titleClassName = 'min-w-0 flex-1 truncate text-[14px] font-medium leading-5 text-text-1';
    const titleContainerClassName = 'bg-white p-3';
    const interactiveTitleClassName = `${titleClassName} transition-colors duration-200 group-hover:text-[#1B61E6]`;
    const ragTitleClassName = 'min-w-0 truncate text-[14px] font-medium leading-[22px] text-text-1';
    const formatSourceMeta = (value?: string) => {
        if (!value) {
            return '';
        }
        const normalizedValue = value.trim();
        const matched = normalizedValue.match(/^(\d{4}-\d{2}-\d{2})[T\s](\d{2}:\d{2})/);
        if (matched) {
            return `${matched[1]} ${matched[2]}`;
        }
        return normalizedValue;
    };
    const splitRagTitle = (value?: string) => {
        const normalizedValue = String(value || '').trim();
        const matched = normalizedValue.match(/^(.*?)(\.[a-zA-Z0-9]+)$/);
        if (!matched) {
            return {
                name: normalizedValue,
                extension: '',
            };
        }
        return {
            name: matched[1],
            extension: matched[2],
        };
    };
    const renderWebHoverIcon = () => (<svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg" className="hidden shrink-0 group-hover:block" aria-hidden="true">
      <g clipPath="url(#citation-web-hover-icon-clip)">
        <path d="M16 0H0V16H16V0Z" fill="white" fillOpacity="0.01"/>
        <path d="M5.33398 10.6667L11.0007 5" stroke="#1B61E6" strokeWidth="1.33333" strokeLinecap="round" strokeLinejoin="round"/>
        <path d="M5 5H11V11" stroke="#1B61E6" strokeWidth="1.33333" strokeLinecap="round" strokeLinejoin="round"/>
      </g>
      <defs>
        <clipPath id="citation-web-hover-icon-clip">
          <rect width="16" height="16" fill="white"/>
        </clipPath>
      </defs>
    </svg>);
    const formattedSourceMeta = isWeb ? formatSourceMeta(preview.sourceMeta) : '';
    const ragTitleParts = splitRagTitle(preview.title);
    const ragSnippetText = String(preview.snippet || '')
        .replace(/!\[[^\]]*\]\([^)]*\)/g, '')
        .replace(/<\/?[a-zA-Z][^>]*>/g, '')
        .split('\n')
        .filter((line) => line.trim() !== '')
        .join('\n');
    const renderWebTitle = () => {
        const titleContent = (<>
        <span className="min-w-0 flex-1 truncate">{preview.title}</span>
        {preview.link && renderWebHoverIcon()}
      </>);
        return (<div className={`flex items-center gap-2 ${preview.link ? interactiveTitleClassName : titleClassName}`}>
        {titleContent}
      </div>);
    };
    const renderRagTitle = () => (<div className="flex items-center gap-2 bg-white p-3">
      <CitationSourceIcon detail={detail} preview={preview} type={preview.type}/>
      <div className="flex min-w-0 flex-1 items-center gap-1">
        <span className={`${onOpenDocumentPreview ? `${ragTitleClassName} transition-colors duration-200 group-hover:text-blue-600` : ragTitleClassName} min-w-0 truncate`} title={preview.title}>
          {ragTitleParts.name || preview.title}
        </span>
        {ragTitleParts.extension && (<span className={`${onOpenDocumentPreview ? 'shrink-0 text-[14px] font-medium leading-[22px] text-text-1 transition-colors duration-200 group-hover:text-blue-600' : 'shrink-0 text-[14px] font-medium leading-[22px] text-text-1'}`}>
            {ragTitleParts.extension}
          </span>)}
      </div>
    </div>);
    const renderWebPreview = () => (<>
      <div className={titleContainerClassName}>
        {renderWebTitle()}
      </div>
      <div className="px-4 pb-0">
        <div className="border-l-2 border-border-base pl-3 text-[12px] leading-6 text-text-2">
          <div className="line-clamp-4 whitespace-pre-wrap break-words">
            {preview.snippet || localize('shared:app_chat.citation.no_snippet')}
          </div>
        </div>
        <div className="mt-3 min-h-6 text-text-3">
          <div className="flex min-w-0 items-center gap-2 pb-0">
            <CitationSourceIcon detail={detail} preview={preview} type={preview.type} ragIconVariant="knowledge"/>
            <span className="w-[90px] min-w-0 truncate text-[12px] font-medium leading-5">{preview.sourceName}</span>
            {formattedSourceMeta && <span className="ml-auto shrink-0 text-[12px] font-normal leading-5">{formattedSourceMeta}</span>}
          </div>
        </div>
      </div>
    </>);
    const renderRagPreview = () => (<>
      {renderRagTitle()}
      <div className="px-4 pb-0">
        <div className="border-l-2 border-border-base pl-3 text-[12px] leading-6 text-text-2">
          <div className="line-clamp-4 whitespace-pre-wrap break-words">
            {ragSnippetText || localize('shared:app_chat.citation.no_snippet')}
          </div>
        </div>
        <div className="mt-3 min-h-6 text-text-3">
          <div className="flex min-w-0 items-center gap-2 pb-0">
            <CitationSourceIcon detail={detail} preview={preview} type={preview.type} ragIconVariant="knowledge" clipAsCircle={false}/>
            <span className="w-[90px] min-w-0 truncate text-[12px] font-medium leading-5">{preview.sourceName}</span>
            {formattedSourceMeta && <span className="shrink-0 text-[12px] font-normal leading-5">{formattedSourceMeta}</span>}
          </div>
        </div>
      </div>
    </>);
    return (<div className={cardClassName} onClick={onCardClick}>
      {isWeb ? renderWebPreview() : renderRagPreview()}
    </div>);
}
