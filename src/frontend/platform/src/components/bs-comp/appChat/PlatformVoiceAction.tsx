import { AudioPlayComponent } from '@/components/voiceFunction/audioPlayButton';
import { useLinsightConfig } from '@/pages/ModelPage/manage/tabs/WorkbenchModel';
export function PlatformVoiceAction({ id, text }: { id: string; text: string }) {
    const { data } = useLinsightConfig();
    return data?.tts_model?.id && text ? <AudioPlayComponent compact messageId={id} msg={text} /> : null;
}
