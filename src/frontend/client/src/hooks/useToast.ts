import { useEffect } from 'react';
import { toast, type ToastType } from '@bisheng/ui';
import type { TShowToast } from '~/common';
import { NotificationSeverity } from '~/common';

/**
 * Legacy `showToast(...)` façade over the shared @bisheng/ui toast
 * (packages/ui/docs/组件-Toast轻提示.md). Every existing call site keeps working;
 * the queueing, stacking, timing and a11y now live in the library.
 *
 * Behaviour changes that come with the shell (all from the spec):
 * - up to 3 toasts stack instead of the newest replacing the previous one;
 * - re-firing the same type+message updates that toast instead of adding one;
 * - the lifetime is derived from the copy (3–10s) when `duration` is omitted;
 * - `duration: 0` now means "stays until dismissed" (it used to hide instantly);
 *   no call site passed 0 when this landed.
 *
 * `showIcon` is accepted for compatibility but ignored: every toast carries its
 * type icon, since the icon is what conveys the semantics without color (§2).
 *
 * New code should import `{ toast }` from '@bisheng/ui' directly.
 */
declare global {
  interface Window {
    /** Set below — the global fallback used by the request interceptor. */
    showToast: typeof showToast;
  }
}

export default function useToast() {
  // Global escape hatch for non-React callers (api/request.ts error fallback).
  useEffect(() => {
    window.showToast = showToast;
  }, []);

  return { showToast };
}

export function showToast({
  message,
  severity = NotificationSeverity.SUCCESS,
  duration,
  status,
}: TShowToast) {
  // The two legacy fields carry the same four values (§10.3) — converging them
  // into one is still an open decision, so both keep working.
  toast.show({ type: (status ?? severity) as ToastType, message, duration });
}
