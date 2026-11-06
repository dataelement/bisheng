import { notification } from '@bisheng/ui';

import { getAssistantOptimizeTaskApi } from "@/controllers/API/assistant";
import { useAssistantStore } from "@/store/assistantStore";
import { t } from "i18next";
import { useEffect, useRef, useState } from "react";

interface StreamEndEvent {
    message?: string
    code?: number
    data?: Record<string, unknown>
}

// Business errors carry a code: show its localized copy, fall back to the raw message
export function streamErrorMessage(event: StreamEndEvent): string {
    if (!event.code) return event.message || ''
    return t(`api_errors:${event.code}`, { ...(event.data || {}), defaultValue: event.message })
}

// The model wraps the prompt in a ```markdown fence whose pieces can arrive in separate chunks
function stripMarkdownFence(text: string): string {
    return text.replace(/^\s*(```)?\s*markdown\s*\n/i, '').replace(/\n?```\s*$/, '')
}

/**
 * Streams the optimized prompt of a newly created assistant straight into the
 * portrait panel, then fills its (still empty) opening lines and questions.
 * Tool and skill selection is left to the manual auto-optimization dialog.
 * Returns whether the prompt is still streaming (panel read-only) and whether
 * any generation is still running (opening lines continue after the prompt).
 */
export function useInitialPromptStream(enabled: boolean) {

    const id = useAssistantStore((state) => state.assistantState.id)
    const prompt = useAssistantStore((state) => state.assistantState.prompt)
    const dispatchAssistant = useAssistantStore((state) => state.dispatchAssistant)
    const [streaming, setStreaming] = useState(false)
    const [promptStreaming, setPromptStreaming] = useState(false)
    const sourceRef = useRef<EventSource | null>(null)
    const startedRef = useRef(false)

    useEffect(() => {
        if (!enabled || startedRef.current || !id || !prompt) return
        startedRef.current = true
        const originalPrompt = prompt

        const start = async () => {
            setStreaming(true)
            setPromptStreaming(true)
            const res = await getAssistantOptimizeTaskApi(String(id), originalPrompt) as unknown as { task_id: string }
            const source = new EventSource(`${__APP_ENV__.BASE_URL}/api/v1/assistant/auto?task_id=${res.task_id}`)
            sourceRef.current = source
            let generated = ''
            const finish = () => {
                source.close()
                setStreaming(false)
                setPromptStreaming(false)
            }

            source.onmessage = (event) => {
                if (!event.data) return
                const data = JSON.parse(event.data)
                switch (data.type) {
                    case 'prompt':
                        generated += data.message
                        // Thinking models send empty chunks first; keep the user's prompt until text arrives
                        if (!generated.trim()) break
                        dispatchAssistant('setPrompt', { prompt: stripMarkdownFence(generated) })
                        break
                    case 'guide_word':
                        dispatchAssistant('setGuideword', { guide_word: data.message })
                        break
                    case 'guide_question':
                        dispatchAssistant('setQuestion', { guide_question: [...(data.message || []), ''] })
                        finish()
                        break
                    case 'end':
                        // The first clean end closes the prompt; the user may edit it while the opening lines generate
                        if (!data.message) {
                            setPromptStreaming(false)
                            break
                        }
                        // The prompt is replaced only once generation succeeded; keep what the user wrote
                        if (!generated.trim()) dispatchAssistant('setPrompt', { prompt: originalPrompt })
                        notification.open({ type: 'error', title: String(t('tip') ?? ''), description: String(streamErrorMessage(data) ?? '') })
                        finish()
                        break
                }
            }
            source.onerror = () => {
                if (!generated.trim()) dispatchAssistant('setPrompt', { prompt: originalPrompt })
                finish()
            }
        }
        start().catch(() => {
            setStreaming(false)
            setPromptStreaming(false)
        })
    }, [enabled, id, prompt, dispatchAssistant])

    useEffect(() => () => sourceRef.current?.close(), [])

    return { streaming, promptStreaming }
}
