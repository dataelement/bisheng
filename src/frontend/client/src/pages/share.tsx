
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

        getShareParamsApi(shareToken).then(res => {
            if ([404, 500].includes(res.status_code)) {
                console.log('404 page')
                return navigate('/404', { replace: true })
            }
            setType(res.data.resource_type)
            setShareInfo(res.data)
        })
    }, [])

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

    return (
        <div className="flex min-h-[100dvh] w-full flex-1 basis-0 flex-col items-start gap-[10px] self-stretch p-2">
            {content}
        </div>
    );
};
