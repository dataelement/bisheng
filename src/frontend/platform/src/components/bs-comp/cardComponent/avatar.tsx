import { AssistantIcon, FlowIcon, SkillIcon } from "@/components/bs-icons";
import { AppNumType } from "@/types/app";
import { cn } from "@/utils";
import { useMemo } from "react";

const gradients = [
    'bg-amber-500',
    'bg-orange-600',
    'bg-teal-500',
    'bg-purple-600',
    'bg-blue-700'
]

export default function AppAvator({ id = 1, flowType = '', url = '', className = '' }) {

    const color = useMemo(() => {
        const str = (id + '').substring(0, 4)
        let hex = '';
        for (let i = 0; i < str.length; i++) {
            hex += str.charCodeAt(i).toString(16);
        }
        const num = parseInt(hex, 16) || 0;
        return gradients[parseInt(num + '', 16) % gradients.length]
    }, [id])

    if (url) return <img src={__APP_ENV__.BASE_URL + url} className={cn(`w-6 h-6 rounded-sm object-cover`, className)} />

    const flowIcons = {
        [AppNumType.SKILL]: <SkillIcon className="" />,
        [AppNumType.ASSISTANT]: <AssistantIcon className="" />,
        [AppNumType.FLOW]: <FlowIcon className="" />
    }

    return <div className={cn(`size-6 min-w-6 p-0.5 rounded-sm flex justify-center items-center`, color, className)}>
        {flowIcons[flowType] || <FlowIcon className="" />}
    </div>
};
