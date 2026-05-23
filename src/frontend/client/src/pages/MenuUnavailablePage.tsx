import { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { ApprovalApiError, applyMenuAccessApi, checkMenuAccessPendingApi } from '~/api/approval';
import { useToastContext } from '~/Providers';
import { NotificationSeverity } from '~/common';
import { useAuthContext, useLocalize } from '~/hooks';
import { WorkbenchEmptyIllustration } from '~/components/workbench/WorkbenchEmptyIllustration';

const MENU_LABEL_KEYS: Record<string, string> = {
  home: 'com_nav_home',
  knowledge_space: 'com_knowledge.knowledge_space',
  subscription: 'com_ui_channel',
  apps: 'com_nav_app_center',
};

const PLUGIN_DEFAULT_ROUTES: Record<string, string> = {
  home: '/c/new',
  knowledge_space: '/knowledge',
  subscription: '/channel',
  apps: '/apps',
};

export default function MenuUnavailablePage() {
  const [searchParams] = useSearchParams();
  const { user } = useAuthContext();
  const navigate = useNavigate();
  const localize = useLocalize();
  const { showToast } = useToastContext();

  const pluginId = searchParams.get('plugin') || '';
  const hasPlugin = Array.isArray((user as { plugins?: string[] } | null)?.plugins)
    && Boolean((user as { plugins?: string[] } | null)?.plugins?.includes(pluginId));
  const menuApprovalMode = Boolean((user as { menu_approval_mode?: boolean } | null)?.menu_approval_mode);
  const canApply = Boolean(pluginId) && menuApprovalMode && !hasPlugin;

  // If the user already has the permission (e.g. approval was granted and they refreshed),
  // redirect to the target page automatically.
  useEffect(() => {
    if (!hasPlugin || !pluginId) return;
    const target = PLUGIN_DEFAULT_ROUTES[pluginId] ?? '/';
    navigate(target, { replace: true });
  }, [hasPlugin, pluginId]);
  const menuName = pluginId ? localize((MENU_LABEL_KEYS[pluginId] || pluginId) as any) : '';

  const [showDialog, setShowDialog] = useState(false);
  const [reason, setReason] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [applied, setApplied] = useState(false);

  // When the target plugin changes: immediately clear stale "已申请" state, then
  // verify whether there is already a pending application for the new plugin.
  // Cleanup cancels any in-flight request so a slow response for a previous
  // plugin cannot overwrite the result for the current one.
  useEffect(() => {
    setApplied(false);
    if (!canApply || !pluginId) return;
    let cancelled = false;
    checkMenuAccessPendingApi(pluginId)
      .then((res) => { if (!cancelled) setApplied(res.has_pending); })
      .catch(() => { /* ignore — fall back to unapplied state */ });
    return () => { cancelled = true; };
  }, [canApply, pluginId]);

  const handleSubmit = async () => {
    if (!canApply || !pluginId || submitting) return;
    setSubmitting(true);
    try {
      await applyMenuAccessApi({
        menu_key: pluginId,
        menu_name: menuName || pluginId,
        reason: reason.trim() || undefined,
      });
      setApplied(true);
      setShowDialog(false);
      showToast({
        message: localize('com_menu_unavailable_apply_success'),
        severity: NotificationSeverity.SUCCESS,
      });
    } catch (err) {
      const errMsg = err instanceof ApprovalApiError
        ? (localize(`api_errors.${err.statusCode}` as any, { defaultValue: '' }) as string
            || localize('com_menu_unavailable_apply_failed'))
        : localize('com_menu_unavailable_apply_failed');
      showToast({
        message: errMsg,
        severity: NotificationSeverity.ERROR,
      });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="flex h-full min-h-[320px] w-full flex-1 flex-col items-center justify-center bg-white px-6 py-12">
      <div className="mb-6 opacity-80">
        <WorkbenchEmptyIllustration />
      </div>
      <p className="max-w-xl text-center text-sm leading-relaxed text-gray-500" role="status">
        {localize('com_menu_unavailable_no_permission')}
      </p>
      {canApply && (
        <div className="mt-6 flex flex-col items-center gap-3">
          <div className="text-sm text-[#4e5969]">
            {localize('com_menu_unavailable_apply_hint', { menu: menuName || pluginId } as any)}
          </div>
          <button
            type="button"
            disabled={applied}
            className="rounded-lg bg-[#165dff] px-4 py-2 text-sm text-white transition-colors hover:bg-[#0e42d2] disabled:cursor-not-allowed disabled:opacity-60"
            onClick={() => setShowDialog(true)}
          >
            {applied
              ? localize('com_menu_unavailable_apply_submitted')
              : localize('com_menu_unavailable_apply_button')}
          </button>
        </div>
      )}

      {/* Apply reason dialog */}
      {showDialog && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4">
          <div className="w-full max-w-sm rounded-2xl bg-white p-6 shadow-xl">
            <h3 className="mb-4 text-base font-semibold text-gray-900">
              {localize('com_menu_unavailable_apply_button')}
            </h3>
            <label className="mb-1 block text-sm text-gray-600">
              {localize('com_menu_unavailable_reason_label')}
            </label>
            <textarea
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              rows={3}
              placeholder={localize('com_menu_unavailable_reason_placeholder') as string}
              className="mb-4 w-full resize-none rounded-lg border border-gray-200 px-3 py-2 text-sm text-gray-800 outline-none focus:border-[#165dff]"
            />
            <div className="flex justify-end gap-3">
              <button
                type="button"
                onClick={() => { setShowDialog(false); setReason(''); }}
                className="rounded-lg border border-gray-200 px-4 py-2 text-sm text-gray-700 hover:bg-gray-50"
              >
                {localize('com_ui_cancel')}
              </button>
              <button
                type="button"
                disabled={submitting}
                onClick={() => void handleSubmit()}
                className="rounded-lg bg-[#165dff] px-4 py-2 text-sm text-white hover:bg-[#0e42d2] disabled:opacity-60"
              >
                {submitting ? localize('com_menu_unavailable_apply_submitting') : localize('com_ui_submit')}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
