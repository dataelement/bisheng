// src/features/chat-config/components/ToggleSection.tsx
import { Switch } from "@/components/bs-ui/switch";
import { ReactNode } from "react";

export const ToggleSection = ({
    title,
    enabled,
    onToggle,
    children,
    extra 
}: {
    title: string;
    enabled: boolean;
    onToggle: (enabled: boolean) => void;
    children: ReactNode;
     extra?: ReactNode; // 设为可选prop
}) => (
     <div className="mb-6">
        <div className="flex items-center mb-2">
            <p className="text-lg font-bold flex items-center">
                <span>{title}</span>
            </p>
            <div className="flex items-center gap-2 ml-2">
               
                <Switch checked={enabled} onCheckedChange={onToggle} />
                 {extra} {/* 在这里渲染extra内容 */}
            </div>
        </div>
        {enabled && children}
    </div>
);