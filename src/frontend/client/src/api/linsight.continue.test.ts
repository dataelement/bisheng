/** @jest-environment node */

import request from './request';
import { continueLinsight } from './linsight';

jest.mock('./request', () => ({
    __esModule: true,
    default: {
        post: jest.fn(),
    },
}));

const mockedRequest = request as jest.Mocked<typeof request>;

describe('continueLinsight', () => {
    beforeEach(() => {
        jest.clearAllMocks();
    });

    it('keeps the existing payload when no replacement model is supplied', async () => {
        mockedRequest.post.mockResolvedValueOnce({ data: true });

        await continueLinsight('version-1', 'retry question');

        expect(mockedRequest.post).toHaveBeenCalledWith(
            '/api/v1/linsight/workbench/continue',
            { session_version_id: 'version-1', question: 'retry question' },
        );
    });

    it('adds model_id only for switch-and-retry', async () => {
        mockedRequest.post.mockResolvedValueOnce({ data: true });

        await continueLinsight('version-1', 'retry question', '22');

        expect(mockedRequest.post).toHaveBeenCalledWith(
            '/api/v1/linsight/workbench/continue',
            { session_version_id: 'version-1', question: 'retry question', model_id: '22' },
        );
    });
});
