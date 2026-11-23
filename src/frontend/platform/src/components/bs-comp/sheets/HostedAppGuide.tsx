import { Alert, Button } from "@bisheng/ui";
import { useTranslation } from "react-i18next";

const TUTORIAL_PATH = "/tutorial/hosted-app.html";
const STEP_KEYS = ["step1", "step2", "step3", "step4", "step5"] as const;

interface HostedAppGuideProps {
    /** Whether the app-factory runtime layer is deployed here (`appConfig.appRuntimeEnabled`). */
    runtimeEnabled: boolean;
}

/**
 * Right-hand panel of the template sheet when "hosted app" is selected
 * (v3.1.0-alpha1 F001). Hosted apps have no templates: they are written locally
 * with an AI coding tool and deployed with a platform key, so the panel explains
 * that path and links the platform's own tutorial instead of listing cards.
 */
export function HostedAppGuide({ runtimeEnabled }: HostedAppGuideProps) {
    const { t } = useTranslation("flow");

    return (
        <section className="flex w-full max-w-[640px] flex-col gap-4" aria-label={t("hostedApp")}>
            {!runtimeEnabled && <Alert type="warning" description={t("hostedApp.guide.descDisabled", { ns: "bs" })} />}
            <div className="flex flex-col gap-2">
                <h3 className="text-base font-medium">{t("hostedApp")}</h3>
                <p className="text-sm leading-relaxed text-muted-foreground">{t("hostedAppGuide.intro")}</p>
            </div>
            <div className="rounded-lg bg-muted px-4 py-3">
                <h4 className="text-sm font-medium">{t("hostedAppGuide.differenceTitle")}</h4>
                <p className="mt-1 text-sm leading-relaxed text-muted-foreground">{t("hostedAppGuide.differenceBody")}</p>
            </div>
            <div className="rounded-lg bg-muted px-4 py-3">
                <h4 className="text-sm font-medium">{t("hostedAppGuide.prepareTitle")}</h4>
                <p className="mt-1 text-sm leading-relaxed text-muted-foreground">{t("hostedAppGuide.prepareBody")}</p>
            </div>
            <div className="rounded-lg bg-muted px-4 py-3">
                <h4 className="text-sm font-medium">{t("hostedAppGuide.stepsTitle")}</h4>
                <ol className="mt-1 list-decimal pl-5 text-sm leading-relaxed text-muted-foreground">
                    {STEP_KEYS.map((key) => (
                        <li key={key}>{t(`hostedAppGuide.${key}`)}</li>
                    ))}
                </ol>
            </div>
            <div>
                <Button onClick={() => window.open(TUTORIAL_PATH, "_blank", "noopener")}>{t("viewTutorial")}</Button>
            </div>
        </section>
    );
}
