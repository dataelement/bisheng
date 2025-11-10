"use client"

import { ArrowLeft, Home } from "lucide-react"

export default function Page404() {
    return (
        <div className="min-h-screen flex items-center justify-center px-4 bg-background">
            <div className="max-w-2xl w-full text-center space-y-8">
                {/* 404 Number */}
                <div className="space-y-4">
                    <h1 className="text-[clamp(6rem,20vw,12rem)] font-bold leading-none tracking-tighter text-foreground/10">
                        404
                    </h1>
                    <div className="-mt-12 space-y-3">
                        <h2 className="text-3xl md:text-4xl font-semibold tracking-tight text-balance">Page Not Found</h2>
                        <p className="text-base md:text-lg text-muted-foreground max-w-md mx-auto text-pretty leading-relaxed">
                            Sorry, the page you are trying to access does not exist or has been removed
                        </p>
                    </div>
                </div>

                {/* Action Buttons */}
                {/* <div className="flex flex-col sm:flex-row items-center justify-center gap-3 pt-4">
                    <Button asChild size="lg" className="w-full sm:w-auto gap-2">
                        <a href="/">
                            <Home className="h-4 w-4" />
                            返回首页
                        </a>
                    </Button>
                    <Button
                        asChild
                        variant="outline"
                        size="lg"
                        className="w-full sm:w-auto gap-2 bg-transparent"
                        onClick={() => window.history.back()}
                    >
                        <button type="button">
                            <ArrowLeft className="h-4 w-4" />
                            返回上一页
                        </button>
                    </Button>
                </div> */}

                {/* Decorative Element */}
                <div className="pt-8 opacity-40">
                    <div className="flex items-center justify-center gap-2 text-sm text-muted-foreground">
                        <div className="h-px w-12 bg-border" />
                        {/* <span>或许您在寻找其他内容</span> */}
                        <div className="h-px w-12 bg-border" />
                    </div>
                </div>
            </div>
        </div>
    )
}
