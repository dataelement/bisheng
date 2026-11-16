import { getDshBrowserConfig, type DshBrowserConfig } from '@/controllers/API/dshSettings'
import { useEffect, useState } from 'react'

export function useDshBrowserConfig() {
    const [config, setConfig] = useState<DshBrowserConfig | null>(null)
    const [failed, setFailed] = useState(false)
    useEffect(() => {
        let abort: AbortController | undefined
        const refresh = () => {
            abort?.abort()
            const current = new AbortController()
            abort = current
            getDshBrowserConfig(current.signal).then((value) => {
                if (current.signal.aborted) return
                setConfig(value); setFailed(false)
                // `management_enabled` reflects whether DSH is deployed at all (yaml,
                // changes only with a restart); `enabled` is the runtime management
                // toggle and keeps being polled. Nothing to poll for without DSH.
                if (value.management_enabled === false) stopPolling()
            }).catch(() => {
                if (!current.signal.aborted) { setConfig(null); setFailed(true) }
            })
        }
        const timer = window.setInterval(refresh, 30000)
        const stopPolling = () => {
            window.clearInterval(timer)
            window.removeEventListener('focus', refresh)
        }
        refresh()
        window.addEventListener('focus', refresh)
        window.addEventListener('dsh-settings-changed', refresh)
        return () => {
            abort?.abort()
            stopPolling()
            window.removeEventListener('dsh-settings-changed', refresh)
        }
    }, [])
    return { config, failed }
}
