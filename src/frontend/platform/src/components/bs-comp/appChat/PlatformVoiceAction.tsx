import { AudioPlayComponent } from '@/components/voiceFunction/audioPlayButton';
import { useWorkbenchRuntimeConfig } from '@/hooks/useWorkbenchRuntimeConfig';
export function PlatformVoiceAction({ id, text }: { id: string; text: string }) {
    const { data } = useWorkbenchRuntimeConfig();
    return data?.tts_model?.id && text ? <AudioPlayComponent compact messageId={id} msg={text} /> : null;
}
