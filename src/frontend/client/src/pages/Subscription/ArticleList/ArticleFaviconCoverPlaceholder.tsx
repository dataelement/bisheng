import { cn } from "~/utils";

export interface ArticleFaviconCoverPlaceholderProps {
    /** 网站 / 信源 icon地址，两层共用 */
    iconUrl?: string | null;
    alt?: string;
    /** 外层容器 class，默认 88×88 与列表封面一致 */
    className?: string;
}

/**
 * 无文章配图时：底层为放大铺满并模糊的同一 icon，上层居中 40×40 清晰 icon。
 */
export function ArticleFaviconCoverPlaceholder({
    iconUrl,
    alt = "",
    className,
}: ArticleFaviconCoverPlaceholderProps) {
    const frame = cn(
        "relative size-[88px] shrink-0 overflow-hidden rounded-sm",
        className
    );

    if (!iconUrl?.trim()) {
        return (
            <div
                className={cn(
                    frame,
                    "bg-[#F7F7F7] ring-1 ring-inset ring-[#E0E0E0]"
                )}
                aria-hidden
            />
        );
    }

    return (
        <div className={frame}>
            <img
                src={iconUrl}
                alt=""
                className="absolute left-1/2 top-1/2 min-h-full min-w-full -translate-x-1/2 -translate-y-1/2 scale-[1.35] object-cover blur-md transition-transform duration-300 ease-in-out fine-pointer:group-hover:scale-[1.45]"
                aria-hidden
                decoding="async"
            />
            <div className="relative z-10 flex h-full w-full items-center justify-center">
                <img
                    src={iconUrl}
                    alt={alt}
                    width={40}
                    height={40}
                    className="size-10 object-contain transition-transform duration-300 ease-in-out fine-pointer:group-hover:scale-105"
                    decoding="async"
                />
            </div>
        </div>
    );
}
