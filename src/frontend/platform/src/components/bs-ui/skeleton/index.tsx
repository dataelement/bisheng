import { cname } from "../utils";

export default function Skeleton({
    className,
    ...props
}: React.HTMLAttributes<HTMLDivElement>) {

    return (
        <div
            className={cname("animate-pulse rounded-md bg-primary/10", className)}
            {...props}
        />
    )
};
