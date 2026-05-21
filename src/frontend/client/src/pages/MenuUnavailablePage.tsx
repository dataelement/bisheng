import { useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useRecoilValue } from 'recoil';
import { applyMenuAccessApi } from '~/api/approval';
import { useToastContext } from '~/Providers';
import { NotificationSeverity } from '~/common';
import { useAuthContext, useLocalize } from '~/hooks';
import { bishengConfState } from '~/pages/appChat/store/atoms';
import { WorkbenchEmptyIllustration } from '~/components/workbench/WorkbenchEmptyIllustration';

const DEFAULT_MESSAGE = '暂无使用过的应用，可以前往应用广场探索更多应用';

const MENU_LABEL_KEYS: Record<string, string> = {
  home: 'com_nav_home',
  knowledge_space: 'com_knowledge.knowledge_space',
  subscription: 'com_ui_channel',
  apps: 'com_nav_app_center',
};

export default function MenuUnavailablePage() {
  const bishengEnv = useRecoilValue(bishengConfState);
  const configured = bishengEnv?.workbench_menu_unavailable_message;
  const trimmed = configured?.trim();
  const message = trimmed || DEFAULT_MESSAGE;
  const [searchParams] = useSearchParams();
  const { user } = useAuthContext();
  const localize = useLocalize();
  const { showToast } = useToastContext();
  const [submitting, setSubmitting] = useState(false);
  const pluginId = searchParams.get('plugin') || '';
  const hasPlugin = Array.isArray((user as { plugins?: string[] } | null)?.plugins)
    && Boolean((user as { plugins?: string[] } | null)?.plugins?.includes(pluginId));
  const menuApprovalMode = Boolean((user as { menu_approval_mode?: boolean } | null)?.menu_approval_mode);
  const canApply = Boolean(pluginId) && menuApprovalMode && !hasPlugin;
  const menuName = pluginId ? localize((MENU_LABEL_KEYS[pluginId] || pluginId) as any) : '';

  const handleApply = async () => {
    if (!canApply || !pluginId) return;
    setSubmitting(true);
    try {
      await applyMenuAccessApi({
        menu_key: pluginId,
        menu_name: menuName || pluginId,
      });
      showToast({
        message: localize('com_menu_unavailable_apply_success'),
        severity: NotificationSeverity.SUCCESS,
      });
    } catch {
      showToast({
        message: localize('com_menu_unavailable_apply_failed'),
        severity: NotificationSeverity.INFO,
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
        {canApply ? localize('com_menu_unavailable_no_permission') : message}
      </p>
      {canApply && (
        <div className="mt-6 flex flex-col items-center gap-3">
          <div className="text-sm text-[#4e5969]">
            {localize('com_menu_unavailable_apply_hint', { menu: menuName || pluginId } as any)}
          </div>
          <button
            type="button"
            disabled={submitting}
            className="rounded-lg bg-[#165dff] px-4 py-2 text-sm text-white transition-colors hover:bg-[#0e42d2] disabled:cursor-not-allowed disabled:opacity-60"
            onClick={() => void handleApply()}
          >
            {localize('com_menu_unavailable_apply_button')}
          </button>
        </div>
      )}
    </div>
  );
}
