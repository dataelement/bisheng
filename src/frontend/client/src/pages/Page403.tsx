"use client"

export default function Page403() {
    return (
        <div className="min-h-screen flex items-center justify-center px-4 bg-background">
            <div className="max-w-2xl w-full text-center space-y-8">
                <div className="space-y-4">
                    <h1 className="text-[clamp(6rem,20vw,12rem)] font-bold leading-none tracking-tighter text-foreground/10">
                        403
                    </h1>
                    <div className="-mt-12 space-y-3">
                        <h2 className="text-3xl touch-desktop:text-4xl font-semibold tracking-tight text-balance">Access Denied</h2>
                        <p className="text-base touch-desktop:text-lg text-muted-foreground max-w-md mx-auto text-pretty leading-relaxed">
                            You do not have permission to access this resource. Please contact your administrator.
                        </p>
                    </div>
                </div>

                <div className="pt-8 opacity-40">
                    <div className="flex items-center justify-center gap-2 text-sm text-muted-foreground">
                        <div className="h-px w-12 bg-border" />
                        <div className="h-px w-12 bg-border" />
                    </div>
                </div>
            </div>
        </div>
    )
}
