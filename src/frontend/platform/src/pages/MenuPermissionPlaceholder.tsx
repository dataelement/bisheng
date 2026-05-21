/** 需审批模式：无菜单权限时占位空白页（管理后台侧栏可点入但无内容） */
export default function MenuPermissionPlaceholder() {
  return (
    <div className="flex h-full w-full items-center justify-center bg-background-main-content px-6">
      <div className="max-w-md rounded-xl border border-border-subtle bg-background-primary p-8 text-center shadow-sm">
        <h2 className="text-lg font-semibold text-text-primary">当前菜单需审批开通</h2>
        <p className="mt-3 text-sm leading-6 text-text-secondary">
          你的角色当前未包含该菜单权限。若租户已开启菜单审批模式，请通过工作台发起菜单权限申请。
        </p>
      </div>
    </div>
  );
}
