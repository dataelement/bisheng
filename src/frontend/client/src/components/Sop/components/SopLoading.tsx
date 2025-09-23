import { motion, AnimatePresence } from "framer-motion";
import { useState, useEffect, useMemo } from "react";
import { cn } from "~/utils";
import { useLocalize } from "~/hooks";

// LoadingBox组件
export const LoadingBox = () => {
    const localize = useLocalize();
    return (
        <div className='h-full bg-white border border-[#E8E9ED] rounded-xl flex flex-col justify-center text-center'>
            <div className="lingsi-border-box mx-auto">
                <div className='w-[194px] h-[102px] bg-no-repeat mx-auto rounded-md bg-white'
                    style={{ backgroundImage: `url(${__APP_ENV__.BASE_URL}/assets/linsi-load.png)` }}></div>
            </div>
            <h1 className='text-2xl mt-10'>{localize('com_sop_loading_title')}</h1>
            <p className='mt-5'>{localize('com_sop_loading_desc')}</p>
        </div>
    );
};


interface PlaySopProps {
    content: string[]
    className?: string
}


export const PlaySop = ({ content: _content, className }: PlaySopProps) => {
    const [currentIndex, setCurrentIndex] = useState(0)
    const [isVisible, setIsVisible] = useState(true)
    const content = useMemo(() => _content.split('\n').filter((item) => item.trim() !== ''), [_content])

    useEffect(() => {
        if (!content || content.length === 0) return

        const interval = setInterval(() => {
            setIsVisible(false)

            setTimeout(() => {
                setCurrentIndex((prev) => (prev + 1) % content.length)
                setIsVisible(true)
            }, 500)
        }, 1400)

        return () => clearInterval(interval)
    }, [content])

    if (!content || content.length === 0) return null

    return (
        <div className={cn("relative h-32 shadow-2xl rounded-xl overflow-hidden mt-6", className)}>
            {/* Video Background */}
            <video
                autoPlay
                loop
                muted
                playsInline
                preload="auto"
                className={cn(
                    "absolute size-full object-fill object-center",
                    "transition-opacity duration-500 ease-out",
                )}
            // src={`${__APP_ENV__.BASE_URL}/assets/linsi-bg.mp4`}
            >
                <source
                    src={`${__APP_ENV__.BASE_URL}/assets/linsi-bg.mp4`}
                    type="video/mp4"
                />
                <img
                    src={`${__APP_ENV__.BASE_URL}/assets/lingsi-bg.png`}
                    alt=""
                />
            </video>

            {/* Overlay for better text visibility */}
            {/* <div className="absolute inset-0 bg-black/10" /> */}

            {/* Animated Text Content */}
            <div className="absolute inset-0 flex items-center justify-center">
                <AnimatePresence mode="wait">
                    {isVisible && (
                        <motion.div
                            key={currentIndex}
                            initial={{
                                y: 100,
                                opacity: 0,
                                scale: 0.8,
                            }}
                            animate={{
                                y: 0,
                                opacity: 1,
                                scale: 1,
                            }}
                            exit={{
                                y: -20,
                                opacity: 0,
                                scale: 0.3,
                                filter: "blur(4px)",
                            }}
                            transition={{
                                duration: 0.2,
                                ease: [0.25, 0.46, 0.45, 0.94],
                                exit: {
                                    duration: 0,
                                    ease: [0.55, 0.085, 0.68, 0.53],
                                },
                            }}
                            className="text-center px-4"
                        >
                            <motion.p
                                className="text-#666 text-lg font-medium drop-shadow-lg"
                                initial={{ letterSpacing: "0.1em" }}
                                animate={{ letterSpacing: "0.05em" }}
                                exit={{ letterSpacing: "0.2em" }}
                                transition={{ duration: 0.4 }}
                            >
                                {content[currentIndex]}
                            </motion.p>
                        </motion.div>
                    )}
                </AnimatePresence>
            </div>

            {/* Subtle vignette effect */}
            <div className="absolute inset-0 bg-gradient-radial from-transparent via-transparent to-black/10" />
        </div>
    )
}



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
