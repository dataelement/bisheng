interface SeparatorProps {
    className?: string;
    text: string;
}

const dashedLineClassName = "h-px flex-1 bg-[repeating-linear-gradient(to_right,currentColor_0_3px,transparent_3px_7px)]";

export function Separator({ className = "", text }: SeparatorProps) {
    return (
        <div className={`flex w-full items-center gap-3 py-4 text-body text-text-3 ${className}`}>
            <span aria-hidden="true" className={dashedLineClassName} />
            <span className="min-w-0 text-center">{text}</span>
            <span aria-hidden="true" className={`${dashedLineClassName} -scale-x-100`} />
        </div>
    );
}
