// @ts-strict-ignore
"use client"

import { Howl } from "howler"
import { useCallback } from "react"
import { atom, useRecoilState, useRecoilValue, useSetRecoilState } from "recoil"

let progressAnimationId: number | null = null

/**
 * The Howl instance is a module-level singleton, NOT Recoil state: playback is
 * global (one audio at a time across all conversations) and the instance is
 * consumed inside async flows where a Recoil value read through a hook closure
 * goes stale — a stale closure once let two Howl instances play simultaneously
 * with the older one orphaned (nothing could pause it). `playToken` versions
 * each playback request so that a slow TTS fetch resolving after the user
 * started another message's playback is discarded instead of double-playing.
 */
let currentSound: Howl | null = null
let playToken = 0

// Active message ID being played
export const activeMessageIdAtom = atom<string | null>({
  key: "audioPlayer_activeMessageId",
  default: null,
})

// Playing state
export const isPlayingAtom = atom<boolean>({
  key: "audioPlayer_isPlaying",
  default: false,
})

// Loading state
export const isLoadingAudioAtom = atom<boolean>({
  key: "audioPlayer_isLoading",
  default: false,
})

// Playback progress (0-100)
export const playbackProgressAtom = atom<number>({
  key: "audioPlayer_playbackProgress",
  default: 0,
})

// Tear down the singleton sound without touching Recoil state.
const unloadCurrentSound = () => {
  if (progressAnimationId !== null) {
    cancelAnimationFrame(progressAnimationId)
    progressAnimationId = null
  }
  if (currentSound) {
    currentSound.unload()
    currentSound = null
  }
}

export function useAudioPlayer() {
  const [activeMessageId, setActiveMessageId] = useRecoilState(activeMessageIdAtom)
  const [isPlaying, setIsPlaying] = useRecoilState(isPlayingAtom)
  const [isLoadingAudio, setIsLoadingAudio] = useRecoilState(isLoadingAudioAtom)
  const setPlaybackProgress = useSetRecoilState(playbackProgressAtom)

  // Reset all playback UI state back to idle.
  const resetState = useCallback(() => {
    setIsPlaying(false)
    setIsLoadingAudio(false)
    setPlaybackProgress(0)
    setActiveMessageId(null)
  }, [setIsPlaying, setIsLoadingAudio, setPlaybackProgress, setActiveMessageId])

  // Update playback progress
  const updateProgress = useCallback(
    (sound: Howl) => {
      if (!sound.playing()) {
        return
      }

      const seek = sound.seek() as number
      const duration = sound.duration()
      const progress = duration > 0 ? (seek / duration) * 100 : 0

      setPlaybackProgress(progress)

      progressAnimationId = requestAnimationFrame(() => updateProgress(sound))
    },
    [setPlaybackProgress],
  )

  /**
   * Start playback of a message: stop whatever is playing NOW (not after the
   * fetch — the old audio must not keep sounding, uncontrollable, while the new
   * one loads), then fetch the audio URL and play it — unless a newer playback
   * request superseded this one meanwhile (token check), in which case the
   * result is discarded. Throws fetch errors through so the caller can toast.
   */
  const playAudio = useCallback(
    async (messageId: string, getAudioUrl: () => Promise<string>) => {
      const token = ++playToken
      unloadCurrentSound()
      setActiveMessageId(messageId)
      setIsLoadingAudio(true)
      setIsPlaying(false)
      setPlaybackProgress(0)

      let audioUrl: string
      try {
        audioUrl = await getAudioUrl()
      } catch (error) {
        // Only reset if this request is still the active one — a newer
        // playback owns the state otherwise.
        if (token === playToken) resetState()
        throw error
      }
      if (token !== playToken) return

      const sound = new Howl({
        src: [audioUrl],
        html5: true,
        // Every callback checks the token: a superseded sound (user already
        // started another message) must not clobber the new playback's state.
        onload: () => {
          if (token !== playToken) return
          setIsLoadingAudio(false)
          sound.play()
        },
        onplay: () => {
          if (token !== playToken) return
          setIsPlaying(true)
          updateProgress(sound)
        },
        onpause: () => {
          if (token !== playToken) return
          setIsPlaying(false)
          if (progressAnimationId !== null) {
            cancelAnimationFrame(progressAnimationId)
            progressAnimationId = null
          }
        },
        onend: () => {
          if (token !== playToken) return
          unloadCurrentSound()
          resetState()
        },
        onstop: () => {
          if (token !== playToken) return
          unloadCurrentSound()
          resetState()
        },
        onloaderror: (_id, error) => {
          console.error("Audio load error:", error)
          if (token !== playToken) return
          unloadCurrentSound()
          resetState()
        },
        onplayerror: (_id, error) => {
          console.error("Audio play error:", error)
          if (token !== playToken) return
          unloadCurrentSound()
          resetState()
        },
      })

      currentSound = sound
    },
    [resetState, setActiveMessageId, setIsLoadingAudio, setIsPlaying, setPlaybackProgress, updateProgress],
  )

  // Pause current audio (module singleton — never a stale closure).
  const pauseAudio = useCallback(() => {
    if (currentSound?.playing()) {
      currentSound.pause()
      setIsPlaying(false)
    }
  }, [setIsPlaying])

  // Resume current audio
  const resumeAudio = useCallback(() => {
    if (currentSound && !currentSound.playing()) {
      currentSound.play()
      setIsPlaying(true)
    }
  }, [setIsPlaying])

  // Stop and cleanup
  const stopAudio = useCallback(() => {
    playToken++ // invalidate any in-flight playback request
    unloadCurrentSound()
    resetState()
  }, [resetState])

  return {
    activeMessageId,
    isPlaying,
    isLoadingAudio,
    playAudio,
    pauseAudio,
    resumeAudio,
    stopAudio,
  }
}

// Hook to get progress for a specific message
export function useAudioProgress(messageId: string) {
  const activeMessageId = useRecoilValue(activeMessageIdAtom)
  const progress = useRecoilValue(playbackProgressAtom)

  return activeMessageId === messageId ? progress : 0
}


/**
 * Interrupt audio playback
 * Control the atomic state and hook for interrupting audio playback
 */
export const interruptAudioAtom = atom<boolean>({
  key: "audioPlayer_interruptAudio",
  default: false,
})
export function useInterruptAudio() {
  const setInterruptAudio = useSetRecoilState(interruptAudioAtom)

  const interruptAudio = useCallback(() => {
    setInterruptAudio(true)
    window.interruptAudio = true

    setTimeout(() => {
      setInterruptAudio(false)
      delete window.interruptAudio
    }, 500)
  }, [setInterruptAudio])

  return interruptAudio
}

/**
 * 录音loading
 * Atomic state and hook for recording audio loading state
 * */
export const recordingAudioLoadingAtom = atom<boolean>({
  key: "audioPlayer_recordingAudioLoading",
  default: false,
})

export function useRecordingAudioLoading() {
  const [isLoading, setIsLoading] = useRecoilState(recordingAudioLoadingAtom)
  return [isLoading, setIsLoading] as const
}