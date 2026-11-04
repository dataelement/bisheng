import React, { useEffect, useRef, useState } from 'react';
import * as Popover from '@radix-ui/react-popover';
import { Badge } from '@bisheng/ui';
import { asRecord } from '../core/normalizeHistory';
import { useCitationPresentation, useCitationUtilities } from './MarkdownServices';
import { CitationPreviewCard } from './CitationPreviewCard';
import type { ChatCitation, CitationDisplayData, CitationDetailLoader } from './types';
export const Citation = ({ data: rawData, children, initialDetail, initialNotPermitted, initialExpired, webContent, loadCitationDetail, popoverKey, activePopoverKey, onActivePopoverKeyChange, onClosePopover, onOpenDocumentPreview, citationPreviewUsesHover, }: {
    data: Partial<CitationDisplayData>;
    children: React.ReactNode;
    initialDetail?: ChatCitation | null;
    initialNotPermitted?: boolean;
    initialExpired?: boolean;
    webContent?: unknown;
    loadCitationDetail: CitationDetailLoader;
    popoverKey: string;
    activePopoverKey: string | null;
    onActivePopoverKeyChange: (key: string | null) => void;
    onClosePopover: (key: string) => void;
    onOpenDocumentPreview: (detail: ChatCitation, itemId?: string, locateChunk?: boolean) => void;
    citationPreviewUsesHover: boolean;
}) => {
    const data = rawData ?? ({} as Partial<CitationDisplayData>);
    const hasData = !!rawData;
    const isOpen = activePopoverKey === popoverKey;
    const { localize } = useCitationPresentation();
const { normalizeCitationType, getLegacyCitationPreview, buildCitationPreview, isArticleCitation, getCitationArticleUrl, isFilePreviewCitation, getCitationSourceLabelKey } = useCitationUtilities();
    const [detail, setDetail] = useState<ChatCitation | null>(initialDetail ?? null);
    const [isLoading, setIsLoading] = useState(false);
    const [error, setError] = useState(false);
    const [notPermitted, setNotPermitted] = useState(!!initialNotPermitted);
    const [expired, setExpired] = useState(!!initialExpired);
    const closeTimerRef = useRef<number | null>(null);
    const identity=JSON.stringify([data.citationId,data.itemId]);
    const lifecycle=useRef({identity,mounted:true});lifecycle.current.identity=identity;
    useEffect(()=>{const state=lifecycle.current;state.mounted=true;return()=>{state.mounted=false;};},[]);
    const citationSource = normalizeCitationType(data.type) === 'web' ? 'web' : 'document';
    const legacyPreview = data.ref?.startsWith('citation:')
        ? getLegacyCitationPreview(webContent, data.label)
        : null;
    const preview = legacyPreview ?? buildCitationPreview(detail, data);
    const fetchDetail = async () => {
        if (detail || notPermitted || legacyPreview || !data.citationId || data.citationId.startsWith('citation:')) {
            return detail;
        }
        setIsLoading(true);
        setError(false);
        try {
            const nextDetail = await loadCitationDetail(data.citationId);
            if(!lifecycle.current.mounted||lifecycle.current.identity!==identity)return null;
            setDetail(nextDetail);
            return nextDetail;
        }
        catch (err) {
            if(!lifecycle.current.mounted||lifecycle.current.identity!==identity)return null;
 const reason = asRecord(err);
            if (reason.citationExpired) {
                setExpired(true);
            }
            else if (reason.citationForbidden) {
                setNotPermitted(true);
            }
            else {
                console.error('Failed to load citation detail:', err);
                setError(true);
            }
            return null;
        }
        finally {
            if(lifecycle.current.mounted&&lifecycle.current.identity===identity)setIsLoading(false);
        }
    };
    const openWebCitation = (url?: string, targetWindow?: Window | null) => {
        if (!url) {
            targetWindow?.close();
            return;
        }
        if (targetWindow) {
            targetWindow.opener = null;
            targetWindow.location.href = url;
            return;
        }
        window.open(url, '_blank', 'noopener,noreferrer');
    };
    const handleOpenChange = (nextOpen: boolean) => {
        if (closeTimerRef.current) {
            window.clearTimeout(closeTimerRef.current);
            closeTimerRef.current = null;
        }
        onActivePopoverKeyChange(nextOpen ? popoverKey : null);
        if (nextOpen) {
            void fetchDetail();
        }
    };
    const scheduleClose = () => {
        if (closeTimerRef.current) {
            window.clearTimeout(closeTimerRef.current);
        }
        closeTimerRef.current = window.setTimeout(() => {
            onClosePopover(popoverKey);
        }, 120);
    };
    const handleCitationClick = async (event?: React.MouseEvent, options?: {
        forceDocument?: boolean;
    }) => {
        event?.preventDefault();
        event?.stopPropagation();
        if (notPermitted || expired) {
            handleOpenChange(!isOpen);
            return;
        }
        const articleUrl = isArticleCitation(detail, data.type)
            ? preview?.link || getCitationArticleUrl(detail)
            : '';
        if (articleUrl) {
            openWebCitation(articleUrl);
            return;
        }
        const isWebCitation = normalizeCitationType(preview?.type || data.type) === 'web';
        if (isWebCitation && preview?.link) {
            openWebCitation(preview.link);
            return;
        }
        if (!citationPreviewUsesHover && !options?.forceDocument) {
            if (closeTimerRef.current) {
                window.clearTimeout(closeTimerRef.current);
                closeTimerRef.current = null;
            }
            handleOpenChange(!isOpen);
            return;
        }
        const pendingWebWindow = isWebCitation ? window.open('about:blank', '_blank') : null;
        const nextDetail = detail ?? await fetchDetail();
        const nextPreview = legacyPreview ?? buildCitationPreview(nextDetail, data);
        if (normalizeCitationType(nextPreview?.type || nextDetail?.type || data.type) === 'web') {
            openWebCitation(nextPreview?.link, pendingWebWindow);
            return;
        }
        pendingWebWindow?.close();
        if (!nextDetail || !isFilePreviewCitation(nextDetail, data.type)) {
            return;
        }
        if (closeTimerRef.current) {
            window.clearTimeout(closeTimerRef.current);
            closeTimerRef.current = null;
        }
        if (!options?.forceDocument) {
            onActivePopoverKeyChange(null);
        }
        onOpenDocumentPreview(nextDetail, data.itemId, true);
    };
    useEffect(() => {
        setDetail(initialDetail??null);setNotPermitted(!!initialNotPermitted);setExpired(!!initialExpired);setError(false);
    },[identity,initialDetail,initialNotPermitted,initialExpired]);
    useEffect(() => {
        return () => {
            if (closeTimerRef.current) {
                window.clearTimeout(closeTimerRef.current);
            }
        };
    }, []);
    if (!hasData) {
        return null;
    }
    return (<Popover.Root open={isOpen} onOpenChange={handleOpenChange}>
      <Popover.Trigger asChild>
        
        <Badge citation={citationSource} data-citation-trigger="true" data-citation-ref={data.ref} data-citation-id={data.citationId} data-citation-item-id={data.itemId} data-citation-type={data.type} data-citation-group-key={data.groupKey} data-citation-chunk-id={data.chunkId} aria-label={localize('shared:app_chat.citation.badge_aria', {
            source: localize(getCitationSourceLabelKey(data.type)),
            index: data.label ?? '',
        })} onClick={handleCitationClick} onMouseEnter={() => {
            if (!citationPreviewUsesHover)
                return;
            handleOpenChange(true);
        }} onMouseLeave={() => {
            if (!citationPreviewUsesHover)
                return;
            scheduleClose();
        }} className={notPermitted ? 'ml-2 cursor-default' : 'ml-2'}>
          {children}
        </Badge>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content side="top" align="start" sideOffset={8} avoidCollisions collisionPadding={16} data-citation-popover-surface data-citation-trigger="true" onMouseEnter={() => {
            if (!citationPreviewUsesHover)
                return;
            handleOpenChange(true);
        }} onMouseLeave={() => {
            if (!citationPreviewUsesHover)
                return;
            scheduleClose();
        }} className="z-50 outline-none">
          <CitationPreviewCard preview={preview} detail={detail} isLoading={isLoading} error={error} notPermitted={notPermitted} expired={expired} onCardClick={() => void handleCitationClick(undefined, { forceDocument: true })} onOpenDocumentPreview={() => void handleCitationClick(undefined, { forceDocument: true })}/>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>);
};
