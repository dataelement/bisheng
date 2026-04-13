import { useCallback, useEffect, useRef } from 'react';
import { useLocation, useNavigate, useParams } from 'react-router-dom';
import { useSetRecoilState } from 'recoil';
import { getAppConversationsApi } from '~/api/apps';
import { useLocalize } from '~/hooks';
import { generateUUID } from '~/utils';
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

    const buildQs = useCallback(() => {
        const from = new URLSearchParams(location.search).get('from');
        return from ? `?from=${from}` : '';
    }, [location.search]);

    const navigateToNewChat = useCallback(() => {
        if (!fid || !type) return;
        const chatId = generateUUID(32);
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
        navigate(`/app/${chatId}/${fid}/${type}${buildQs()}`, { replace: true });
    }, [fid, type, localize, setConversations, navigate, buildQs]);

    useEffect(() => {
        if (fromDelete || resolvedRef.current || !fid || !type) return;
        resolvedRef.current = true;
        (async () => {
            try {
                const res = await getAppConversationsApi(fid, 1, 100) as { data?: { list?: Array<{ chat_id: string }> } };
                const list = res.data?.list ?? [];
                if (list.length > 0) {
                    // Backend returns sessions sorted by update_time desc — list[0] is most recent.
                    navigate(`/app/${list[0].chat_id}/${fid}/${type}${buildQs()}`, { replace: true });
                } else {
                    navigateToNewChat();
                }
            } catch {
                navigateToNewChat();
            }
        })();
    }, [fromDelete, fid, type, navigate, navigateToNewChat, buildQs]);

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
