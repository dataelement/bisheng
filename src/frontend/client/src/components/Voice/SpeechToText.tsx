"use client"

import { LoaderCircle, Mic } from "lucide-react"
import PropTypes from "prop-types"
import { useCallback, useEffect, useRef, useState } from "react"
import { useRecoilState } from "recoil"
import { getVoice2TextApi } from "~/api"
import { useToastContext } from "~/Providers"
import { Button } from ".."
import VoiceRecordingIcon from "../ui/icon/Voice"
import { interruptAudioAtom, useParsingAudioLoading } from "./textToSpeechStore"

// --- Core Audio Processing Logic ---

/**
 * Encodes an AudioBuffer to WAV format
 * Converts multi-channel audio to mono to reduce noise
 */
const encodeWAV = (audioBuffer: AudioBuffer): Blob => {
    const sampleRate = audioBuffer.sampleRate
    const channels = audioBuffer.numberOfChannels
    let samples = audioBuffer.getChannelData(0)

    // Convert multi-channel to mono (reduces noise)
    if (channels > 1) {
        const monoSamples = new Float32Array(samples.length)
        for (let i = 0; i < samples.length; i++) {
            let sum = 0
            for (let c = 0; c < channels; c++) {
                sum += audioBuffer.getChannelData(c)[i]
            }
            monoSamples[i] = sum / channels
        }
        samples = monoSamples
    }

    // Encode WAV file header
    const buffer = new ArrayBuffer(44 + samples.length * 2)
    const view = new DataView(buffer)

    const writeString = (view: DataView, offset: number, string: string) => {
        for (let i = 0; i < string.length; i++) {
            view.setUint8(offset + i, string.charCodeAt(i))
        }
    }

    // RIFF Chunk
    writeString(view, 0, "RIFF")
    view.setUint32(4, 36 + samples.length * 2, true)
    writeString(view, 8, "WAVE")

    // fmt Chunk
    writeString(view, 12, "fmt ")
    view.setUint32(16, 16, true)
    view.setUint16(20, 1, true) // PCM format
    view.setUint16(22, 1, true) // Mono channel
    view.setUint32(24, sampleRate, true)
    view.setUint32(28, sampleRate * 2, true)
    view.setUint16(32, 2, true)
    view.setUint16(34, 16, true) // 16-bit

    // data Chunk
    writeString(view, 36, "data")
    view.setUint32(40, samples.length * 2, true)

    // Write PCM data
    let offset = 44
    for (let i = 0; i < samples.length; i++) {
        const s = Math.max(-1, Math.min(1, samples[i]))
        view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7fff, true)
        offset += 2
    }

    return new Blob([view], { type: "audio/wav" })
}

/**
 * Converts a Blob to WAV format using Web Audio API
 */
const convertBlobToWav = async (blob: Blob): Promise<Blob> => {
    return new Promise((resolve, reject) => {
        const audioContext = new (window.AudioContext || (window as any).webkitAudioContext)({
            sampleRate: 44100,
        })
        const fileReader = new FileReader()

        fileReader.onload = async () => {
            try {
                const audioBuffer = await audioContext.decodeAudioData(fileReader.result as ArrayBuffer)
                const wavBlob = encodeWAV(audioBuffer)
                resolve(wavBlob)
                audioContext.close()
            } catch (err) {
                reject(new Error("Audio decoding failed: " + (err as Error).message))
                audioContext.close()
            }
        }

        fileReader.onerror = () => {
            reject(new Error("Failed to read audio file"))
        }

        fileReader.readAsArrayBuffer(blob)
    })
}

// --- Main Component ---

interface SpeechToTextComponentProps {
    disabled?: boolean
    onChange: (text: string) => void
}

const SpeechToTextComponent = ({ disabled, onChange }: SpeechToTextComponentProps) => {
    const { showToast } = useToastContext()
    const [isRecording, setIsRecording] = useState(false)
    const [isProcessing, setIsProcessing] = useState(false)

    const mediaRecorderRef = useRef<MediaRecorder | null>(null)
    const audioChunksRef = useRef<Blob[]>([])
    const audioContextRef = useRef<AudioContext | null>(null)
    const streamRef = useRef<MediaStream | null>(null)

    const [interruptAudio] = useRecoilState(interruptAudioAtom)
    const [_, setIsLoading] = useParsingAudioLoading()
    useEffect(() => {
        stopRecording(null)
    }, [interruptAudio])

    /**
     * Cleans up all audio resources
     */
    const cleanupResources = useCallback(async () => {
        // Stop all media tracks
        if (streamRef.current) {
            streamRef.current.getTracks().forEach((track) => track.stop())
            streamRef.current = null
        }

        // Close audio context
        if (audioContextRef.current && audioContextRef.current.state !== "closed") {
            await audioContextRef.current.close()
            audioContextRef.current = null
        }

        // Clear media recorder
        mediaRecorderRef.current = null
    }, [])

    /**
     * Sends audio to speech-to-text API
     */
    const convertSpeechToText = useCallback(
        async (audioBlob: Blob) => {
            try {
                setIsLoading(true)
                const formData = new FormData()
                formData.append("file", audioBlob, "recording.wav")
                const res = await getVoice2TextApi(formData)
                const responseData = res.data
                const transcript = responseData || ""

                // Pass recognized text to parent component
                if (!transcript) {
                    return showToast({ message: "No text recognized", status: "info" })
                }
                onChange(transcript)
            } catch (err) {
                console.error("Speech recognition error:", err)
                showToast({ message: "语音识别不可用，请联系管理员", status: "error" })
            } finally {
                setIsProcessing(false)
                setIsLoading(false)
            }
        },
        [onChange, showToast],
    )

    /**
     * Starts audio recording with optimized settings
     */
    const startRecording = useCallback(async (e) => {
        try {
            e.preventDefault();
            audioChunksRef.current = []
            setIsProcessing(false)
            // Ten minute recording limit
            setTimeout(() => {
                setIsProcessing(true)
                mediaRecorderRef.current?.stop()
                setIsRecording(false)
            }, 600000)

            // Request microphone access with noise reduction settings
            const stream = await navigator.mediaDevices.getUserMedia({
                audio: {
                    sampleRate: 44100,
                    channelCount: 1,
                    echoCancellation: true,
                    noiseSuppression: true,
                    autoGainControl: true,
                },
            })

            streamRef.current = stream

            // Initialize AudioContext for optimized encoding
            const audioContext = new (window.AudioContext || (window as any).webkitAudioContext)({
                sampleRate: 44100,
            })
            audioContextRef.current = audioContext

            // Initialize MediaRecorder with optimal codec
            const options = { mimeType: "audio/webm; codecs=opus" }
            const mediaRecorder = new MediaRecorder(stream, options)
            mediaRecorderRef.current = mediaRecorder

            // Collect audio data chunks
            mediaRecorder.ondataavailable = (event) => {
                if (event.data.size > 0) {
                    audioChunksRef.current.push(event.data)
                }
            }

            // Handle recording stop
            mediaRecorder.onstop = async () => {
                if (window.interruptAudio) {
                    setIsProcessing(false)
                    return cleanupResources()
                }
                try {
                    setIsProcessing(true)

                    // Convert recorded audio to WAV format
                    const rawBlob = new Blob(audioChunksRef.current, { type: "audio/webm" })
                    const wavBlob = await convertBlobToWav(rawBlob)

                    // Send to speech-to-text API
                    await convertSpeechToText(wavBlob)
                } catch (conversionError) {
                    console.error("Audio conversion failed:", conversionError)
                    showToast({ message: "Audio format conversion failed, please try again", status: "error" })
                    setIsProcessing(false)
                } finally {
                    await cleanupResources()
                }
            }

            // Start recording
            mediaRecorder.start()
            setIsRecording(true)
        } catch (err) {
            console.error("Microphone access error:", err)
            showToast({ message: "Microphone access denied", status: "error" })
            await cleanupResources()
        }
    }, [convertSpeechToText, showToast, cleanupResources, interruptAudio])

    /**
     * Stops the current recording
     */
    const stopRecording = useCallback((e) => {
        e?.preventDefault();
        if (isProcessing) return

        if (mediaRecorderRef.current && isRecording) {
            setIsProcessing(true)
            mediaRecorderRef.current.stop()
            setIsRecording(false)
        }
    }, [isRecording, isProcessing])

    return (
        <div className="relative z-10">
            {/* Recording control button */}
            <div className={disabled ? 'cursor-not-allowed' : ''}>
                {isProcessing && <LoaderCircle size={30} className="animate-spin p-1" />}
                {!isProcessing && isRecording && (
                    <Button size={'icon'} variant='outline' onClick={stopRecording} className="rounded-full w-8 h-8">
                        {/* <AudioLines size={18} className="animate-pulse" /> */}
                        <VoiceRecordingIcon onClick={() => { }} />
                    </Button>
                )}
                {!isProcessing && !isRecording && (
                    <Button size={'icon'} disabled={disabled} onClick={startRecording} className="rounded-full w-8 h-8">
                        <Mic size={18} className="" />
                    </Button>
                )}
            </div>

            {/* Recording pulse animation */}
            {isRecording && <div className="pulse-ring"></div>}
        </div>
    )
}

// PropTypes for runtime validation
SpeechToTextComponent.propTypes = {
    onChange: PropTypes.func.isRequired,
}

export default SpeechToTextComponent
