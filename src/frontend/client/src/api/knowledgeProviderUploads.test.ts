/**
 * @jest-environment node
 */
import {
  parentDirOfRelativePath,
  prepareProviderFolderUpload,
  readFileCapabilities,
} from './knowledgeProviderUploads';

jest.mock('./request', () => ({
  __esModule: true,
  default: {
    getResponse: jest.fn(),
    postResponse: jest.fn(),
    post: jest.fn(),
    get: jest.fn(),
  },
  prepareBrowserHeaders: jest.fn(),
}));

import request, { prepareBrowserHeaders } from './request';

const mockedRequest = request as jest.Mocked<typeof request>;
const mockedHeaders = prepareBrowserHeaders as jest.MockedFunction<typeof prepareBrowserHeaders>;

describe('readFileCapabilities folder_upload', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('sets providerFolderUpload when folder_upload is supported', async () => {
    mockedRequest.getResponse.mockResolvedValue({
      headers: { 'x-management-tenant': '3' },
      data: {
        status_code: 200,
        data: {
          provider_key: 'weknora',
          capability_revision: 7,
          generation: 2,
          capabilities: {
            upload: 'supported',
            folder_upload: 'supported',
            preview: 'conditional',
            preview_representation: 'text_excerpt',
          },
        },
      },
    });
    await expect(readFileCapabilities('14')).resolves.toMatchObject({
      native: false,
      providerUpload: true,
      providerFolderUpload: true,
      tenant: '3',
    });
  });

  it('does not admit folder upload when folder_upload is unverified', async () => {
    mockedRequest.getResponse.mockResolvedValue({
      headers: { 'x-management-tenant': '3' },
      data: {
        status_code: 200,
        data: {
          provider_key: 'weknora',
          capability_revision: 7,
          capabilities: { upload: 'unverified', folder_upload: 'unverified', preview: 'conditional' },
        },
      },
    });
    await expect(readFileCapabilities('14')).resolves.toMatchObject({
      providerUpload: false,
      providerFolderUpload: false,
    });
  });
});

describe('parentDirOfRelativePath', () => {
  it('binds nested files to their relative directory for prepare folder_id lookup', () => {
    const folderByDir = new Map([
      ['docs', '101'],
      ['docs/sub', '102'],
    ]);
    expect(folderByDir.get(parentDirOfRelativePath('docs/a.txt'))).toBe('101');
    expect(folderByDir.get(parentDirOfRelativePath('docs/sub/b.txt'))).toBe('102');
    expect(folderByDir.get(parentDirOfRelativePath('docs\\sub\\c.txt'))).toBe('102');
  });
});

describe('prepareProviderFolderUpload', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockedHeaders.mockResolvedValue({ 'X-Management-Tenant': '3' });
  });

  it('returns verified folder map for parent_id binding', async () => {
    mockedRequest.postResponse.mockResolvedValue({
      data: {
        status_code: 200,
        data: {
          root_name: 'docs',
          folders: [
            { relative_dir: 'docs', folder_id: 101 },
            { relative_dir: 'docs/sub', folder_id: 102 },
          ],
        },
      },
    });
    await expect(
      prepareProviderFolderUpload('14', { parent_id: null, paths: ['docs/a.txt', 'docs/sub/b.txt'] }, '3'),
    ).resolves.toEqual({
      root_name: 'docs',
      folders: [
        { relative_dir: 'docs', folder_id: 101 },
        { relative_dir: 'docs/sub', folder_id: 102 },
      ],
    });
  });

  it('rejects when tenant scope drifts', async () => {
    mockedHeaders.mockResolvedValue({ 'X-Management-Tenant': '9' });
    await expect(
      prepareProviderFolderUpload('14', { paths: ['docs/a.txt'] }, '3'),
    ).rejects.toThrow('Upload scope changed');
    expect(mockedRequest.postResponse).not.toHaveBeenCalled();
  });
});
