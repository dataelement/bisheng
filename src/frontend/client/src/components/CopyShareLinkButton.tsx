import type { MouseEventHandler } from "react";
import type { ButtonProps } from "~/components/ui/Button";
import { Button } from "~/components/ui/Button";
import { ShareOutlineIcon } from "~/components/icons";
import { useLocalize } from "~/hooks";
import { useToastContext } from "~/Providers";
import { cn, copyText } from "~/utils";

export function buildClientShareUrl(path: string) {
    if (typeof window === "undefined") return "";
    const base = window.location.origin + (__APP_ENV__.BASE_URL || "");
    const normalizedBase = base.endsWith("/") ? base.slice(0, -1) : base;
    const normalizedPath = path.startsWith("/") ? path : `/${path}`;
    return `${normalizedBase}${normalizedPath}`;
}

interface CopyShareLinkButtonProps extends Omit<ButtonProps, "onClick"> {
    sharePath: string;
    label?: string;
    successMessage?: string;
    errorMessage?: string;
    iconClassName?: string;
    onClick?: MouseEventHandler<HTMLButtonElement>;
}

export function CopyShareLinkButton({
    sharePath,
    label,
    successMessage,
    errorMessage,
    iconClassName,
    className,
    children,
    disabled,
    onClick,
    variant = "ghost",
    ...props
}: CopyShareLinkButtonProps) {
    const localize = useLocalize();
    const { showToast } = useToastContext();
    const shareLink = buildClientShareUrl(sharePath);

    const handleClick: MouseEventHandler<HTMLButtonElement> = async (event) => {
        onClick?.(event);
        if (event.defaultPrevented) return;

        try {
            await copyText(shareLink);
            showToast({
                message: successMessage || localize("com_knowledge.share_link_copied"),
                status: "success",
            });
        } catch {
            showToast({
                message: errorMessage || localize("com_knowledge.copy_failed_retry"),
                status: "error",
            });
        }
    };

    return (
        <Button
            {...props}
            type={props.type || "button"}
            variant={variant}
            disabled={disabled || !shareLink}
            onClick={handleClick}
            className={cn(
                "h-8 gap-1 px-4 font-normal transition-colors hover:bg-[#F7F8FA] touch-mobile:rounded-[6px] touch-mobile:border touch-mobile:border-[#EBECF0] touch-mobile:bg-white touch-mobile:px-4 touch-mobile:text-[#212121]",
                className,
            )}
        >
            <ShareOutlineIcon className={cn("size-4 shrink-0 text-gray-800", iconClassName)} />
            {children || label || localize("com_knowledge.share")}
        </Button>
    );
}
