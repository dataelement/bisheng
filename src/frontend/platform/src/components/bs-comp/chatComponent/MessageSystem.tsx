// @ts-strict-ignore
import { toast } from '@bisheng/ui';

import MessageMarkDown from "@/pages/BuildPage/flow/FlowChat/MessageMarkDown";
import { copyText } from "@/utils";
import { Outlined } from "bisheng-icons";

import { useMemo } from "react";
import { useTranslation } from "react-i18next";

export default function MessageSystem({ data }) {

    const { t } = useTranslation()

    const handleCopy = (dom) => {
        copyText(dom)

        toast.show({ type: 'success', message: [String(t('prompt') ?? ''), String(t('chat.copyTip') ?? '')].filter(Boolean).join('\n') })
    }

    // 日志markdown
    const logMkdown = useMemo(
        () => (
            data.thought && <MessageMarkDown message={data.thought.toString()} />
        ),
        [data.thought]
    )

    const border = { system: 'border-slate-500', question: 'border-amber-500', processing: 'border-cyan-600', answer: 'border-lime-600', report: 'border-slate-500', guide: 'border-none' }

    return <div className="py-1">
        <div className={`relative rounded-sm px-6 py-4 border text-sm dark:bg-gray-900 ${data.category === 'guide' ? 'bg-[#EDEFF6]' : 'bg-slate-50'} ${border[data.category || 'system']}`}>
            {logMkdown}
            {data.category === 'report' && <Outlined.Copy className=" absolute right-4 top-2 cursor-pointer" onClick={(e) => handleCopy(e.target.parentNode)}></Outlined.Copy>}
        </div>
    </div>
};
