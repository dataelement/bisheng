import { Outlined } from 'bisheng-icons';
import { Tag } from '@bisheng/ui';
import cn from '@bisheng/ui/cn';
import { createCitationUtilities } from './preview';
import { CitationSourceIcon } from './CitationSourceIcon';
import type { ChatCitation, ChatLocalize, CitationPreview, CitationReferenceItem } from './types';
const {getCitationDocumentFileType,normalizeCitationType}=createCitationUtilities(key=>key);
function SourceTypeBadge({ preview, type, localize }: { preview: CitationPreview | null; type?: string;localize:ChatLocalize }) {

  const isWeb = normalizeCitationType(preview?.type || type) === 'web';
  return (
    <Tag size="small" color={isWeb ? 'web' : 'brand'}>
        {localize(isWeb ? 'com_message.source_type_web' : 'com_message.source_type_document')}
    </Tag>
  );
}

export function splitDocumentTitle(title: string, detail: ChatCitation | null, preview: CitationPreview | null) {
  const fileType = String(getCitationDocumentFileType(detail) || preview?.sourceMeta || '')
    .toLowerCase()
    .replace(/^\./, '');

  if (!fileType) {
    return { name: title, extension: '' };
  }

  const normalizedExtension = `.${fileType}`;
  if (title.toLowerCase().endsWith(normalizedExtension)) {
    return {
      name: title.slice(0, title.length - normalizedExtension.length),
      extension: normalizedExtension,
    };
  }

  return { name: title, extension: normalizedExtension };
}

export function CitationReferenceCard({
  item,
  localize,
  onOpenArticle,
  detail,
  isLoading,
  hasError,
  onOpenDocumentPreview,
}: {
  item: CitationReferenceItem;
  localize:ChatLocalize;
  onOpenArticle?:(url:string)=>void;
  detail: ChatCitation | null;
  isLoading: boolean;
  hasError: boolean;
  onOpenDocumentPreview: (item: CitationReferenceItem, detail: ChatCitation) => void;
}) {

  const {buildCitationDocumentPreview,isFilePreviewCitation}=createCitationUtilities(localize);
  const preview = item.legacyPreview ?? buildCitationDocumentPreview(detail, item.data);
  const type = preview?.type || item.data.type;
  const isWeb = normalizeCitationType(type) === 'web';
  const title = preview?.title || localize('com_message.source_untitled');
  const canOpenDocument = !!detail && isFilePreviewCitation(detail, type);
  const { name: documentName, extension: documentExtension } = splitDocumentTitle(title, detail, preview);

  const nameRowTextClass =
    'text-[14px] font-normal leading-[22px] text-text-1';

  return (
    <div className="flex min-h-[92px] flex-col gap-2 rounded-md border border-border-base bg-white p-2">
      <div className="flex items-center">
        <SourceTypeBadge localize={localize} preview={preview} type={item.data.type} />
      </div>

      {canOpenDocument ? (
        <button
          type="button"
          onClick={() => onOpenDocumentPreview(item, detail!)}
          className={cn(
            'flex w-full min-w-0 items-center gap-1 rounded-sm text-left',
            nameRowTextClass,
            'transition-colors hover:text-blue-500 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/25',
          )}
          title={title}
        >
          {!isWeb && <CitationSourceIcon localize={localize} detail={detail} preview={preview} type={type} />}
          <div className="min-w-0 flex-1">
            <span className="inline-flex min-w-0 max-w-full items-baseline gap-0.5">
              <span className="min-w-0 flex-1 truncate text-left">{documentName}</span>
              {documentExtension ? <span className="shrink-0">{documentExtension}</span> : null}
            </span>
          </div>
        </button>
      ) : preview?.link ? (
        <a
          href={preview.link}
          onClick={event=>{if(normalizeCitationType(type)==='article'&&onOpenArticle){event.preventDefault();onOpenArticle(preview.link!);}}}
          target="_blank"
          rel="noreferrer"
          className={cn(
            // Web links are generic external links, not a brand action — pin the
            // hover to a fixed blue (matches the web hover arrow #1B61E6) so it
            // doesn't follow the blue⇄green brand theme.
            'flex w-full min-w-0 items-center gap-1 rounded-sm hover:text-[#1B61E6]',
            nameRowTextClass,
          )}
          title={title}
        >
          {!isWeb && <CitationSourceIcon localize={localize} detail={detail} preview={preview} type={type} />}
          <span className="min-w-0 flex-1 truncate">{title}</span>
        </a>
      ) : (
        <div className={cn('flex min-w-0 items-center gap-1', nameRowTextClass)}>
          {!isWeb && <CitationSourceIcon localize={localize} detail={detail} preview={preview} type={type} />}
          <span className="min-w-0 flex-1 truncate" title={title}>
            {title}
          </span>
        </div>
      )}

      {(isLoading || hasError) && <div className="min-h-[20px] text-[12px] leading-5 text-text-2">
        {isLoading ? (
          <span className="inline-flex items-center gap-2 text-text-3">
            <Outlined.Loading className="size-3.5 animate-spin" />
            {localize('com_message.source_loading')}
          </span>
        ) : hasError ? (
          <span className="text-text-3">{localize('com_message.source_load_failed')}</span>
        ) : (
          null
        )}
      </div>}

      <div className="flex min-w-0 items-center gap-1 text-[12px] leading-5 text-text-3">
        {isWeb ? (
          <>
            <div className="flex size-4 shrink-0 items-center justify-center overflow-hidden rounded-full border border-border-base bg-white">
              <CitationSourceIcon localize={localize} detail={detail} preview={preview} type={type} />
            </div>
            <span className="truncate">{preview?.sourceName || localize('com_message.source_name_fallback_web')}</span>
            {preview?.sourceMeta ? <span className="shrink-0">{preview.sourceMeta}</span> : null}
          </>
        ) : (
          <>
            <CitationSourceIcon localize={localize} detail={detail} preview={preview} type={type} ragIconVariant="knowledge" clipAsCircle={false} />
            <span className="truncate">{preview?.sourceName || localize('com_message.source_name_fallback_document')}</span>
          </>
        )}
      </div>
    </div>
  );
}

