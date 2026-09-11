import { UserPopMenu } from "~/layouts/UserPopMenu";

/**
 * 会话历史抽屉底部：与 PC 左侧栏一致的用户菜单（消息提醒 / 语言 / 退出）
 */
export function ChatNavUserFooter() {
    return (
        <div className="shrink-0 border-t border-[#ececec] pt-3 pb-1 mt-2 -mx-1 px-1 touch-mobile:mx-0 touch-mobile:px-0">
            <UserPopMenu variant="drawer" />
        </div>
    );
}
