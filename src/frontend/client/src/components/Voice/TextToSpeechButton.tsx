"use client"

import { Loader2 } from "lucide-react"
import VolumeNotice from "bisheng-design-system/src/icons/outlined/VolumeNotice"
import PlayerPause from "bisheng-design-system/src/icons/outlined/PlayerPause"
import { SingleIconButton } from "bisheng-design-system/src/components/Button"
import { cn } from "~/utils"
import { textToSpeech } from "~/api"
import { useGetWorkbenchModelsQuery } from "~/hooks/queries/data-provider"
import { useToastContext } from "~/Providers"
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

    const getIcon = () => {
        if (isCurrentLoading) {
            return <Loader2 className="animate-spin" />
        }
        if (isCurrentPlaying) {
            return <PlayerPause />
        }
        return <VolumeNotice />
    }

    // Disabled when tts_model is not configured
    const { data: modelData } = useGetWorkbenchModelsQuery()
    if (!modelData?.tts_model.id) return null

    return (
        <SingleIconButton
            variant="ghost"
            size="mini"
            icon={getIcon()}
            aria-label={isCurrentPlaying ? "暂停" : "朗读"}
            onClick={handlePlayPause}
            disabled={isCurrentLoading}
            loading={isCurrentLoading}
            className={cn("text-gray-400 hover:text-gray-600", className)}
        />
    )
}



