import * as React from 'react';
import * as DialogPrimitive from '@radix-ui/react-dialog';
import { Outlined } from 'bisheng-icons';
import cn from '../../utils/cn';

/**
 * Modal — the centered, interrupting overlay (组件-Modal弹窗.md v1).
 *
 * One shell for every business dialog: header (56px, fixed) + body (the ONLY
 * scrolling area) + footer (fixed). 16px of side padding throughout; the body
 * adds none of its own top/bottom — the header's height and the footer's
 * padding already hold that gap open. Everything the spec pins down
 * — the four sizes and their step-down table, the 40% black mask with no blur,
 * the z-index tier, the 200/160ms curves, the three exits — lives here, so a
 * business page never restates it.
 *
 * Not this component: a confirm/deny prompt (二次确认 has its own component)
 * and anything that should stay beside the page content (Drawer).
 */

/** §2 — four sizes; `fullscreen` is also what every size becomes on a phone (§7). */
export type ModalSize = 'small' | 'medium' | 'large' | 'fullscreen';

/** Which of the three exits (§6) the user took. */
export type ModalDismissSource = 'close-button' | 'overlay' | 'esc';

/**
 * §2/§3 — the width ladder, CSS only (no JS measuring).
 *
 * Mobile-first: the base state is the phone (< 576px) full-screen sheet, so the
 * card widths all start at `min-[576px]:`, then step UP at lg (1024) / xl (1280).
 * `min(<档位>, calc(100vw - 32px))` is the catch-all gutter rule — 16px of page
 * has to stay visible on each side, or the dialog reads as a pinned panel.
 */
const SIZE_WIDTH: Record<Exclude<ModalSize, 'fullscreen'>, string> = {
  small: 'min-[576px]:w-[min(400px,calc(100vw-32px))]',
  medium: 'min-[576px]:w-[min(400px,calc(100vw-32px))] lg:w-[min(600px,calc(100vw-32px))]',
  large:
    'min-[576px]:w-[min(400px,calc(100vw-32px))] lg:w-[min(600px,calc(100vw-32px))] xl:w-[min(960px,calc(100vw-32px))]',
};

/** §5 — 40% black, no blur (a blurred backdrop reads as "I left the page"). */
const OVERLAY_CLASS =
  'fixed inset-0 z-modal bg-black/40 data-[state=open]:animate-modal-overlay-in data-[state=closed]:animate-modal-overlay-out motion-reduce:animate-none';

/** Phone (< 576px) has no visible outside area — §7 says the mask is not drawn. */
const OVERLAY_PHONE_CLASS = 'hidden min-[576px]:block';

/**
 * The card itself is the positioned layer — deliberately NOT wrapped in a
 * centring div: `Dialog.Portal` puts every child in its own `Presence`, and a
 * plain wrapper (no animation of its own) unmounts the whole subtree the
 * instant it closes, cutting the 160ms exit short.
 */
const CONTENT_BASE =
  'fixed z-modal flex flex-col overflow-hidden bg-bg-page text-text-1 outline-none data-[state=open]:animate-modal-content-in data-[state=closed]:animate-modal-content-out motion-reduce:animate-none';

/** §7 — phone: the dialog IS the screen. Square corners, no mask, no gutter. */
const CONTENT_PHONE = 'inset-0 h-full w-full rounded-none';

/** §2/§4 — from the tablet档 up: a centred 16px-radius card, capped at 视窗高 - 64px. */
const CONTENT_CARD =
  'min-[576px]:inset-auto min-[576px]:left-1/2 min-[576px]:top-1/2 min-[576px]:-translate-x-1/2 min-[576px]:-translate-y-1/2 min-[576px]:h-auto min-[576px]:max-h-[calc(100vh-64px)] min-[576px]:rounded-2xl min-[576px]:border min-[576px]:border-border-base min-[576px]:shadow-modal';

export interface ModalProps {
  /** Controlled visibility. Leave out (with `defaultOpen` / `trigger`) to let the dialog own it. */
  open?: boolean;
  defaultOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
  /** Element that opens the dialog; wired up as the dialog's trigger automatically. */
  trigger?: React.ReactNode;
  /** §2 — pick by how WIDE the content is, never by how long it is. */
  size?: ModalSize;
  /** Header title. Required: it is what the dialog is announced as. */
  title: React.ReactNode;
  /** Optional line under the title, inside the body. */
  description?: React.ReactNode;
  /** Body content — the only part that scrolls. */
  children?: React.ReactNode;
  /** Footer actions, primary rightmost (组件-Button按钮.md). Omit and the footer is not rendered. */
  footer?: React.ReactNode;
  /**
   * The header「×」(§4). Decided by dialog TYPE, not by whether a 取消 button
   * exists: a form dialog keeps both (取消 sits by the primary button, the「×」is
   * where a hand reaches to dismiss a layer — different places to look); a
   * confirm dialog drops it, its two footer buttons already are the question.
   */
  closable?: boolean;
  /** Accessible name of the「×」button. Text comes from the caller (library contract). */
  closeLabel?: string;
  /** §6 — clicking the mask closes. Turn off for a dialog that must be answered. */
  maskClosable?: boolean;
  /** §6 — Esc closes. */
  escClosable?: boolean;
  /** §6 — while a submit is in flight ALL three exits are disabled until it returns. */
  submitting?: boolean;
  /**
   * Runs before an exit closes the dialog; return `false` to keep it open.
   * That is how unsaved input gets its 二次确认 (§6) — the caller opens the
   * confirm and closes the dialog itself once the user gives it up.
   */
  beforeClose?: (source: ModalDismissSource) => boolean | void;
  /** Portal target; defaults to `document.body`. */
  container?: HTMLElement | null;
  /** Extra classes on the card. */
  className?: string;
  /** Extra classes on the body — e.g. `p-0` for a preview that bleeds to the edge. */
  bodyClassName?: string;
  /** Extra classes on the footer. */
  footerClassName?: string;
  /** Escape hatch for the mask (§5) — e.g. a lighter second layer. Nesting needs
   * nothing here: a confirm opened on top of a dialog draws its own mask. */
  overlayClassName?: string;
}

export function Modal({
  open,
  defaultOpen,
  onOpenChange,
  trigger,
  size = 'medium',
  title,
  description,
  children,
  footer,
  closable = true,
  closeLabel = 'Close',
  maskClosable = true,
  escClosable = true,
  submitting = false,
  beforeClose,
  container,
  className,
  bodyClassName,
  footerClassName,
  overlayClassName,
}: ModalProps) {
  const isFullscreen = size === 'fullscreen';

  /** True when this exit must NOT close the dialog (§6). */
  const blocked = React.useCallback(
    (source: ModalDismissSource) => submitting || beforeClose?.(source) === false,
    [submitting, beforeClose],
  );

  return (
    <DialogPrimitive.Root open={open} defaultOpen={defaultOpen} onOpenChange={onOpenChange}>
      {trigger ? <DialogPrimitive.Trigger asChild>{trigger}</DialogPrimitive.Trigger> : null}
      <DialogPrimitive.Portal container={container ?? undefined}>
        {isFullscreen ? null : (
          <DialogPrimitive.Overlay className={cn(OVERLAY_CLASS, OVERLAY_PHONE_CLASS, overlayClassName)} />
        )}
        <DialogPrimitive.Content
          className={cn(
            CONTENT_BASE,
            CONTENT_PHONE,
            isFullscreen ? null : [CONTENT_CARD, SIZE_WIDTH[size]],
            className,
          )}
          onEscapeKeyDown={(event) => {
            if (!escClosable || blocked('esc')) event.preventDefault();
          }}
          onInteractOutside={(event) => {
            if (!maskClosable || blocked('overlay')) event.preventDefault();
          }}
        >
          {/* §4 — header and footer never scroll; only the body does. Same
           * arrangement at every size, 全屏档 and phone included: title left,
           *「×」right, actions in the footer (§2). */}
          <div className="flex h-14 shrink-0 items-center gap-3 px-4">
            <DialogPrimitive.Title className="min-w-0 flex-1 truncate text-h4 text-text-1">
              {title}
            </DialogPrimitive.Title>
            {closable ? (
              <DialogPrimitive.Close asChild>
                <button
                  type="button"
                  aria-label={closeLabel}
                  disabled={submitting}
                  onClick={(event) => {
                    if (blocked('close-button')) event.preventDefault();
                  }}
                  className="btn-touch-hit relative flex size-6 shrink-0 items-center justify-center rounded-md text-text-3 transition-colors hover:bg-fill-1 hover:text-text-1 disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:bg-transparent"
                >
                  <Outlined.Close className="size-4" />
                </button>
              </DialogPrimitive.Close>
            ) : null}
          </div>

          <div
            className={cn(
              // §4 — the body keeps NO vertical padding of its own; the header's
              // height and the footer's padding already hold that gap open.
              // `py-0.5 -my-0.5` is not spacing: a scroll container clips at its
              // padding box, and with zero vertical padding that edge cuts the
              // 2px focus ring off any field sitting first or last in the body.
              // The padding gives the ring its 2px, the negative margin takes
              // the same 2px back out of the layout — nothing moves.
              'min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 py-0.5 -my-0.5 text-body',
              bodyClassName,
            )}
          >
            {description ? (
              <DialogPrimitive.Description className="mb-3 text-body text-text-2">
                {description}
              </DialogPrimitive.Description>
            ) : null}
            {children}
          </div>

          {footer ? (
            <div
              className={cn(
                // §2/§7 — whenever the dialog owns the whole screen (any size on
                // a phone, the 全屏档 everywhere) the actions tile the row edge
                // to edge and clear the home-indicator safe area; on a card they
                // sit right-aligned at their natural width.
                'flex shrink-0 items-center justify-end gap-3 p-4 [&>*]:flex-1',
                'pb-[calc(16px+env(safe-area-inset-bottom))]',
                isFullscreen ? null : 'min-[576px]:pb-4 min-[576px]:[&>*]:flex-none',
                footerClassName,
              )}
            >
              {footer}
            </div>
          ) : null}
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}

/**
 * Closes the dialog it sits in — put it on the footer's 取消 button
 * (`<ModalClose asChild><Button …/></ModalClose>`). It does NOT run
 * `beforeClose`: that guard is for the three accidental exits, not for a button
 * the user aimed at.
 */
export const ModalClose = DialogPrimitive.Close;
