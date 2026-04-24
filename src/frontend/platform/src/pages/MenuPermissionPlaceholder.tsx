/** 需审批模式：无菜单权限时占位空白页（管理后台侧栏可点入但无内容） */
export default function MenuPermissionPlaceholder() {
  return <div className="h-full w-full bg-background-main-content" aria-hidden />;
}
