import {
    getKnowledgeParseQueuePositionsApi,
    type KnowledgeFile,
} from "~/api/knowledge";

const MAX_QUEUE_POSITION_FILE_IDS = 100;
const DEFAULT_UPLOAD_SUCCESS_MESSAGE = "上传成功";

function chunkFileIds(fileIds: number[]): number[][] {
    const chunks: number[][] = [];
    for (let index = 0; index < fileIds.length; index += MAX_QUEUE_POSITION_FILE_IDS) {
        chunks.push(fileIds.slice(index, index + MAX_QUEUE_POSITION_FILE_IDS));
    }
    return chunks;
}

export async function resolvePortalUploadSuccessMessage(
    knowledgeId: string | number,
    registeredFiles: KnowledgeFile[],
): Promise<string> {
    const fileIds = Array.from(new Set(
        registeredFiles
            .map((file) => Number(file.id))
            .filter((fileId) => Number.isInteger(fileId) && fileId > 0),
    ));
    if (!fileIds.length || fileIds.length !== registeredFiles.length) {
        return DEFAULT_UPLOAD_SUCCESS_MESSAGE;
    }

    try {
        const responses = await Promise.all(
            chunkFileIds(fileIds).map((chunk) => getKnowledgeParseQueuePositionsApi(knowledgeId, chunk)),
        );
        const queuedPositions = responses.flatMap((response) => response.items
            .filter((item) => item.state === "queued" && item.aheadWaitingCount !== null)
            .map((item) => ({
                aheadWaitingCount: item.aheadWaitingCount as number,
                waitingCount: response.waitingCount,
            })));
        if (!queuedPositions.length) return DEFAULT_UPLOAD_SUCCESS_MESSAGE;

        const foremost = queuedPositions.reduce((current, candidate) => (
            candidate.aheadWaitingCount < current.aheadWaitingCount ? candidate : current
        ));
        const currentPosition = foremost.aheadWaitingCount + 1;
        if (
            foremost.aheadWaitingCount <= 0
            || foremost.waitingCount === null
            || foremost.waitingCount < currentPosition
        ) {
            return DEFAULT_UPLOAD_SUCCESS_MESSAGE;
        }
        return `上传成功，${registeredFiles.length} 个文件已进入队列，最前第 ${currentPosition}/${foremost.waitingCount} 名`;
    } catch {
        return DEFAULT_UPLOAD_SUCCESS_MESSAGE;
    }
}
