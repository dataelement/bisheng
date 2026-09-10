import { Button } from '@/components/bs-ui/button'
import { Input } from '@/components/bs-ui/input'
import { userContext } from '@/contexts/userContext'
import { useDshBrowserConfig } from '@/hooks/useDshBrowserConfig'
import { rememberDesktopLoginReturnTo } from '@/utils/loginReturnTo'
import { useContext, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
    callbackUrl,
    readAuthId,
    useDshAuthorization,
} from './useDshAuthorization'

export function DshLogin() {
    const { t } = useTranslation()
    const { user } = useContext(userContext)
    const { config, failed } = useDshBrowserConfig()
    const [copied, setCopied] = useState(false)
    useEffect(() => {
        const previous = document.title
        document.title = t('dsh.title')
        return () => {
            document.title = previous
        }
    }, [t])
    let authId: string | null = null
    let invalid = false
    try {
        authId = readAuthId(location.search)
    } catch {
        invalid = true
    }
    const flow = useDshAuthorization(authId)
    useEffect(() => {
        const meta = document.createElement('meta')
        meta.name = 'referrer'
        meta.content = 'no-referrer'
        document.head.appendChild(meta)
        return () => {
            meta.remove()
        }
    }, [])
    function handleLogin() {
        rememberDesktopLoginReturnTo()
        location.assign(import.meta.env.BASE_URL)
    }
    async function handleCopy(value: string) {
        try {
            await navigator.clipboard.writeText(value)
            setCopied(true)
        } catch {
            setCopied(false)
        }
    }
    const tenantName = user?.leaf_tenant_name?.trim() || user?.tenant_name?.trim()
    const base = location.origin
    const download = config?.download_url
    return (
        <main className="flex min-h-screen items-center justify-center bg-background p-4">
            <section className="flex w-full max-w-xl flex-col gap-4 rounded-lg border bg-background p-6">
                <h1 className="text-xl font-semibold">{t('dsh.title')}</h1>
                <p className="break-all text-sm text-muted-foreground">
                    {base}
                </p>
                {invalid || failed ? (
                    <p role="alert">{t('dsh.unavailable')}</p>
                ) : !config ? (
                    <p role="status">{t('dsh.loading')}</p>
                ) : !config.enabled ? (
                    <p role="status">{t('dsh.disabled')}</p>
                ) : (
                    <>
                        {!authId ? (
                            <>
                                <p>{t('dsh.entryHelp')}</p>
                                <Button
                                    onClick={() =>
                                        location.assign(
                                            `dsh-desktop://login?${new URLSearchParams({ server: base })}`,
                                        )
                                    }
                                >
                                    {t('dsh.openDesktop')}
                                </Button>
                                <p className="text-sm text-muted-foreground">
                                    {t('dsh.installHelp')}
                                </p>
                                {download && (
                                    <Button variant="outline" asChild>
                                        <a
                                            href={download}
                                            target="_blank"
                                            rel="noreferrer"
                                        >
                                            {t('dsh.download')}
                                        </a>
                                    </Button>
                                )}
                                <Input
                                    aria-label={t('dsh.server')}
                                    readOnly
                                    value={base}
                                />
                                <Button
                                    variant="outline"
                                    onClick={() => handleCopy(base)}
                                >
                                    {t('dsh.copyServer')}
                                </Button>
                            </>
                        ) : !user?.user_id ? (
                            <Button onClick={handleLogin}>
                                {t('dsh.login')}
                            </Button>
                        ) : (
                            <>
                                <p>
                                    {t(tenantName ? 'dsh.authorizeHelp' : 'dsh.authorize_without_tenant', {
                                        name: user.user_name,
                                        tenant: tenantName,
                                    })}
                                </p>
                                {flow.status === 'idle' && (
                                    <div className="flex flex-wrap gap-2">
                                        <Button onClick={flow.handleAuthorize}>
                                            {t('dsh.authorize')}
                                        </Button>
                                        <Button
                                            variant="outline"
                                            onClick={flow.handleCancel}
                                        >
                                            {t('dsh.cancel')}
                                        </Button>
                                    </div>
                                )}
                                <p role="status">
                                    {flow.status !== 'idle' &&
                                        t(`dsh.auth_${flow.status}`)}
                                </p>
                                {flow.denialUrl && (
                                    <iframe
                                        title={t('dsh.callback')}
                                        className="hidden"
                                        referrerPolicy="no-referrer"
                                        src={flow.denialUrl}
                                    />
                                )}
                                {flow.authorization && (
                                    <>
                                        <iframe
                                            title={t('dsh.callback')}
                                            className="hidden"
                                            referrerPolicy="no-referrer"
                                            src={callbackUrl(
                                                authId,
                                                flow.authorization,
                                            )}
                                        />
                                        <p>
                                            {t('dsh.ticketHelp', {
                                                seconds: flow.seconds,
                                            })}
                                        </p>
                                        <Input
                                            type="password"
                                            autoComplete="off"
                                            aria-label={t('dsh.ticket')}
                                            readOnly
                                            value={
                                                flow.authorization
                                                    .identity_ticket
                                            }
                                        />
                                        <Button
                                            onClick={() =>
                                                handleCopy(
                                                    flow.authorization!
                                                        .identity_ticket,
                                                )
                                            }
                                        >
                                            {t('dsh.copyTicket')}
                                        </Button>
                                    </>
                                )}
                            </>
                        )}
                        {copied && <p role="status">{t('dsh.copied')}</p>}
                    </>
                )}
            </section>
        </main>
    )
}
