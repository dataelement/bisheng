// @ts-strict-ignore

import { isApiError } from "@bisheng/api-client";
import { Button } from "@bisheng/ui";
import { showApiError } from "~/api/request";
import { useLocalize } from "~/hooks";
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { getShareParamsApi } from "~/api";
import ChatView from "~/components/Chat/ChatView";
import Sop from "~/components/Sop";
import AppChat from "./appChat";
import { generateUUID } from "~/utils";

const Apptypes = {
    'skill': 1,
    'assistant': 5,
    'workflow': 10
}

export default function Share() {
    const { token: shareToken, vid } = useParams()
    const [type, setType] = useState('')
    const [shareInfo, setShareInfo] = useState(null)
    const navigate = useNavigate()
    const localize = useLocalize();
    const [error, setError] = useState<unknown>(null);
    const loadShare = () => {
        setError(null);
        void getShareParamsApi(shareToken).then(res => {
            setType(res.data.resource_type);
            setShareInfo(res.data);
        }).catch(cause => {
            if (isApiError(cause) && (cause.status_code === 404 || cause.httpStatus === 404)) {
                navigate('/404', { replace: true });
                return;
            }
            setError(cause);
            showApiError(cause);
        });
    };

    useEffect(() => {
        // Handle app share links: token format is "app_{applicationId}_{flowType}"
        if (shareToken?.startsWith('app_')) {
            const slug = shareToken.substring(4); // Remove "app_" prefix
            const lastUnderscore = slug.lastIndexOf('_');
            if (lastUnderscore !== -1) {
                const applicationId = slug.substring(0, lastUnderscore);
                const flowType = slug.substring(lastUnderscore + 1);
                const chatId = generateUUID(32);
                navigate(`/app/${chatId}/${applicationId}/${flowType}`, { replace: true });
                return;
            }
        }

        loadShare();
    }, [])

    if (error) return (
        <div role="alert">
            <p>{error instanceof Error ? error.message : localize('com_ui_error')}</p>
            <Button variant="outlined" onClick={loadShare}>{localize('com_ui_retry')}</Button>
        </div>
    );
    if (!shareInfo) return null

    const content = (() => {
        switch (type) {
            case 'linsight_session':
                // Parent uses items-start (no cross-axis stretch); Sop's root
                // lacks w-full so it collapses to content width. Wrap to fill.
                return (
                    <div className="h-full w-full">
                        <Sop id={shareInfo.resource_id} vid={vid} shareToken={shareToken} />
                    </div>
                )
            case 'workbench_chat':
                return <ChatView id={shareInfo.resource_id} shareToken={shareToken} />;
            default:
                // Same wrapper trick as the Sop branch: parent uses
                // items-start so AppChat's root (which has h-full but no
                // w-full) collapses to content width and the inner
                // mx-auto/max-w-[800px] then "centers" inside that
                // shrunken column — visually left-stuck. Wrap to fill so
                // the inner mx-auto centers against the full viewport.
                return (
                    <div className="h-full w-full">
                        <AppChat
                            chatId={shareInfo.resource_id}
                            flowId={shareInfo.meta_data.flowId}
                            shareToken={shareToken}
                            flowType={Apptypes[type]}
                        />
                    </div>
                )
        }
    })();

    // Definite viewport height (NOT min-h, and NOT flex-1/basis-0 — basis-0 would
    // override the height to 0 in a flex parent) + overflow-hidden, so the share
    // page never scrolls at the document level. The inner ChatView / Sop / AppChat
    // then drive their own scroll areas (chat messages and the citation panel
    // scroll independently instead of together).
    return (
        <div className="flex h-[100dvh] w-full flex-col items-start gap-[10px] self-stretch overflow-hidden p-2">
            {content}
        </div>
    );
};
