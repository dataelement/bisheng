/**
 * Toast has moved to the shared component library (@bisheng/ui) — one imperative
 * API (`toast.success(...)`) plus a single always-mounted container, per
 * packages/ui/docs/组件-Toast轻提示.md.
 *
 * This module keeps the old default export working: `<Toast />` still renders
 * the container at the app root. New code imports `{ toast }` from '@bisheng/ui'
 * (or keeps using `useToastContext()`, which now delegates here).
 */
import { Toaster } from '@bisheng/ui';
import { useLocalize } from '~/hooks';

export { toast } from '@bisheng/ui';

export default function Toast() {
  const localize = useLocalize();
  return <Toaster closeLabel={localize('com_ui_close')} />;
}
