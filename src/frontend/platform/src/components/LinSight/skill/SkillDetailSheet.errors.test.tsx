import { normalizeApiError } from '@bisheng/api-client';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { notification } from '@bisheng/ui';
import { skillApi, type SkillDetail } from '@/controllers/API/linsight';
import { showApiError } from '@/controllers/request';
import { SkillDetailSheet } from './SkillDetailSheet';

vi.mock('@/controllers/API/linsight', () => ({ skillApi: { getSkillFile: vi.fn() } }));
vi.mock('@/controllers/request', () => ({ showApiError: vi.fn() }));
afterEach(cleanup);

it('delegates an already presented asset request failure without opening another notice', async () => {
    const notice = vi.spyOn(notification, 'open');
    const error = normalizeApiError(new Error('Missing file'), { message: 'Missing file' });
    error.presentation = 'toast';
    vi.mocked(skillApi.getSkillFile).mockRejectedValueOnce(error);
    const detail: SkillDetail = {
        id: 1, name: 'example', display_name: 'Example', description: '', enabled: true,
        default_checked: false, source: 'manual', preview: '', source_text: '', files: [{ path: 'guide.txt', size: 1 }],
    };
    render(<SkillDetailSheet detail={detail} onOpenChange={vi.fn()} onEdit={vi.fn()} onDelete={vi.fn()} />);
    fireEvent.click(screen.getByText('guide.txt'));
    await waitFor(() => expect(skillApi.getSkillFile).toHaveBeenCalledWith('example', 'guide.txt'));
    await waitFor(() => expect(showApiError).toHaveBeenCalledWith(error));
    expect(notice).not.toHaveBeenCalled();
});
