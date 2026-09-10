import {
    isRetryableRegistrationFailure,
    registerUploadedStagesWithRetry,
} from './fileUploadUtils';

/**
 * Registering staged uploads retried on any failure, including a considered
 * rejection. Going over a space's size quota rolls the transaction back and
 * cleans the staged object up, so the retry had nothing left to register and
 * came back with a raw S3 "NoSuchKey" — business code 500, which the response
 * interceptor reads as a dead backend and covers the screen with the
 * maintenance overlay. The uploader was told the service was down. They were
 * over quota, and the first answer said so.
 */

jest.mock('~/api/request', () => ({
    __esModule: true,
    default: { post: jest.fn(), get: jest.fn() },
    translateApiErrorMessage: (input: { status_message?: string }) => input?.status_message ?? '',
}));

const QUOTA_EXCEEDED = 18024;

function codedError(status_code: number, status_message = 'File size limit exceeded') {
    return Object.assign(new Error(status_message), { status_code, statusCode: status_code });
}

describe('a considered rejection is not repeated', () => {
    it('treats a business code as final', () => {
        expect(isRetryableRegistrationFailure(codedError(QUOTA_EXCEEDED))).toBe(false);
    });

    it('treats a call that never got an answer as retryable', () => {
        expect(isRetryableRegistrationFailure(new Error('Network Error'))).toBe(true);
    });

    it('does not ask again after a quota rejection', async () => {
        const register = jest.fn().mockRejectedValue(codedError(QUOTA_EXCEEDED));

        await expect(
            registerUploadedStagesWithRetry({
                spaceId: '293',
                uploadIds: ['u-1'],
                parentId: null,
                register,
            }),
        ).rejects.toMatchObject({ status_code: QUOTA_EXCEEDED });

        // The second call is what turned "over quota" into "service unavailable".
        expect(register).toHaveBeenCalledTimes(1);
    });

    it('still retries once when the call itself fell over', async () => {
        const register = jest
            .fn()
            .mockRejectedValueOnce(new Error('Network Error'))
            .mockResolvedValueOnce([]);

        await expect(
            registerUploadedStagesWithRetry({
                spaceId: '293',
                uploadIds: ['u-1'],
                parentId: null,
                register,
            }),
        ).resolves.toEqual([]);

        expect(register).toHaveBeenCalledTimes(2);
    });
});
