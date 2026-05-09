import { useGetBsConfig } from '~/hooks/queries/data-provider';

/**
 * 首钢门户专属：在 BiSheng 工作台内嵌 iframe 打开知识门户的后台管理界面。
 * URL 双源——优先 BiSheng "系统配置" YAML 的 shougang.portal_admin_url；
 * 兜底 ConfigMap 注入的 window.__SHOUGANG_PORTAL_ADMIN_URL__。
 */
export default function ShougangPortalAdmin() {
  const { data: bsConfig } = useGetBsConfig();
  const url =
    bsConfig?.shougang?.portal_admin_url
    ?? window.__SHOUGANG_PORTAL_ADMIN_URL__;
  if (!url) return null;
  return (
    <div className="h-full w-full bg-white">
      <iframe
        src={url}
        title="门户配置"
        className="h-full w-full border-0"
      />
    </div>
  );
}
