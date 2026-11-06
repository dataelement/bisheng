import { Button, Tooltip } from "@bisheng/ui";
import { Outlined } from "bisheng-icons";
import type { ReactElement, ReactNode } from "react";
interface QuestionHintProps {
    content: ReactNode;
    error?: boolean;
    className?: string;
    children?: ReactElement | null;
}
export function QuestionHint({ content, error = false, className, children }: QuestionHintProps) {
    return (
        <Tooltip content={content}>
            {children ?? (
                <Button
                    type="button"
                    variant="text"
                    color={error ? "danger" : "default"}
                    size="small"
                    iconOnly
                    className={className}
                    aria-label={typeof content === "string" ? content : undefined}
                >
                    <Outlined.Question />
                </Button>
            )}
        </Tooltip>
    );
}
