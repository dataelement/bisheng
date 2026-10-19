import * as React from 'react';
import { notification, toast as sharedToast } from '@bisheng/ui';
import type { ToastType } from '@bisheng/ui';

interface LegacyActionProps {
    children?: React.ReactNode;
    altText?: string;
    onClick?: () => void;
}

interface LegacyToastOptions {
    /** Position is now fixed by the shared design system. */
    className?: string;
    title?: React.ReactNode;
    description?: React.ReactNode | string[];
    variant?: ToastType | null;
    action?: React.ReactElement<LegacyActionProps>;
    duration?: number;
    onOpenChange?: (open: boolean) => void;
    isAlert?: boolean;
}

function noticeText(node: React.ReactNode): string {
    if (node === null || node === undefined || typeof node === 'boolean') return '';
    if (Array.isArray(node)) return node.map(noticeText).filter(Boolean).join('\n');
    if (React.isValidElement<{ children?: React.ReactNode }>(node)) return noticeText(node.props.children);
    return String(node);
}

function showNotice(options: LegacyToastOptions, centered: boolean) {
    let current = options;
    const type = options.variant ?? 'info';
    const title = noticeText(options.title);
    const description = noticeText(options.description);
    // Stable keys let the shared queues coalesce repeated interceptor errors.
    const id = `platform:${centered ? 'message' : 'toast'}:${type}:${title}:${description}`;
    const show = () => {
        const nextType = current.variant ?? 'info';
        const nextTitle = noticeText(current.title);
        const nextDescription = noticeText(current.description);
        const action = current.action ? {
            label: current.action.props.altText || noticeText(current.action.props.children),
            onClick: () => current.action?.props.onClick?.(),
        } : undefined;
        if (centered) {
            sharedToast.show({ id, type: nextType, message: [nextTitle, nextDescription].filter(Boolean).join('\n'),
                duration: current.duration, action });
        } else {
            notification.open({ id, type: nextType, title: nextTitle || undefined, description: nextDescription,
                duration: current.duration, actions: action ? [action] : undefined,
                onClose: () => current.onOpenChange?.(false) });
        }
    };
    show();
    return {
        id,
        dismiss: () => {
            if (centered) {
                sharedToast.dismiss(id);
                current.onOpenChange?.(false);
            } else notification.close(id);
        },
        update: (next: Partial<LegacyToastOptions>) => {
            current = { ...current, ...next };
            show();
        },
    };
}

export function toast(options: LegacyToastOptions) {
    return showNotice(options, options.isAlert ?? false);
}

export function message(options: LegacyToastOptions) {
    return showNotice(options, true);
}

function dismiss(id?: string) {
    if (id) {
        sharedToast.dismiss(id);
        notification.close(id);
    } else {
        sharedToast.clear();
        notification.closeAll();
    }
}

// All live callers use these imperative handles. Rendering and queue lifetime
// belong exclusively to the shared containers, including interceptor notices.
export function useToast() {
    return { toast, message, dismiss };
}
