import request from '@/controllers/request'
import { useEffect, useState } from 'react'

export function useDshProfile(userId: number | undefined, enabled: boolean) {
    const [profile, setProfile] = useState<{ userId: number; department_name: string | null } | null>(null)
    useEffect(() => {
        if (!enabled || !userId) return
        const controller = new AbortController()
        void request.get<unknown, { department_name: string | null }>('/api/v1/dsh/me/profile', { signal: controller.signal }).then((data: { department_name: string | null }) => {
            if (!controller.signal.aborted) setProfile({ userId, department_name: data.department_name })
        }).catch(() => {
            if (!controller.signal.aborted) setProfile(null)
        })
        return () => controller.abort()
    }, [userId, enabled])
    return enabled && profile?.userId === userId ? profile : null
}
