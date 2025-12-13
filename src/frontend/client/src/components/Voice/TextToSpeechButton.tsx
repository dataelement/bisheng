"use client"

import { Loader2, Pause, Volume2 } from "lucide-react"
import { textToSpeech } from "~/api"
import { useGetWorkbenchModelsQuery } from "~/data-provider"
import { useToastContext } from "~/Providers"
import { cn } from "~/utils"
import {
    useAudioPlayer
} from "./textToSpeechStore"


interface TextToSpeechButtonProps {
    messageId: string
    text: string
    className?: string
}

export const TextToSpeechButton = ({ messageId, text, className }: TextToSpeechButtonProps) => {
    const { activeMessageId, isLoadingAudio, isPlaying, playAudio, setActiveMessageId, pauseAudio, resumeAudio, stopAudio, setIsLoadingAudio } = useAudioPlayer()
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

            setActiveMessageId(messageId)
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



