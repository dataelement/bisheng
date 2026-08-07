import { LoadingIcon } from "@/components/bs-icons/loading"
import { Suspense } from "react"
import { Outlet } from "react-router-dom"

/**
 * Chrome-less layout for `/standalone/*` routes: full viewport, no sidebar and
 * no header, so the page can be embedded into another product via iframe.
 * Keeps the same content background/rounding as the platform content area.
 */
export default function StandaloneLayout() {
    return (
        <div className="h-screen w-screen overflow-hidden bg-background-main-content">
            <Suspense
                fallback={
                    <div className="flex h-full items-center justify-center">
                        <LoadingIcon />
                    </div>
                }
            >
                <Outlet />
            </Suspense>
        </div>
    )
}
