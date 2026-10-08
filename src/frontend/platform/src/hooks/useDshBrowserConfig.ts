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
                if (!current.signal.aborted) { setConfig(value); setFailed(false) }
            }).catch(() => {
                if (!current.signal.aborted) { setConfig(null); setFailed(true) }
            })
        }
        refresh()
        const timer = window.setInterval(refresh, 30000)
        window.addEventListener('focus', refresh)
        window.addEventListener('dsh-settings-changed', refresh)
        return () => {
            abort?.abort()
            window.clearInterval(timer)
            window.removeEventListener('focus', refresh)
            window.removeEventListener('dsh-settings-changed', refresh)
        }
    }, [])
    return { config, failed }
}
