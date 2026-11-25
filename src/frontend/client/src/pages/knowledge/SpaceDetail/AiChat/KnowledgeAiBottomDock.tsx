import { useRecoilValue } from "recoil";
import store from "~/store";
import { KnowledgeAskBar } from "./KnowledgeAskBar";

import { useSpaceCapabilities } from '../../hooks/useSpaceCapabilities';

interface KnowledgeAiBottomDockProps {
    spaceId: string;
    spaceName: string;
}

/** All layouts hand questions to the main chat and its global conversation list. */
export function KnowledgeAiBottomDock({ spaceId, spaceName }: KnowledgeAiBottomDockProps) {
    const chatModel = useRecoilValue(store.chatModel);
    const { tagScope } = useSpaceCapabilities(spaceId);
    return <KnowledgeAskBar nativeTagScope={tagScope.kind === 'native' ? tagScope.key : undefined} spaceId={spaceId} spaceName={spaceName} modelValue={chatModel.id} />;
}
