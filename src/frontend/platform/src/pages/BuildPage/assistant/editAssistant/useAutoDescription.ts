import { useAssistantStore } from "@/store/assistantStore";
import { useEffect, useRef } from "react";

/**
 * Streams an auto-generated description into a newly created assistant.
 * Creation no longer waits for this model call; the backend stores the result.
 */
export function useAutoDescription(enabled: boolean) {
    const id = useAssistantStore((state) => state.assistantState.id)
    const desc = useAssistantStore((state) => state.assistantState.desc)
    const prompt = useAssistantStore((state) => state.assistantState.prompt)
    const setGeneratedDesc = useAssistantStore((state) => state.setGeneratedDesc)
    const sourceRef = useRef<EventSource | null>(null)
    const startedRef = useRef(false)

    useEffect(() => {
        if (!enabled || startedRef.current) return
        if (!id || desc || !prompt) return
        startedRef.current = true

        let text = ''
        const source = new EventSource(
            `${__APP_ENV__.BASE_URL}/api/v1/assistant/auto/description?assistant_id=${encodeURIComponent(String(id))}`
        )
        sourceRef.current = source
        source.onmessage = (event) => {
            if (!event.data) return
            const data = JSON.parse(event.data)
            if (data.type === 'description') {
                text += data.message
                setGeneratedDesc(text.trimStart())
            } else if (data.type === 'end') {
                // A failing model is already reported by the auto-optimization dialog
                // that opens for new assistants, so only log here to avoid a duplicate toast.
                if (data.message) console.warn('assistant description generation failed:', data.message)
                if (text) setGeneratedDesc(text.trim())
                source.close()
            }
        }
        source.onerror = () => source.close()
    }, [enabled, id, desc, prompt, setGeneratedDesc])

    useEffect(() => () => sourceRef.current?.close(), [])
}
