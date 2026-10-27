import { Outlined } from 'bisheng-icons';
import { emitAreaTextEvent, EVENT_TYPE } from '../useAreaText';
import { useLocalize } from '~/hooks';
import { formatStrTime } from '~/utils';
interface ClientUserActionsProps {
    text: string;
    canResend: boolean;
    searchUrl?: string;
    createTime?: string;
}
export function ClientUserActions({ text, canResend, searchUrl, createTime }: ClientUserActionsProps) {
    const localize = useLocalize();
    const handleResend = (send: boolean) => emitAreaTextEvent({ action: EVENT_TYPE.RE_ENTER, autoSend: send, text });
    return <div className="flex justify-end mt-2 opacity-0 group-hover:opacity-100 transition-opacity gap-2">
        {createTime && <span className="text-slate-400 text-sm pt-0.5">{formatStrTime(createTime, localize('shared:app_chat.timestamp_format'))}</span>}
        <div className="flex gap-0.5 text-gray-400 cursor-pointer self-end">
            {canResend && <Outlined.Edit className="size-6 p-1 hover:text-gray-500" onClick={() => handleResend(false)} />}
            {canResend && <Outlined.Refresh className="size-6 p-1 hover:text-gray-500" onClick={() => handleResend(true)} />}
            {searchUrl && <Outlined.Search className="size-6 p-1 hover:text-gray-500" onClick={() => window.open(searchUrl + encodeURIComponent(text))} />}
        </div>
    </div>;
}
