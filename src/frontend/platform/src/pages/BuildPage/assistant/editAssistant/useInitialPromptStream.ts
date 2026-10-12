import { useToast } from "@/components/bs-ui/toast/use-toast";
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

/**
 * Streams the optimized prompt of a newly created assistant straight into the
 * portrait panel, then fills its (still empty) opening lines and questions.
 * Tool and skill selection is left to the manual auto-optimization dialog.
 */
export function useInitialPromptStream(enabled: boolean) {
    const { toast } = useToast()
    const id = useAssistantStore((state) => state.assistantState.id)
    const prompt = useAssistantStore((state) => state.assistantState.prompt)
    const dispatchAssistant = useAssistantStore((state) => state.dispatchAssistant)
    const [streaming, setStreaming] = useState(false)
    const sourceRef = useRef<EventSource | null>(null)
    const startedRef = useRef(false)

    useEffect(() => {
        if (!enabled || startedRef.current || !id || !prompt) return
        startedRef.current = true
        const originalPrompt = prompt

        const start = async () => {
            setStreaming(true)
            const res = await getAssistantOptimizeTaskApi(String(id), originalPrompt) as unknown as { task_id: string }
            const source = new EventSource(`${__APP_ENV__.BASE_URL}/api/v1/assistant/auto?task_id=${res.task_id}`)
            sourceRef.current = source
            let generated = ''
            const finish = () => {
                source.close()
                setStreaming(false)
            }

            source.onmessage = (event) => {
                if (!event.data) return
                const data = JSON.parse(event.data)
                switch (data.type) {
                    case 'prompt':
                        generated += data.message
                        // Thinking models send empty chunks first; keep the user's prompt until text arrives
                        if (!generated.trim()) break
                        dispatchAssistant('setPrompt', { prompt: generated.replace('```markdown', '') })
                        break
                    case 'guide_word':
                        dispatchAssistant('setGuideword', { guide_word: data.message })
                        break
                    case 'guide_question':
                        dispatchAssistant('setQuestion', { guide_question: [...(data.message || []), ''] })
                        finish()
                        break
                    case 'end':
                        if (!data.message) break
                        // The prompt is replaced only once generation succeeded; keep what the user wrote
                        if (!generated.trim()) dispatchAssistant('setPrompt', { prompt: originalPrompt })
                        toast({ title: t('tip'), variant: 'error', description: streamErrorMessage(data) })
                        finish()
                        break
                }
            }
            source.onerror = () => {
                if (!generated.trim()) dispatchAssistant('setPrompt', { prompt: originalPrompt })
                finish()
            }
        }
        start().catch(() => setStreaming(false))
    }, [enabled, id, prompt, dispatchAssistant, toast])

    useEffect(() => () => sourceRef.current?.close(), [])

    return streaming
}
