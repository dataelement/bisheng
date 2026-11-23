import { LoadingState } from '@/components/bs-icons/loading/LoadingState'
import { userContext } from '@/contexts/userContext'
import {
    getOAuth2ConsentDetails,
    submitOAuth2ConsentDecision,
} from '@/controllers/API/oauth2'
import type { OAuth2ConsentDetails } from '@/types/oauth2'
import { Button } from '@bisheng/ui'
import { Outlined } from 'bisheng-icons'
import { useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

const REQUEST_ID_RE = /^[A-Za-z0-9_-]{1,128}$/

function readRequestId(search: string): string | null {
    const params = new URLSearchParams(search)
    const values = params.getAll('request_id')
    if (values.length !== 1 || !REQUEST_ID_RE.test(values[0])) return null
    return values[0]
}

export function OAuthConsent() {
    const { t } = useTranslation()
    const { user } = useContext(userContext)
    const homeUrl = import.meta.env.BASE_URL
    const requestId = useMemo(() => readRequestId(location.search), [])

    const [details, setDetails] = useState<OAuth2ConsentDetails | null>(null)
    const [status, setStatus] = useState<
        'loading' | 'ready' | 'submitting' | 'invalid' | 'failed'
    >(() => (requestId ? 'loading' : 'invalid'))
    const autoSubmitted = useRef(false)

    const submitDecision = useCallback(
        async (decision: 'approve' | 'deny') => {
            if (!requestId) return
            setStatus('submitting')
            try {
                const res = await submitOAuth2ConsentDecision(
                    requestId,
                    decision,
                )
                location.assign(res.redirect_uri)
            } catch {
                setStatus('failed')
            }
        },
        [requestId],
    )

    useEffect(() => {
        if (!requestId || !user?.user_id) return
        const controller = new AbortController()
        setStatus('loading')
        getOAuth2ConsentDetails(requestId, controller.signal)
            .then((data) => {
                if (controller.signal.aborted) return
                setDetails(data)
                if (!data.require_consent && !autoSubmitted.current) {
                    autoSubmitted.current = true
                    void submitDecision('approve')
                } else {
                    setStatus('ready')
                }
            })
            .catch(() => {
                if (!controller.signal.aborted) setStatus('failed')
            })
        return () => controller.abort()
    }, [requestId, submitDecision, user?.user_id])

    function handleGoLogin() {
        const returnTo = `${location.pathname}${location.search}`
        location.assign(`${homeUrl}?return_to=${encodeURIComponent(returnTo)}`)
    }

    return (
        <main className="flex min-h-screen items-center justify-center bg-background p-4">
            <section className="flex w-full max-w-lg flex-col gap-5 rounded-2xl border bg-background p-6 shadow-sm sm:p-8">
                {!requestId || status === 'invalid' ? (
                    <div className="flex flex-col items-center gap-3 text-center">
                        <h1 className="text-xl font-semibold">
                            {t('oauth2.consent.invalidTitle')}
                        </h1>
                        <p className="text-sm text-muted-foreground">
                            {t('oauth2.consent.invalidDesc')}
                        </p>
                    </div>
                ) : !user?.user_id ? (
                    <div className="flex flex-col items-center gap-4 text-center">
                        <div className="flex h-12 w-12 items-center justify-center rounded-full bg-primary/10 text-primary">
                            <Outlined.PeopleSafe aria-hidden className="h-6 w-6" />
                        </div>
                        <h1 className="text-xl font-semibold">
                            {t('oauth2.consent.loginRequiredTitle')}
                        </h1>
                        <p className="text-sm text-muted-foreground">
                            {t('oauth2.consent.loginRequiredDesc')}
                        </p>
                        <Button className="w-full" onClick={handleGoLogin}>
                            {t('oauth2.consent.signIn')}
                        </Button>
                    </div>
                ) : status === 'loading' || status === 'submitting' ? (
                    <div className="flex flex-col items-center gap-3 py-6">
                        <LoadingState />
                        <p className="text-sm text-muted-foreground">
                            {status === 'submitting'
                                ? t('oauth2.consent.authorizing')
                                : t('oauth2.consent.loading')}
                        </p>
                    </div>
                ) : status === 'failed' || !details ? (
                    <div className="flex flex-col items-center gap-3 text-center">
                        <h1 className="text-xl font-semibold">
                            {t('oauth2.consent.expiredTitle')}
                        </h1>
                        <p className="text-sm text-muted-foreground">
                            {t('oauth2.consent.expiredDesc')}
                        </p>
                    </div>
                ) : (
                    <>
                        <header className="flex flex-col gap-1.5">
                            <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                                {t('oauth2.consent.eyebrow')}
                            </p>
                            <h1 className="text-xl font-semibold tracking-tight">
                                {t('oauth2.consent.heading', {
                                    client: details.client_name,
                                })}
                            </h1>
                            {details.client_description && (
                                <p className="text-sm text-muted-foreground">
                                    {details.client_description}
                                </p>
                            )}
                        </header>

                        <div className="rounded-xl border bg-muted/30 p-4">
                            <p className="mb-2 text-xs font-medium text-muted-foreground">
                                {t('oauth2.consent.accountLabel')}
                            </p>
                            <p className="text-sm font-medium">
                                {user.user_name}
                            </p>
                        </div>

                        <div className="flex flex-col gap-2">
                            <p className="text-sm font-medium">
                                {t('oauth2.consent.scopesTitle')}
                            </p>
                            <ul className="flex flex-col gap-1.5 rounded-xl border p-3 text-sm text-muted-foreground">
                                {details.scopes.map((scope) => (
                                    <li
                                        key={scope}
                                        className="flex items-center gap-2"
                                    >
                                        <Outlined.CheckCircle
                                            aria-hidden
                                            className="h-4 w-4 shrink-0 text-primary"
                                        />
                                        <span>
                                            {t(
                                                `oauth2.scopes.${scope}`,
                                                scope,
                                            )}
                                        </span>
                                    </li>
                                ))}
                            </ul>
                        </div>

                        <div className="flex items-center justify-end gap-3 pt-2">
                            <Button
                                variant="outline"
                                onClick={() => void submitDecision('deny')}
                            >
                                {t('oauth2.consent.deny')}
                            </Button>
                            <Button
                                onClick={() => void submitDecision('approve')}
                            >
                                {t('oauth2.consent.approve')}
                            </Button>
                        </div>
                    </>
                )}
            </section>
        </main>
    )
}
