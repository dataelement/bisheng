"use client"

import { Howl } from "howler"
import { useCallback } from "react"
import { atom, useRecoilState, useRecoilValue, useSetRecoilState } from "recoil"

let progressAnimationId: number | null = null

// Active message ID being played
export const activeMessageIdAtom = atom<string | null>({
  key: "audioPlayer_activeMessageId",
  default: null,
})

// Audio instance (Howl object)
export const audioInstanceAtom = atom<Howl | null>({
  key: "audioPlayer_audioInstance",
  default: null,
  dangerouslyAllowMutability: true, // Howl instance is mutable
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

export function useAudioPlayer() {
  const [activeMessageId, setActiveMessageId] = useRecoilState(activeMessageIdAtom)
  const [audioInstance, setAudioInstance] = useRecoilState(audioInstanceAtom)
  const [isPlaying, setIsPlaying] = useRecoilState(isPlayingAtom)
  const [isLoadingAudio, setIsLoadingAudio] = useRecoilState(isLoadingAudioAtom)
  const setPlaybackProgress = useSetRecoilState(playbackProgressAtom)

  // Clean up audio resources
  const cleanupAudio = useCallback(() => {
    if (progressAnimationId !== null) {
      cancelAnimationFrame(progressAnimationId)
      progressAnimationId = null
    }

    if (audioInstance) {
      audioInstance.unload()
      setAudioInstance(null)
    }

    setIsPlaying(false)
    setPlaybackProgress(0)
  }, [audioInstance, setAudioInstance, setIsPlaying, setPlaybackProgress])

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

  // Play audio from URL
  const playAudio = useCallback(
    (messageId: string, audioUrl: string) => {
      // Stop current audio if playing
      if (audioInstance) {
        cleanupAudio()
      }

      setActiveMessageId(messageId)
      setIsLoadingAudio(true)

      const sound = new Howl({
        src: [audioUrl],
        html5: true,
        onload: () => {
          // Check if this is still the active message
          setIsLoadingAudio(false)
          sound.play()
          setIsPlaying(true)
          updateProgress(sound)
        },
        onplay: () => {
          setIsPlaying(true)
          updateProgress(sound)
        },
        onpause: () => {
          setIsPlaying(false)
          if (progressAnimationId !== null) {
            cancelAnimationFrame(progressAnimationId)
            progressAnimationId = null
          }
        },
        onend: () => {
          cleanupAudio()
          setActiveMessageId(null)
        },
        onstop: () => {
          cleanupAudio()
        },
        onloaderror: (_id, error) => {
          console.error("[v0] Audio load error:", error)
          setIsLoadingAudio(false)
          cleanupAudio()
          setActiveMessageId(null)
        },
        onplayerror: (_id, error) => {
          console.error("[v0] Audio play error:", error)
          cleanupAudio()
          setActiveMessageId(null)
        },
      })

      setAudioInstance(sound)
    },
    [
      audioInstance,
      cleanupAudio,
      setActiveMessageId,
      setIsLoadingAudio,
      setAudioInstance,
      setIsPlaying,
      updateProgress,
    ],
  )

  // Pause current audio
  const pauseAudio = useCallback(() => {
    if (audioInstance && isPlaying) {
      audioInstance.pause()
      setIsPlaying(false)
    }
  }, [audioInstance, isPlaying, setIsPlaying])

  // Resume current audio
  const resumeAudio = useCallback(() => {
    if (audioInstance && !isPlaying) {
      audioInstance.play()
      setIsPlaying(true)
    }
  }, [audioInstance, isPlaying, setIsPlaying])

  // Stop and cleanup
  const stopAudio = useCallback(() => {
    if (audioInstance) {
      audioInstance.stop()
    }
    cleanupAudio()
    setActiveMessageId(null)
  }, [audioInstance, cleanupAudio, setActiveMessageId])

  return {
    activeMessageId,
    isPlaying,
    isLoadingAudio,
    playAudio,
    pauseAudio,
    resumeAudio,
    stopAudio,
    setIsLoadingAudio,
    setActiveMessageId
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
 * Atomic state and hook for parsing audio loading state
 */
export const parsingAudioLoadingAtom = atom<boolean>({
  key: "audioPlayer_parsingAudioLoading",
  default: false,
})

export function useParsingAudioLoading() {
  const [isLoading, setIsLoading] = useRecoilState(parsingAudioLoadingAtom)
  return [isLoading, setIsLoading] as const
}