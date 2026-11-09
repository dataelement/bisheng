import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { expect, it, vi } from 'vitest';
import { KnowledgeModel } from './KnowledgeModel';
import { updateKnowledgeModelConfig } from '@/controllers/API/finetune';

vi.mock('@/controllers/API/finetune', () => ({ getKnowledgeModelEnvelope: vi.fn(), updateKnowledgeModelConfig: vi.fn().mockResolvedValue({}) }));
vi.mock('../useSystemConfigEnvelope', () => ({ useSystemConfigEnvelope: () => ({ config: saved, loading: false, clearInherited: vi.fn() }) }));
vi.mock('./WorkbenchModel', () => ({ defalutPrompt: 'original default' }));
vi.mock('../ModelFieldHint', () => ({ ModelFieldHint: () => null }));
vi.mock('bisheng-icons', () => ({ Outlined: { Setting: () => null, Loading: () => null } }));
vi.mock('@bisheng/ui', () => ({
  Alert: ({ description }: { description: string }) => <p>{description}</p>,
  Button: ({ children, onClick, disabled }: { children: ReactNode; onClick?: () => void; disabled?: boolean }) => <button onClick={onClick} disabled={disabled}>{children}</button>,
  Cascader: ({ value, onChange, 'aria-label': label }: { value: unknown; onChange: (path: string[]) => void; 'aria-label': string }) => <button aria-label={label} onClick={() => onChange(['provider', '222'])}>{JSON.stringify(value)}</button>,
  Tooltip: ({ children }: { children: ReactNode }) => <>{children}</>,
  Switch: () => null, Textarea: () => null, toast: { show: vi.fn() },
}));
const saved = { embedding_model_id: '101', source_model_id: '999', extract_title_model_id: '998', qa_similar_model_id: 202, asr_model_id: 777, abstract_enabled: true, auto_tag_enabled: true, abstract_prompt: 'original prompt', auto_tag_prompt: 'original tags' };
it('actual default form keeps unknown saved IDs and an in-progress repair across candidate refreshes', async () => {
  const { rerender } = render(<KnowledgeModel llmOptions={[]} embeddings={[]} asrModel={[]} onBack={vi.fn()} />);
  await waitFor(() => expect(screen.getByRole('button', { name: 'model.sourceTracingModel' })).toHaveTextContent('999'));
  expect(screen.getByRole('button', { name: 'model.documentSummaryModel' })).toHaveTextContent('998');
  fireEvent.click(screen.getByRole('button', { name: 'model.defaultEmbeddingModel' }));
  const options = [{ value: 'provider', label: 'new provider', children: [{ value: '222', label: 'new model' }] }];
  rerender(<KnowledgeModel llmOptions={options} embeddings={options} asrModel={[]} onBack={vi.fn()} />);
  expect(screen.getByRole('button', { name: 'model.defaultEmbeddingModel' })).toHaveTextContent('222');
  fireEvent.click(screen.getByRole('button', { name: 'model.save' }));
  await waitFor(() => expect(updateKnowledgeModelConfig).toHaveBeenCalledOnce());
  expect(updateKnowledgeModelConfig).toHaveBeenCalledWith({ ...saved, embedding_model_id: '222' });
});
