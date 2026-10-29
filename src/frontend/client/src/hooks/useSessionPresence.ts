/**
 * Department concurrency: page lease for one session page.
 *
 * The page holds one lease per tab and renews it every 30s. The lease only
 * covers "the user is looking at this session", so it is released when the user
 * leaves the page — not when a single reply finishes. The backend also accepts
 * the id on execution requests (`X-Flow-Lease-Id`) and on the app WebSocket
 * (`flow_lease_id`), so a reply never takes a second slot.
 *
 * Mount this ONCE per session, in the component that renders that session.
 * Mounting it in a shared hook (e.g. `useLinsightManager`) would give every
 * caller its own lease and multiply the count.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { useActivate, useUnactivate } from 'react-activation'
import request from '~/api/request'
import { useLocalize, useToast } from '~/hooks'
import { generateUUID } from '~/utils'

const RENEW_INTERVAL_MS = 30_000
const PRESENCE_BASE = `${__APP_ENV__.BASE_URL}/api/v1/department-flow/presence`

type PresenceOutcome = 'held' | 'rejected' | 'skipped'

interface EnsurePayload {
  outcome?: PresenceOutcome
  department_id?: number | null
  limited?: boolean
}

export interface EnsureLeaseResult {
  /** Lease id to send with the request, or null when this page does not count. */
  leaseId: string | null
  /** True when the department is full — the caller must not send. */
  blocked: boolean
}

export interface SessionPresence {
  leaseId: string | null
  /**
   * Lease id for the request about to be sent. Generates one on first use and
   * re-checks the slot when the page was previously rejected, so a user who
   * comes back later can succeed without reloading.
   */
  ensureLeaseId: () => Promise<EnsureLeaseResult>
}

export interface SessionPresenceOptions {
  /**
   * Share pages and guest sessions must not take a slot: a forwarded link would
   * otherwise be able to exhaust a whole department.
   */
  disabled?: boolean
}

export function useSessionPresence(
  sessionKey: string | null | undefined,
  options: SessionPresenceOptions = {},
): SessionPresence {
  const { disabled = false } = options
  const localize = useLocalize()
  const { showToast } = useToast()

  const [leaseId, setLeaseId] = useState<string | null>(null)
  const leaseIdRef = useRef<string | null>(null)
  /** Department of the last successful `held` — released with this exact id. */
  const departmentIdRef = useRef<number | null>(null)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  /** Last known slot state; `rejected` makes the next send re-check first. */
  const outcomeRef = useRef<PresenceOutcome | 'idle' | 'no-limit'>('idle')
  const prevSessionKeyRef = useRef<string | null>(null)

  const stopHeartbeat = useCallback(() => {
    if (timerRef.current !== null) {
      clearInterval(timerRef.current)
      timerRef.current = null
    }
  }, [])

  const releaseLease = useCallback(async (id: string | null) => {
    const departmentId = departmentIdRef.current
    // No department yet (first beat has not returned) — the lease expires on
    // its own instead of being deleted from a guessed key.
    if (!id || departmentId === null) return
    departmentIdRef.current = null
    try {
      await request.post(`${PRESENCE_BASE}/release`, { lease_id: id, department_id: departmentId })
    } catch {
      // Best effort: the lease expires after LEASE_TTL_MS anyway.
    }
  }, [])

  // Declared before `startHeartbeat` so the interval can call the latest `beat`
  // without capturing a stale closure (and without restarting on every render).
  const beatRef = useRef<(id: string) => Promise<PresenceOutcome | 'error'>>(async () => 'error')

  const startHeartbeat = useCallback(
    (id: string) => {
      if (disabled) return
      if (timerRef.current !== null) return
      timerRef.current = setInterval(() => {
        void beatRef.current(id)
      }, RENEW_INTERVAL_MS)
    },
    [disabled],
  )

  const beat = useCallback(
    async (id: string): Promise<PresenceOutcome | 'error'> => {
      if (disabled) return 'skipped'
      let payload: EnsurePayload
      try {
        const response = await request.post(`${PRESENCE_BASE}/ensure`, { lease_id: id })
        payload = (response as { data?: EnsurePayload } | undefined)?.data ?? {}
      } catch {
        // Network error or 5xx: not a `skipped`. Keep renewing — treating this
        // as "no limit" would silently drop the page out of the count.
        return 'error'
      }

      const outcome = payload.outcome ?? 'skipped'
      if (outcome === 'held') {
        if (payload.department_id !== null && payload.department_id !== undefined) {
          departmentIdRef.current = payload.department_id
        }
        outcomeRef.current = 'held'
        startHeartbeat(id)
        return 'held'
      }
      if (outcome === 'rejected') {
        stopHeartbeat()
        outcomeRef.current = 'rejected'
        showToast({ message: localize('api_errors.12045'), status: 'warning' })
        return 'rejected'
      }
      // `skipped` has two sources: no limit configured (stop heartbeating) and
      // Redis unavailable (keep going, this is a fail-open pass).
      if (payload.limited) {
        outcomeRef.current = 'skipped'
        startHeartbeat(id)
      } else {
        stopHeartbeat()
        outcomeRef.current = 'no-limit'
      }
      return 'skipped'
    },
    [disabled, localize, showToast, startHeartbeat, stopHeartbeat],
  )

  // `beat` is recreated when its dependencies change; the interval must call the
  // latest version without being restarted on every render.
  beatRef.current = beat

  const ensureLeaseId = useCallback(async (): Promise<EnsureLeaseResult> => {
    if (disabled) return { leaseId: null, blocked: false }
    let id = leaseIdRef.current
    if (!id) {
      id = generateUUID(32)
      leaseIdRef.current = id
      setLeaseId(id)
    }
    // Re-check before sending when the previous attempt was rejected, or when
    // nothing has been attempted yet (first submit from `c/new`).
    if (outcomeRef.current === 'rejected' || outcomeRef.current === 'idle') {
      const result = await beatRef.current(id)
      if (result === 'rejected') return { leaseId: id, blocked: true }
    }
    if (timerRef.current === null && outcomeRef.current !== 'no-limit') {
      startHeartbeat(id)
    }
    return { leaseId: id, blocked: false }
  }, [disabled, startHeartbeat])

  // Render-phase id creation: `wsUrl` and the SSE headers read this value in the
  // same render, so a later `useEffect` would let the first WebSocket connect
  // without the id and take a second slot.
  if (!disabled && sessionKey && !leaseId) {
    const next = generateUUID(32)
    leaseIdRef.current = next
    setLeaseId(next)
  }

  // Start (or restart) the heartbeat whenever the id changes.
  useEffect(() => {
    if (disabled || !leaseId) {
      stopHeartbeat()
      return
    }
    void beatRef.current(leaseId)
    return stopHeartbeat
  }, [disabled, leaseId, stopHeartbeat])

  // Switching away from a real conversation — or dropping back to `c/new` /
  // `/linsight/new` — releases the lease and forgets the id. `c/new` → real id
  // and `/linsight/new`'s sticky `new` keep it (the first submit already took
  // this lease).
  useEffect(() => {
    const previous = prevSessionKeyRef.current
    prevSessionKeyRef.current = sessionKey ?? null
    const id = leaseIdRef.current
    if (!id) return
    const previousWasReal = Boolean(previous)
    const nextWasReal = Boolean(sessionKey)
    const becameEmpty = previousWasReal && !nextWasReal
    const switchedToAnother = previousWasReal && nextWasReal && previous !== sessionKey
    if (!becameEmpty && !switchedToAnother) return
    void releaseLease(id)
    stopHeartbeat()
    outcomeRef.current = 'idle'
    leaseIdRef.current = null
    setLeaseId(null)
  }, [sessionKey, releaseLease, stopHeartbeat])

  // Real unmount: the user closed this session for good.
  useEffect(
    () => () => {
      void releaseLease(leaseIdRef.current)
      stopHeartbeat()
    },
    [releaseLease, stopHeartbeat],
  )

  // KeepAlive freezes instead of unmounting on a sidebar switch: release the
  // slot but keep the id so coming back re-asserts the same lease.
  useUnactivate(() => {
    void releaseLease(leaseIdRef.current)
    stopHeartbeat()
    // The slot was handed back, so the next send must re-check before sending
    // even though the lease id is kept for reactivation.
    outcomeRef.current = 'idle'
  })

  useActivate(() => {
    const id = leaseIdRef.current
    if (id && !disabled) void beatRef.current(id)
  })

  // Tab close / reload: `sendBeacon` survives unload, plain requests do not.
  useEffect(() => {
    const handlePageHide = () => {
      const id = leaseIdRef.current
      const departmentId = departmentIdRef.current
      if (!id || departmentId === null) return
      try {
        const body = new Blob([JSON.stringify({ lease_id: id, department_id: departmentId })], {
          type: 'application/json',
        })
        navigator.sendBeacon(`${PRESENCE_BASE}/release`, body)
      } catch {
        // Best effort: the lease expires after LEASE_TTL_MS.
      }
    }
    window.addEventListener('pagehide', handlePageHide)
    return () => window.removeEventListener('pagehide', handlePageHide)
  }, [])

  return { leaseId, ensureLeaseId }
}

export default useSessionPresence
