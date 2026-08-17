// @ts-strict-ignore
import { AssistantIcon, FlowIcon } from "@/components/bs-icons";
import { AppNumType } from "@/types/app";
import { cn } from "@/utils";
import { Boxes } from "lucide-react";
import { useMemo } from "react";

const gradients = [
    'bg-amber-500',
    'bg-orange-600',
    'bg-teal-500',
    'bg-purple-600',
    'bg-blue-700'
]

interface AppAvatorProps {
    /** Seeds the fallback background colour; callers pass an id or a name. */
    id?: string | number
    /** `AppNumType` value of the row. */
    flowType?: string | number
    url?: string
    className?: string
}

export default function AppAvator({ id = 1, flowType = '', url = '', className = '' }: AppAvatorProps) {

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
        [AppNumType.ASSISTANT]: <AssistantIcon className="" />,
        [AppNumType.FLOW]: <FlowIcon className="" />,
        // F054 hosted application. Third branch only — the two above keep
        // their icon and their pixel size exactly as they are.
        [AppNumType.HOSTED_APP]: <Boxes className="size-4 text-white" />
    }

    return <div className={cn(`size-6 min-w-6 p-0.5 rounded-sm flex justify-center items-center`, color, className)}>
        {flowIcons[flowType] || <FlowIcon className="" />}
    </div>
};
