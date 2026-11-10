import { useAuthContext } from '~/hooks/AuthContext';
import useLocalize from '~/hooks/useLocalize';
import { canShowPlatformAdminEntry } from '~/utils/platformAccess';
import { getPlatformAdminPanelUrl } from '~/utils/platformAdminUrl';

type NoticeUser = {
  role?: string | null;
  plugins?: string[] | null;
  is_department_admin?: boolean | null;
  has_admin_console?: boolean | null;
};

/**
 * Explains why the composer is disabled when the tenant has no workbench model.
 *
 * Without it the input simply looks broken: typing is ignored because the daily
 * chat has no model to send to (`bsConfig.models` empty — the list lives in
 * 模型管理 → 工作台模型, not in the model registry). End users cannot fix this
 * themselves, so they get "ask an administrator"; admins get a direct link.
 */
export function WorkbenchModelsNotice() {
  const t = useLocalize();
  const { user } = useAuthContext();
  const accessUser = user as NoticeUser | null;
  const canConfigure = canShowPlatformAdminEntry(
    accessUser
      ? {
          role: accessUser.role,
          plugins: accessUser.plugins,
          is_department_admin: accessUser.is_department_admin,
          has_admin_console: accessUser.has_admin_console,
        }
      : null,
  );

  return (
    <div
      role="status"
      className="mb-2 flex flex-wrap items-center justify-center gap-x-1.5 gap-y-1 rounded-lg bg-warning-tint px-3 py-2 text-center text-body-sm text-warning"
    >
      <span>{t('com_workbench_no_models')}</span>
      {canConfigure ? (
        <a
          href={getPlatformAdminPanelUrl()}
          target="_blank"
          rel="noreferrer"
          className="font-medium underline underline-offset-2"
        >
          {t('com_workbench_no_models_action')}
        </a>
      ) : (
        <span>{t('com_workbench_no_models_contact_admin')}</span>
      )}
    </div>
  );
}
