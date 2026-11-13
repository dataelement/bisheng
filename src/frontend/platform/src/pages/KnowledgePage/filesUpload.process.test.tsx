import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, expect, it, vi } from 'vitest';
import FilesUpload from './filesUpload';

const { process, uploadFiles } = vi.hoisted(() => ({ process: vi.fn(), uploadFiles: [
  { id: 'a', fileName: 'a.pdf', file_path: '/tmp/a.pdf', preview_upload_ref: 'signed-a' },
  { id: 'b', fileName: 'b.pdf', file_path: '/tmp/b.pdf' },
] }));
vi.mock('@/controllers/API', () => ({ subUploadLibFile: process, retryKnowledgeFileApi: vi.fn() }));
vi.mock('@/controllers/API/permission', () => ({ checkResourceActionApi: vi.fn().mockResolvedValue({ allowed: true }) }));
vi.mock('@/components/bs-comp/knowledgeUploadComponent', () => ({ default: ({ onFileChange }) => <button onClick={() => onFileChange(uploadFiles, [])}>finish upload</button> }));
vi.mock('./components/FileUploadStep2', async () => {
  const React = await import('react');
  return { default: React.forwardRef(({ onNext, resultFiles }: { onNext: (step: number, config: object) => void; resultFiles: typeof uploadFiles }, ref) => {
    React.useImperativeHandle(ref, () => ({ handleNext: () => onNext(3, { rules: { knowledgeId: 1, separator: ['\\n'], separatorRule: ['after'], chunkSize: 1000, chunkOverlap: 0, fileList: resultFiles.map(file => ({ filePath: file.file_path, previewUploadRef: file.preview_upload_ref, excelRule: {} })) }, applyEachCell: true, cellGeneralConfig: {} }) }));
    return <button onClick={() => onNext(3, { rules: { knowledgeId: 1, separator: ['\\n'], separatorRule: ['after'], chunkSize: 1000, chunkOverlap: 0, fileList: resultFiles.map(file => ({ filePath: file.file_path, previewUploadRef: file.preview_upload_ref, excelRule: {} })) }, applyEachCell: true, cellGeneralConfig: {} })}>continue rules</button>;
  }) };
});
vi.mock('./components/PreviewResult', () => ({ default: () => <div>preview</div> }));
vi.mock('./components/FileUploadStep4', () => ({ default: () => null }));

beforeEach(() => { process.mockReset().mockResolvedValue([]); });
function setup() {
  render(<MemoryRouter initialEntries={['/filelib/1/upload']}><Routes><Route path="/filelib/:id/upload" element={<FilesUpload />} /></Routes></MemoryRouter>);
}

it('includes the upload reference in direct process requests without changing paths', async () => {
  setup();
  fireEvent.click(await screen.findByText('finish upload'));
  fireEvent.click(screen.getByRole('button', { name: 'uploadDirectly' }));
  await waitFor(() => expect(process).toHaveBeenCalled());
  expect(process.mock.calls[0][0].file_list).toMatchObject([
    { file_path: '/tmp/a.pdf', preview_upload_ref: 'signed-a' },
    { file_path: '/tmp/b.pdf' },
  ]);
});

it('includes the upload reference in wizard process requests without changing paths', async () => {
  setup();
  fireEvent.click(await screen.findByText('finish upload'));
  fireEvent.click(screen.getByRole('button', { name: /nextStep/ }));
  fireEvent.click(await screen.findByRole('button', { name: 'continue rules' }));
  await screen.findByText('preview');
  await waitFor(() => expect(screen.getByRole('button', { name: /nextStep/ })).toBeEnabled());
  fireEvent.click(screen.getByRole('button', { name: /nextStep/ }));
  await waitFor(() => expect(process).toHaveBeenCalled());
  expect(process.mock.calls[0][0].file_list).toMatchObject([
    { file_path: '/tmp/a.pdf', preview_upload_ref: 'signed-a' },
    { file_path: '/tmp/b.pdf' },
  ]);
});
