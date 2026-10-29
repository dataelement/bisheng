// @ts-strict-ignore
import { Boxes } from "lucide-react";
import { useMemo } from "react";
import { cn } from "~/utils"
import { AssistantIcon } from "~/components/ui/icon/AssistantIcon";
import { SkillIcon } from "~/components/ui/icon/SkillIcon";
import { WorkflowIcon } from "~/components/ui/icon/WorkflowIcon";

const gradients = [
    'bg-amber-500',
    'bg-orange-600',
    'bg-teal-500',
    'bg-purple-600',
    'bg-blue-700'
]

export default function AppAvator({ id = 1, flowType = '', url = '', className = '', iconClassName = 'w-4 h-4' }) {

    const color = useMemo(() => {
        const str = id + ''
        let hex = '';
        for (let i = 0; i < str.length; i++) {
            hex += str.charCodeAt(i).toString(16);
        }
        const num = parseInt(hex, 16) || 0;
        return gradients[parseInt(num + '', 16) % gradients.length]
    }, [id])

    if (url) return <img src={__APP_ENV__.BASE_URL + url} className={cn(`size-6 rounded-sm object-cover`, className)} />

    const flowConfig: Record<number, { icon: React.ReactNode, bgColor: string }> = {
        1: {
            icon: <SkillIcon style={{ color: '#722ED1' }} className={iconClassName} />,
            bgColor: '#F5E8FF'
        },
        5: {
            icon: <AssistantIcon style={{ color: '#FF7D00' }} className={iconClassName} />,
            bgColor: '#FFF7E8'
        },
        10: {
            icon: <WorkflowIcon className={cn(iconClassName, "text-primary")} />,
            bgColor: 'rgb(var(--brand-50))'
        },
        // F054 hosted application. Same Boxes glyph the platform build page
        // uses, so one application wears one icon on both sides. Without this
        // entry the fallback below renders it as an assistant — a wrong icon,
        // never an error.
        35: {
            icon: <Boxes style={{ color: '#00B42A' }} className={iconClassName} />,
            bgColor: '#E8FFEA'
        }
    }

    const currentConfig = flowConfig[flowType as number] || flowConfig[5]; // Default to assistant if not found

    return (
        <div
            className={cn(`size-5 min-w-5 rounded-md flex justify-center items-center`, className)}
            style={{ backgroundColor: currentConfig.bgColor }}
        >
            {currentConfig.icon}
        </div>
    );
};
