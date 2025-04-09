import { useEffect, useRef } from "react";

export default function LoadMore({ onScrollLoad }) {
    // scroll load
    const footerRef = useRef<HTMLDivElement>(null)
    useEffect(function () {
        const observer = new IntersectionObserver((entries) => {
            entries.forEach(entry => {
                if (entry.isIntersecting) {
                    onScrollLoad()
                }
            });
        }, {
            // root: null, // 视口
            rootMargin: '0px', // 视口的边距
            threshold: 0.1 // 目标元素超过视口的10%即触发回调
        });

        observer.observe(footerRef.current);
        return () => footerRef.current && observer.unobserve(footerRef.current);
    }, [])

    return <div ref={footerRef} style={{ height: 20 }}></div>
};
