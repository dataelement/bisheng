import { authorizeDsh, denyDsh } from '@/controllers/API/dsh'
import type { DshAuthorization } from '@/types/dsh'
import { useEffect, useRef, useState } from 'react'

export function readAuthId(search: string): string | null {
    const params = new URLSearchParams(search)
    const values = params.getAll('auth_id')
    if (!values.length) return null
    if (values.length !== 1 || !/^[A-Za-z0-9_-]{1,128}$/.test(values[0]))
        throw new Error('Invalid authorization identifier')
    return values[0]
}
export function callbackUrl(
    authId: string,
    authorization: DshAuthorization,
): string {
    const url = new URL(authorization.redirect_uri)
    url.search = new URLSearchParams({
        auth_id: authId,
        identity_ticket: authorization.identity_ticket,
        state: authorization.state,
    }).toString()
    return url.href
}
export function useDshAuthorization(authId: string | null) {
    const [authorization, setAuthorization] = useState<DshAuthorization | null>(
        null,
    )
    const [status, setStatus] = useState<
        'idle' | 'pending' | 'issued' | 'expired' | 'failed' | 'cancelled'
    >('idle')
    const [denialUrl, setDenialUrl] = useState<string | null>(null)
    const active = useRef<AbortController | null>(null)
    const deadline = useRef(0)
    useEffect(
        () => () => {
            active.current?.abort()
        },
        [],
    )
    useEffect(() => {
        if (status !== 'issued') return
        const timer = window.setTimeout(() => {
            setAuthorization(null)
            setStatus('expired')
        }, Math.max(0, deadline.current - Date.now()))
        return () => window.clearTimeout(timer)
    }, [status])
    async function handleAuthorize() {
        if (!authId || active.current || status !== 'idle') return
        const controller = new AbortController()
        active.current = controller
        setStatus('pending')
        try {
            const result = await authorizeDsh(authId, controller.signal)
            if (controller.signal.aborted) return
            deadline.current = Date.now() + result.expires_in * 1000
            setAuthorization(result)
            setStatus('issued')
        } catch {
            if (!controller.signal.aborted) setStatus('failed')
        } finally {
            if (active.current === controller) active.current = null
        }
    }
    async function handleCancel() {
        if (!authId || active.current || status !== 'idle') return
        const controller = new AbortController()
        active.current = controller
        setStatus('pending')
        try {
            const result = await denyDsh(authId, controller.signal)
            if (controller.signal.aborted) return
            const url = new URL(result.redirect_uri)
            url.search = new URLSearchParams({
                auth_id: authId,
                error: result.error,
                state: result.state,
            }).toString()
            setDenialUrl(url.href)
            setStatus('cancelled')
        } catch {
            if (!controller.signal.aborted) setStatus('failed')
        } finally {
            if (active.current === controller) active.current = null
        }
    }
    return {
        authorization,
        denialUrl,
        status,
        handleAuthorize,
        handleCancel,
    }
}
