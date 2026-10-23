import { useTranslation } from "react-i18next";

export default function Page404() {
    const { t } = useTranslation("bs");
    return (
        <div className="min-h-screen flex items-center justify-center px-4 bg-background">
            <div className="max-w-2xl w-full text-center space-y-8">
                {/* 404 Number */}
                <div className="space-y-4">
                    <h1 className="text-[clamp(6rem,20vw,12rem)] font-bold leading-none tracking-tighter text-foreground/10">
                        404
                    </h1>
                    <div className="-mt-12 space-y-3">
                        <h2 className="text-3xl md:text-4xl font-semibold tracking-tight text-balance">
                            {t("publicPages.notFoundTitle")}
                        </h2>
                        <p className="text-base md:text-lg text-muted-foreground max-w-md mx-auto text-pretty leading-relaxed">
                            {t("publicPages.notFoundDescription")}
                        </p>
                    </div>
                </div>

                {/* Action Buttons */}
                {}

                {/* Decorative Element */}
                <div className="pt-8 opacity-40">
                    <div className="flex items-center justify-center gap-2 text-sm text-muted-foreground">
                        <div className="h-px w-12 bg-border" />
                        {}
                        <div className="h-px w-12 bg-border" />
                    </div>
                </div>
            </div>
        </div>
    );
}
