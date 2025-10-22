"use client"

import { Howl } from "howler"
import { Loader2, Pause, Volume2 } from "lucide-react"
import { useCallback } from "react"
import { useRecoilState, useRecoilValue, useSetRecoilState } from "recoil"
import { textToSpeech } from "~/api"
import { useToastContext } from "~/Providers"
import {
    activeMessageIdAtom,
    audioInstanceAtom,
    isLoadingAudioAtom,
    isPlayingAtom,
    playbackProgressAtom,
} from "./textToSpeechStore"
import { useGetWorkbenchModelsQuery } from "~/data-provider"
import { cn } from "~/utils"


interface TextToSpeechButtonProps {
    messageId: string
    text: string
    className?: string
}

export const TextToSpeechButton = ({ messageId, text, className }: TextToSpeechButtonProps) => {
    const { activeMessageId, isLoadingAudio, isPlaying, playAudio, pauseAudio, resumeAudio, stopAudio, setIsLoadingAudio } = useAudioPlayer()
    const { showToast } = useToastContext()

    // Check current message playback state
    const isCurrentMessage = activeMessageId === messageId
    const isCurrentLoading = isCurrentMessage && isLoadingAudio
    const isCurrentPlaying = isCurrentMessage && isPlaying

    // Fetch audio URL from API
    const fetchAudioUrl = async (content: string): Promise<string> => {
        try {
            const response = await textToSpeech(content)

            // Parse API response to get audio path
            let audioPath = ""
            if (typeof response === "string") {
                audioPath = response
            } else if (response?.data) {
                audioPath = typeof response.data === "string" ? response.data : response.data?.data || ""
            }

            if (!audioPath) {
                throw new Error("Failed to parse audio path from response")
            }

            // Construct full URL
            return `${__APP_ENV__.BASE_URL}${audioPath}`
        } catch (error) {
            console.error("Failed to fetch audio URL:", error)
            throw new Error("Audio generation failed")
        }
    }

    // Handle play/pause action
    const handlePlayPause = async () => {
        try {
            // If this is the current message
            if (isCurrentMessage) {
                if (isPlaying) {
                    pauseAudio()
                } else {
                    resumeAudio()
                }
                return
            }

            setIsLoadingAudio(true)
            // If this is a new message, fetch audio and play
            const audioUrl = await fetchAudioUrl(text)
            playAudio(messageId, audioUrl)
        } catch (error) {
            console.error("Failed to play audio:", error)
            showToast({ message: "播放功能不可用，请联系管理员", status: "error" })

            // Clean up state on error
            if (isCurrentMessage) {
                stopAudio()
            }
        }
    }

    // Render icon based on state
    const renderIcon = () => {
        if (isCurrentLoading) {
            return <Loader2 size={20} strokeWidth={1.8} className="animate-spin text-gray-400" />
        }

        if (isCurrentPlaying) {
            return (
                <Pause
                    size={20}
                    strokeWidth={1.8}
                    className="text-gray-400 hover:text-primary transition-colors cursor-pointer"
                />
            )
        }

        return (
            <Volume2
                size={20}
                strokeWidth={1.8}
                className="text-gray-400 hover:text-primary transition-colors cursor-pointer"
            />
        )
    }

    // Disabled when tts_model is not configured
    const { data: modelData } = useGetWorkbenchModelsQuery()
    if (!modelData?.tts_model.id) return null

    return (
        <button
            onClick={handlePlayPause}
            disabled={isCurrentLoading}
            aria-label={isCurrentPlaying ? "Pause" : "Play"}
            className={cn("inline-flex items-center justify-center disabled:opacity-50 disabled:cursor-not-allowed", className)}
        >
            {renderIcon()}
        </button>
    )
}



let progressAnimationId: number | null = null

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
        setIsLoadingAudio
    }
}

// Hook to get progress for a specific message
export function useAudioProgress(messageId: string) {
    const activeMessageId = useRecoilValue(activeMessageIdAtom)
    const progress = useRecoilValue(playbackProgressAtom)

    return activeMessageId === messageId ? progress : 0
}
