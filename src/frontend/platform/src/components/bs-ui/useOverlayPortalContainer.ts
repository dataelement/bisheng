import * as React from "react"

export type OverlayPortalContainer = Element | DocumentFragment | null

type WebkitFullscreenDocument = Document & {
  webkitFullscreenElement?: Element | null
}

const fullscreenListeners = new Set<() => void>()
let isListeningForFullscreen = false

function getFullscreenElement(): Element | null {
  if (typeof document === "undefined") return null

  return document.fullscreenElement
    ?? (document as WebkitFullscreenDocument).webkitFullscreenElement
    ?? null
}

function notifyFullscreenListeners() {
  fullscreenListeners.forEach(listener => listener())
}

function subscribeToFullscreen(listener: () => void) {
  if (typeof document === "undefined") return () => {}

  fullscreenListeners.add(listener)
  if (!isListeningForFullscreen) {
    document.addEventListener("fullscreenchange", notifyFullscreenListeners)
    document.addEventListener("webkitfullscreenchange", notifyFullscreenListeners)
    isListeningForFullscreen = true
  }

  return () => {
    fullscreenListeners.delete(listener)
    if (fullscreenListeners.size === 0 && isListeningForFullscreen) {
      document.removeEventListener("fullscreenchange", notifyFullscreenListeners)
      document.removeEventListener("webkitfullscreenchange", notifyFullscreenListeners)
      isListeningForFullscreen = false
    }
  }
}

export function useOverlayPortalContainer(
  explicitContainer?: OverlayPortalContainer,
): Element | DocumentFragment | undefined {
  const fullscreenElement = React.useSyncExternalStore(
    subscribeToFullscreen,
    getFullscreenElement,
    () => null,
  )

  return explicitContainer ?? fullscreenElement ?? undefined
}
