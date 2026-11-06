/**
 * Detail + live instance state for one hosted application.
 *
 * Plain `useState` / `useEffect` on purpose: react-query v3 is frozen in this
 * app (lint `no-restricted-imports`) and the @tanstack migration has not
 * happened, so new data fetching does not get to use either.
 *
 * The two loads are kept apart because they fail differently and the page has
 * to survive that: the detail is the page (no detail, no page), while the
 * instance view legitimately answers "the orchestration backend is down" and
 * must degrade to a notice inside the publish tab rather than blanking the app.
 */
import {
  getHostedAppApi,
  getHostedAppErrorCode,
  getHostedAppErrorMessage,
  getHostedAppInstanceApi,
  HOSTED_APP_ERROR,
  type HostedAppDetail,
  type HostedAppInstance,
} from "@/controllers/API/hostedApp"
import { useCallback, useEffect, useState } from "react"

export type HostedAppLoadError = "forbidden" | "not_found" | "failed"

interface UseHostedAppResult {
  app: HostedAppDetail | null
  instance: HostedAppInstance | null
  loading: boolean
  error: HostedAppLoadError | null
  errorMessage: string
  instanceError: string
  reload: () => void
  reloadInstance: () => void
}

function classify(error: unknown): HostedAppLoadError {
  const code = getHostedAppErrorCode(error)
  if (code === HOSTED_APP_ERROR.MANAGE_FORBIDDEN || code === HOSTED_APP_ERROR.OWNER_ONLY) {
    return "forbidden"
  }
  if (code === HOSTED_APP_ERROR.NOT_FOUND) return "not_found"
  return "failed"
}

export function useHostedApp(appId: string | undefined): UseHostedAppResult {
  const [app, setApp] = useState<HostedAppDetail | null>(null)
  const [instance, setInstance] = useState<HostedAppInstance | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<HostedAppLoadError | null>(null)
  const [errorMessage, setErrorMessage] = useState("")
  const [instanceError, setInstanceError] = useState("")

  const reloadInstance = useCallback(() => {
    if (!appId) return
    getHostedAppInstanceApi(appId)
      .then((data) => {
        setInstance(data)
        setInstanceError("")
      })
      .catch((err) => {
        setInstance(null)
        setInstanceError(getHostedAppErrorMessage(err))
      })
  }, [appId])

  const reload = useCallback(() => {
    if (!appId) {
      setLoading(false)
      setError("not_found")
      return
    }
    setLoading(true)
    getHostedAppApi(appId)
      .then((data) => {
        setApp(data)
        setError(null)
        setErrorMessage("")
        reloadInstance()
      })
      .catch((err) => {
        setApp(null)
        setError(classify(err))
        setErrorMessage(getHostedAppErrorMessage(err))
      })
      .finally(() => setLoading(false))
  }, [appId, reloadInstance])

  useEffect(() => {
    reload()
  }, [reload])

  return {
    app,
    instance,
    loading,
    error,
    errorMessage,
    instanceError,
    reload,
    reloadInstance,
  }
}
