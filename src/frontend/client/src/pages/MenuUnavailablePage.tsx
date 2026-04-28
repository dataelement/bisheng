import { WorkbenchEmptyIllustration } from '~/components/workbench/WorkbenchEmptyIllustration';
import { bishengConfState } from '~/pages/appChat/store/atoms';
import { useRecoilValue } from 'recoil';

/** Default hint when YAML `env.workbench_menu_unavailable_message` is unset — plain text only (no link). */
const DEFAULT_MESSAGE =
  '暂无使用过的应用，可以前往应用广场探索更多应用';

/** 需审批模式：无对应工作台菜单权限时的占位页（插画 + 管理员可配置的纯文案） */
export default function MenuUnavailablePage() {
  const bishengEnv = useRecoilValue(bishengConfState);
  const configured = bishengEnv?.workbench_menu_unavailable_message;
  const trimmed = configured?.trim();
  const message = trimmed || DEFAULT_MESSAGE;

  return (
    <div className="flex h-full min-h-[320px] w-full flex-1 flex-col items-center justify-center bg-white px-6 py-12">
      <div className="mb-6 opacity-80">
        <WorkbenchEmptyIllustration />
      </div>
      <p className="max-w-xl text-center text-sm leading-relaxed text-gray-500" role="status">
        {message}
      </p>
    </div>
  );
}
