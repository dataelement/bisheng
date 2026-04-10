import { useId } from "react";

/** 知识空间 / 订阅侧栏列表项左侧笔记本图标（与知识空间侧栏一致） */
export function SpaceNotebookIcon({ active }: { active: boolean }) {
    const clipId = `nb-${useId().replace(/:/g, "")}`;
    return (
        <svg
            width={14}
            height={14}
            viewBox="0 0 16 16"
            fill="none"
            xmlns="http://www.w3.org/2000/svg"
            className={`size-3.5 shrink-0 ${active ? "text-[#165DFF]" : "text-[#818181]"}`}
            aria-hidden
        >
            <g clipPath={`url(#${clipId})`}>
                <path d="M16 0H0V16H16V0Z" fill="white" fillOpacity={0.01} />
                <path
                    d="M2.66699 1.99998C2.66699 1.63179 2.96547 1.33331 3.33366 1.33331H12.667C13.0352 1.33331 13.3337 1.63179 13.3337 1.99998V14C13.3337 14.3682 13.0352 14.6666 12.667 14.6666H3.33366C2.96547 14.6666 2.66699 14.3682 2.66699 14V1.99998Z"
                    stroke="currentColor"
                    strokeWidth={1.33333}
                    strokeLinejoin="round"
                />
                <path
                    d="M5.33301 1.33331V14.6666"
                    stroke="currentColor"
                    strokeWidth={1.33333}
                    strokeLinecap="round"
                    strokeLinejoin="round"
                />
                <path d="M8 4H10.6667" stroke="currentColor" strokeWidth={1.33333} strokeLinecap="round" strokeLinejoin="round" />
                <path
                    d="M8 6.66669H10.6667"
                    stroke="currentColor"
                    strokeWidth={1.33333}
                    strokeLinecap="round"
                    strokeLinejoin="round"
                />
                <path
                    d="M3.33301 1.33331H7.33301"
                    stroke="currentColor"
                    strokeWidth={1.33333}
                    strokeLinecap="round"
                    strokeLinejoin="round"
                />
                <path
                    d="M3.33301 14.6667H7.33301"
                    stroke="currentColor"
                    strokeWidth={1.33333}
                    strokeLinecap="round"
                    strokeLinejoin="round"
                />
            </g>
            <defs>
                <clipPath id={clipId}>
                    <rect width={16} height={16} fill="white" />
                </clipPath>
            </defs>
        </svg>
    );
}
