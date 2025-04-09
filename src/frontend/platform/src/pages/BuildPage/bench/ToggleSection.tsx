// src/features/chat-config/components/ToggleSection.tsx
import { Switch } from "@/components/bs-ui/switch";
import { ReactNode } from "react";

export const ToggleSection = ({
    title,
    enabled,
    onToggle,
    children,
}: {
    title: string;
    enabled: boolean;
    onToggle: (enabled: boolean) => void;
    children: ReactNode;
}) => (
    <div className="mb-6">
        <p className="text-lg font-bold mb-2">
            <span>{title}</span>
            <Switch className="ml-4" checked={enabled} onCheckedChange={onToggle} />
        </p>
        {enabled && children}
    </div>
);