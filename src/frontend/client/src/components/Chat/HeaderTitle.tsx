import { useLocalize } from '~/hooks';
import ShareChat from '../Share/ShareChat';

const types = {
  1: 'skill',
  5: 'assistant',
  10: 'workflow',
  15: 'workbench_chat'
}
export default function HeaderTitle({ conversation, logo, readOnly }) {
  const localize = useLocalize();

  return (
    <div className="sticky top-0 z-10 flex h-14 w-full items-center justify-center bg-white p-2 gap-2 font-semibold dark:bg-gray-800 dark:text-white ">
      {logo}
      <div id="app-title" className="overflow max-w-2xl truncate">{conversation?.title || localize('com_ui_new_chat')}</div>
      <div className='absolute right-2'>
        {!readOnly && <ShareChat type={types[conversation?.flowType]} flowId={conversation?.flowId} chatId={conversation?.conversationId || ''} />}
      </div>
    </div>
  );
}
