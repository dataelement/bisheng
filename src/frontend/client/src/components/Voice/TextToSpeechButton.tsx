// @ts-strict-ignore
"use client"

import { Outlined } from "bisheng-icons"
import { textToSpeech } from "~/api"
import { useGetWorkbenchModelsQuery } from "~/hooks/queries/data-provider"
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
    const { activeMessageId, isLoadingAudio, isPlaying, playAudio, pauseAudio, resumeAudio } = useAudioPlayer()
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
            // Re-throw as-is (not wrapped) so a backend business error (e.g. TTS
            // synthesis failure, code 10026) keeps its status_code — the request
            // interceptor already toasted the localized message for those; the
            // caller only needs to fall back to a generic toast for other errors.
            throw error
        }
    }

    // Handle play/pause action
    const handlePlayPause = async (event?: React.MouseEvent<HTMLButtonElement>) => {
        event?.preventDefault()
        event?.stopPropagation()
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

            // New message: the store stops any currently-playing audio at once,
            // fetches, then plays — discarding the result if the user starts
            // another playback while this fetch is in flight (token guard).
            await playAudio(messageId, () => fetchAudioUrl(text))
        } catch (error) {
            console.error("Failed to play audio:", error)
            // A backend business error (e.g. TTS synthesis failure, code 10026)
            // already got its localized toast from the request interceptor
            // (skip403Redirect path) — only show the generic fallback here for
            // errors that never reached that path (network failure, malformed
            // response, etc.), so the user doesn't see two toasts. State reset
            // on error is handled inside the store.
            if (!(error as any)?.status_code) {
                showToast({ message: "播放功能不可用，请联系管理员", status: "error" })
            }
        }
    }

    // Render icon based on state
    const renderIcon = () => {
        if (isCurrentLoading) {
            return <Outlined.Loading size={14} className="animate-spin text-[#818181]" />
        }

        if (isCurrentPlaying) {
            return (
                <Outlined.PlayerPause
                    size={14}
                    className="text-[#818181]"
                />
            )
        }

        return (
            <Outlined.VolumeNotice
                size={14}
                className="text-[#818181]"
            />
        )
    }

    // Disabled when tts_model is not configured
    const { data: modelData } = useGetWorkbenchModelsQuery()
    if (!modelData?.tts_model?.id) return null

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


