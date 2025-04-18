import { useLocalize } from '~/hooks';

export default function HeaderTitle({ conversation }) {
  const localize = useLocalize();

  return (
    <div className="sticky top-0 z-10 flex h-14 w-full items-center justify-center bg-white p-2 font-semibold dark:bg-gray-800 dark:text-white">
      <div className="overflow max-w-2xl pt-3">{conversation?.title || localize('com_ui_new_chat')}</div>
    </div>
  );
}
