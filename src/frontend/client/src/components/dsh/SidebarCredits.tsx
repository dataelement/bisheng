import { useQuery } from '@tanstack/react-query'
import { useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { useLocation, useNavigate } from 'react-router-dom'
import { getDshCredits } from '~/api/dsh'
import { subscribeConversationActivity } from '~/components/Chat/desktopConversationBridge'
import { useAuthContext } from '~/hooks'
import { useDshDesktop } from '~/hooks/useDshDesktop'
import { createSettingsRouteState, readSettingsRouteState } from '~/pages/settings/settingsHistory'

// A turn is charged when its model call settles; a new conversation's title call (itself a model
// call, around ten seconds with a reasoning model) follows, so the balance is read twice.
const SETTLE_DELAYS_MS = [1500, 20_000]
// Backstop for calls made elsewhere (desktop Work, knowledge spaces, other tabs).
const REFRESH_INTERVAL_MS = 60_000

interface SidebarCreditsProps {
    onNavigate?: () => void
}

/** This month's remaining credits beside the account entry; opens the full card in settings. */
export function SidebarCredits({ onNavigate }: SidebarCreditsProps) {
    const { t, i18n } = useTranslation()
    const navigate = useNavigate()
    const location = useLocation()
    const { user } = useAuthContext()
    const { enabled } = useDshDesktop()
    // Same key as the settings card, so both always show one balance.
    const credits = useQuery({
        queryKey: ['dsh-self-credits', user?.id],
        enabled: enabled && Boolean(user?.id),
        retry: false,
        staleTime: 0,
        refetchInterval: REFRESH_INTERVAL_MS,
        queryFn: ({ signal }) => getDshCredits(signal),
    })
    const { refetch } = credits

    useEffect(() => {
        let timers: number[] = []
        const unsubscribe = subscribeConversationActivity(() => {
            timers.forEach((timer) => window.clearTimeout(timer))
            timers = SETTLE_DELAYS_MS.map((delay) => window.setTimeout(() => void refetch(), delay))
        })
        return () => {
            unsubscribe()
            timers.forEach((timer) => window.clearTimeout(timer))
        }
    }, [refetch])

    // An unreadable balance stays on the settings card, which explains it and offers a retry.
    if (!enabled || !credits.data) return null
    const { unlimited, remaining, limit } = credits.data
    const number = new Intl.NumberFormat(i18n.language, { maximumFractionDigits: 2 })
    // "remaining / allowance": raising an exhausted member's allowance visibly changes the row.
    const value = unlimited
        ? t('dsh.creditsUnlimited')
        : remaining == null
          ? '—'
          : `${number.format(Number(remaining))} / ${number.format(Number(limit))}`

    const openCredits = () => {
        const alreadyInSettings = /^\/settings(?:\/|$)/.test(location.pathname)
        const state = alreadyInSettings
            ? readSettingsRouteState(location.state)
            : createSettingsRouteState(location, window.history.state?.idx)
        navigate('/settings/desktop', { replace: alreadyInSettings, state })
        onNavigate?.()
    }

    return (
        <button
            type="button"
            data-sidebar-credits
            // Same row chrome as the account button below it.
            className="flex w-full shrink-0 items-center justify-between gap-2 rounded-lg px-2 py-1 text-left outline-none transition-colors hover:bg-fill-1 focus-visible:bg-fill-1 coarse-pointer:min-h-11"
            onClick={openCredits}
        >
            <span className="min-w-0 truncate text-body-sm text-text-2">{t('dsh.creditsRemaining')}</span>
            <span className="shrink-0 text-body-sm font-medium tabular-nums text-text-1">{value}</span>
        </button>
    )
}
