import { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { ApprovalApiError, applyMenuAccessApi, checkMenuAccessPendingApi } from '~/api/approval';
import { useToastContext } from '~/Providers';
import { NotificationSeverity } from '~/common';
import { useAuthContext, useLocalize } from '~/hooks';
import { WorkbenchEmptyIllustration } from '~/components/workbench/WorkbenchEmptyIllustration';
import { Button } from '~/components/ui/Button';
import { CommentDialog } from '~/components/ui/CommentDialog';

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
  // Workspace menu-unavailable flow uses the workbench approval scope (legacy flag as fallback).
  const menuApprovalMode = Boolean(
    (user as { menu_approval_mode_workbench?: boolean; menu_approval_mode?: boolean } | null)
      ?.menu_approval_mode_workbench
    ?? (user as { menu_approval_mode?: boolean } | null)?.menu_approval_mode,
  );
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

  const handleSubmit = async (reason: string) => {
    if (!canApply || !pluginId || submitting) return;
    setSubmitting(true);
    try {
      await applyMenuAccessApi({
        menu_key: pluginId,
        menu_name: menuName || pluginId,
        reason: reason || undefined,
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
    <div className="flex min-h-[320px] w-full flex-1 flex-col items-center justify-center gap-4 bg-white px-8 text-center">
      <WorkbenchEmptyIllustration />
      <div className="flex flex-col items-center gap-1">
        <p className="text-base font-medium leading-6 text-[#1D2129]" role="status">
          {localize('com_menu_unavailable_no_permission')}
        </p>
        {canApply && (
          <p className="text-sm leading-[22px] text-[#999999]">
            {localize('com_menu_unavailable_apply_hint', { menu: menuName || pluginId } as any)}
          </p>
        )}
      </div>
      {canApply && (
        <Button
          className="h-8 rounded-md px-4"
          disabled={applied}
          onClick={() => setShowDialog(true)}
        >
          {applied
            ? localize('com_menu_unavailable_apply_submitted')
            : localize('com_menu_unavailable_apply_button')}
        </Button>
      )}

      {/* Apply reason dialog — shared shell with the message-feedback dialog. */}
      <CommentDialog
        open={showDialog}
        onOpenChange={(open) => { if (!submitting) setShowDialog(open); }}
        title={localize('com_menu_unavailable_apply_button')}
        placeholder={localize('com_menu_unavailable_reason_placeholder') as string}
        submitting={submitting}
        submittingText={localize('com_menu_unavailable_apply_submitting')}
        onSubmit={(reason) => void handleSubmit(reason)}
      />
    </div>
  );
}
