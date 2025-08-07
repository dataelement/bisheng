import { cn } from "~/utils";

// LoadingBox组件
export const LoadingBox = () => {
    return (
        <div className='h-full bg-white border border-[#E8E9ED] rounded-xl flex flex-col justify-center text-center'>
            <div className="lingsi-border-box mx-auto">
                <div className='w-[194px] h-[102px] bg-no-repeat mx-auto rounded-md bg-white'
                    style={{ backgroundImage: `url(${__APP_ENV__.BASE_URL}/assets/linsi-load.png)` }}></div>
            </div>
            <h1 className='text-2xl mt-10'>为您提供详细 SOP，以确保任务精准</h1>
            <p className='mt-5'>灵思正在为您规划 SOP...</p>
        </div>
    );
};


interface LoadingDotsProps {
    className?: string
    size?: "sm" | "md" | "lg"
}

export function LoadingDots({ className, size = "md" }: LoadingDotsProps) {
    const sizeClasses = {
        sm: "w-1 h-1",
        md: "w-2 h-2",
        lg: "w-3 h-3",
    }

    const gapClasses = {
        sm: "gap-1",
        md: "gap-2",
        lg: "gap-3",
    }

    return (
        <div className={cn("flex items-center m-4", gapClasses[size], className)}>
            <div
                className={cn("rounded-full bg-black animate-pulse", sizeClasses[size])}
                style={{
                    animation: "loadingDots 1.5s ease-in-out infinite",
                    animationDelay: "0s",
                }}
            />
            <div
                className={cn("rounded-full bg-black animate-pulse", sizeClasses[size])}
                style={{
                    animation: "loadingDots 1.5s ease-in-out infinite",
                    animationDelay: "0.3s",
                }}
            />
            <div
                className={cn("rounded-full bg-black animate-pulse", sizeClasses[size])}
                style={{
                    animation: "loadingDots 1.5s ease-in-out infinite",
                    animationDelay: "0.6s",
                }}
            />
        </div>
    )
}
