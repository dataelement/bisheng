
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
            if (res.status_code === 404) {
                console.log('404 page')
                return navigate('/404', { replace: true })
            }
            setType(res.data.resource_type)
            setShareInfo(res.data)
        })
    }, [])

    if (!shareInfo) return null

    switch (type) {
        case 'linsight_session':
            return <Sop id={shareInfo.resource_id} vid={vid} shareToken={shareToken} />
        case 'workbench_chat':
            return <ChatView id={shareInfo.resource_id} shareToken={shareToken} />;
        default:
            return <AppChat
                chatId={shareInfo.resource_id}
                flowId={shareInfo.meta_data.flowId}
                shareToken={shareToken}
                flowType={Apptypes[type]}
            />
    }
};
