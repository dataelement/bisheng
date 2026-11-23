import { Boxes } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "~/utils"
import { AssistantIcon } from "~/components/ui/icon/AssistantIcon";
import { SkillIcon } from "~/components/ui/icon/SkillIcon";
import { WorkflowIcon } from "~/components/ui/icon/WorkflowIcon";

interface AppAvatorProps {
    id?: string | number;
    flowType?: string | number;
    url?: string;
    className?: string;
    iconClassName?: string;
}

export default function AppAvator({ flowType = '', url = '', className = '', iconClassName = 'w-4 h-4' }: AppAvatorProps) {
    if (url) return <img src={__APP_ENV__.BASE_URL + url} className={cn(`size-6 rounded-sm object-cover`, className)} />

    const flowConfig: Record<number, { icon: ReactNode, colorClassName: string }> = {
        1: {
            icon: <SkillIcon className={iconClassName} />,
            colorClassName: 'bg-tag-skill-tint text-tag-skill'
        },
        5: {
            icon: <AssistantIcon className={iconClassName} />,
            colorClassName: 'bg-warning-tint text-warning'
        },
        10: {
            icon: <WorkflowIcon className={iconClassName} />,
            colorClassName: 'bg-blue-50 text-blue-main'
        },
        // F054 hosted application. Same Boxes glyph the platform build page
        // uses, so one application wears one icon on both sides. Without this
        // entry the fallback below renders it as an assistant — a wrong icon,
        // never an error.
        35: {
            icon: <Boxes className={iconClassName} />,
            colorClassName: 'bg-success-tint text-success'
        }
    }

    const currentConfig = flowConfig[flowType as number] || flowConfig[5]; // Default to assistant if not found

    return (
        <div
            className={cn("size-5 min-w-5 rounded-md flex justify-center items-center", currentConfig.colorClassName, className)}
        >
            {currentConfig.icon}
        </div>
    );
};
