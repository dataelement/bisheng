import { type LinsightInfo, SopStatus } from '~/store/linsight';

export function getContinueFailureUpdate(
    originalLinsight: LinsightInfo | undefined,
    modelId: string | number | undefined,
    error: unknown,
): Partial<LinsightInfo> {
    if (modelId != null && originalLinsight) {
        return {
            history: originalLinsight.history,
            question: originalLinsight.question,
            tasks: originalLinsight.tasks,
            sessionSteps: originalLinsight.sessionSteps,
            output_result: originalLinsight.output_result,
            file_list: originalLinsight.file_list,
            taskError: originalLinsight.taskError,
            taskErrorInfo: originalLinsight.taskErrorInfo,
            status: originalLinsight.status,
        };
    }
    return { status: SopStatus.Stoped, taskError: String(error) };
}
