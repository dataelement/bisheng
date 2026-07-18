import { useCallback, useEffect, useRef } from 'react';
import { useLocation, useNavigate, useParams } from 'react-router-dom';
import { useSetRecoilState } from 'recoil';
import { getAppConversationsApi } from '~/api/apps';
import { useLocalize } from '~/hooks';
import { generateUUID } from '~/utils';
import {
    deriveAppChatOriginFromEntry,
    isAllowedAppChatReturn,
    writeAppChatOrigin,
    writeAppChatReturnTo,
} from '~/pages/appChat/appChatOrigin';
import { ChatEmptyState } from './components/ChatEmptyState';
import { appConversationsState } from './store/appSidebarAtoms';

/**
 * Landing route for `/app/:fid/:type` (no chatId).
 *
 * Two entry modes:
 * - Normal entry (from explore card): resolve to the most recent conversation,
 *   or create a fresh one if the user has none yet. Redirects to
 *   `/app/{chatId}/:fid/:type` and this component unmounts.
 * - Post-delete-all (`location.state.fromDelete === true`): stays mounted and
 *   renders the empty-state panel; no auto-create.
 */
export default function AppChatEntry() {
    const { fid, type } = useParams();
    const navigate = useNavigate();
    const location = useLocation();
    const localize = useLocalize();
    const setConversations = useSetRecoilState(appConversationsState);
    const fromDelete = (location.state as { fromDelete?: boolean } | null)?.fromDelete === true;
    const resolvedRef = useRef(false);

    // Flow-level info (name / logo / description) is loaded by SideNav's useAppSidebar
    // hook into currentAppInfoState, so the sidebar card is populated here too.

    const buildQs = useCallback(() => {
        const qs = new URLSearchParams(location.search || '');
        qs.delete('from');
        qs.delete('entry');
        const normalized = qs.toString();
        return normalized ? `?${normalized}` : '';
    }, [location.search]);

    const deriveReturnTo = useCallback(() => {
        const qs = new URLSearchParams(location.search || '');
        const returnTo = qs.get('returnTo');
        if (isAllowedAppChatReturn(returnTo)) return returnTo;
        const sr = (location.state as { appSurfaceReturn?: string } | null)?.appSurfaceReturn;
        if (isAllowedAppChatReturn(sr)) return sr;
        return null;
    }, [location.search, location.state]);

    const navigateToNewChat = useCallback(() => {
        if (!fid || !type) return;
        const chatId = generateUUID(32);
        const origin = deriveAppChatOriginFromEntry(location.search, location.state);
        if (origin) writeAppChatOrigin(chatId, origin);
        const returnTo = deriveReturnTo();
        if (returnTo) writeAppChatReturnTo(chatId, returnTo);
        // Seed sidebar placeholder so the new chat shows up immediately.
        setConversations((prev) => [
            {
                id: chatId,
                title: localize('com_ui_new_chat'),
                flowId: fid,
                flowType: Number(type),
                updatedAt: new Date().toISOString(),
                createdAt: new Date().toISOString(),
            },
            ...prev,
        ]);
        navigate(`/app/${chatId}/${fid}/${type}${buildQs()}`, {
            replace: true,
            state: location.state,
        });
    }, [fid, type, localize, setConversations, navigate, buildQs, location.search, location.state, deriveReturnTo]);

    useEffect(() => {
        if (fromDelete || resolvedRef.current || !fid || !type) return;
        resolvedRef.current = true;
        (async () => {
            try {
                const res = await getAppConversationsApi(fid, 1, 100) as { data?: { list?: Array<{ chat_id: string }> } };
                const list = res.data?.list ?? [];
                if (list.length > 0) {
                    const chatId = list[0].chat_id;
                    const origin = deriveAppChatOriginFromEntry(location.search, location.state);
                    if (origin) writeAppChatOrigin(chatId, origin);
                    const returnTo = deriveReturnTo();
                    if (returnTo) writeAppChatReturnTo(chatId, returnTo);
                    navigate(`/app/${chatId}/${fid}/${type}${buildQs()}`, {
                        replace: true,
                        state: location.state,
                    });
                } else {
                    navigateToNewChat();
                }
            } catch {
                navigateToNewChat();
            }
        })();
    }, [fromDelete, fid, type, navigate, navigateToNewChat, buildQs, deriveReturnTo, location.search, location.state]);

    if (fromDelete) {
        return (
            <div className="relative h-full flex flex-col">
                <div className="min-h-0 flex-1 flex flex-col">
                    <ChatEmptyState onNewChat={navigateToNewChat} />
                </div>
            </div>
        );
    }

    return null;
}
