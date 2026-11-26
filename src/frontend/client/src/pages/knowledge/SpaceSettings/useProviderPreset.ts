import { useEffect, useState } from 'react';
import {
  isCompleteSelection, listExtractTemplates, listProviderModels, previewProviderPreset,
  type ExtractConfig, type ExtractTemplate, type ProviderModels, type ProviderSelection, type ReviewedPreset,
} from '~/api/knowledgeProviderSettings';

export type SelectionDraft = {
  summary_model_id: string; embedding_model_id: string; vision_model_id: string;
  chunk_size: number | null; overlap: number | null;
  extract_mode: 'template' | 'custom';
  extract_template_kb_id: string;
  extract_config: ExtractConfig;
};

const EMPTY_EXTRACT: ExtractConfig = {
  text: '',
  tags: [''],
  nodes: [{ name: '' }],
  relations: [{ node1: '', type: '', node2: '' }],
};

const EMPTY: SelectionDraft = {
  summary_model_id: '', embedding_model_id: '', vision_model_id: '', chunk_size: 512, overlap: 64,
  extract_mode: 'template', extract_template_kb_id: '', extract_config: EMPTY_EXTRACT,
};

function toSelection(draft: SelectionDraft): ProviderSelection | null {
  const base = {
    summary_model_id: draft.summary_model_id,
    embedding_model_id: draft.embedding_model_id,
    vision_model_id: draft.vision_model_id,
    chunk_size: draft.chunk_size as number,
    overlap: draft.overlap as number,
  };
  if (draft.extract_mode === 'template') {
    const candidate = { ...base, extract_template_kb_id: draft.extract_template_kb_id };
    return isCompleteSelection(candidate) ? candidate : null;
  }
  const tags = draft.extract_config.tags.map(t => t.trim()).filter(Boolean);
  const nodes = draft.extract_config.nodes.map(n => ({ name: n.name.trim() })).filter(n => n.name);
  const relations = draft.extract_config.relations
    .map(r => ({ node1: r.node1.trim(), type: r.type.trim(), node2: r.node2.trim() }))
    .filter(r => r.node1 && r.type && r.node2);
  const candidate = {
    ...base,
    extract_config: { text: draft.extract_config.text.trim(), tags, nodes, relations },
  };
  return isCompleteSelection(candidate) ? candidate : null;
}

export function useProviderPreset(enabled: boolean) {
  const [models, setModels] = useState<ProviderModels | null>(null);
  const [modelsFailed, setModelsFailed] = useState(false);
  const [templates, setTemplates] = useState<ExtractTemplate[] | null>(null);
  const [templatesFailed, setTemplatesFailed] = useState(false);
  const [selection, setSelection] = useState<SelectionDraft>(EMPTY);
  const [preset, setPreset] = useState<ReviewedPreset | null>(null);
  // A reviewed preset only covers the selection it was probed for. While a new
  // selection is being reviewed the previous one stays on screen (the form must
  // not blank out on every keystroke) but it is not submittable.
  const [fresh, setFresh] = useState(false);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let active = true;
    setModels(null);
    setModelsFailed(false);
    setTemplates(null);
    setTemplatesFailed(false);
    setSelection(EMPTY);
    if (enabled) {
      void listProviderModels().then(
        result => {
          if (!active) return;
          setModels(result);
          setSelection(current => ({
            ...current,
            summary_model_id: result.chat[0]?.id ?? '',
            embedding_model_id: result.embedding[0]?.id ?? '',
            vision_model_id: result.vision[0]?.id ?? '',
          }));
        },
        () => { if (active) setModelsFailed(true); },
      );
      void listExtractTemplates().then(
        result => {
          if (!active) return;
          setTemplates(result);
          setSelection(current => ({
            ...current,
            extract_template_kb_id: current.extract_template_kb_id || result[0]?.id || '',
          }));
        },
        () => { if (active) setTemplatesFailed(true); },
      );
    }
    return () => { active = false; };
  }, [enabled]);
  const chosen = enabled && models !== null ? toSelection(selection) : null;
  const complete = chosen !== null;
  const key = chosen ? JSON.stringify(chosen) : '';
  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    setFresh(false);
    setFailed(false);
    if (!key) {
      setPreset(null);
      return () => { active = false; controller.abort(); };
    }
    // Each preview runs a live probe of all three models, so wait until typing in the chunk fields settles.
    const timer = setTimeout(() => {
      void previewProviderPreset(JSON.parse(key) as ProviderSelection, controller.signal).then(
        result => {
          if (!active) return;
          setPreset(result);
          setFresh(true);
        },
        (error: unknown) => {
          if (!active) return;
          if (import.meta.env.DEV) {
            const code = error && typeof error === 'object' && 'status_code' in error
              ? (error as { status_code?: unknown }).status_code : undefined;
            console.warn('WeKnora creation-settings preview failed', code ?? error);
          }
          setFailed(true);
        },
      );
    }, 400);
    return () => { active = false; clearTimeout(timer); controller.abort(); };
  }, [key]);
  return {
    models, modelsFailed, templates, templatesFailed, selection, setSelection, complete,
    preset, fresh, failed,
  };
}
