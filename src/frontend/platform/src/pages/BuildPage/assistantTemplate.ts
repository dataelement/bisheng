import { createAssistantsApi, saveAssistanttApi } from '@/controllers/API/assistant';

export interface AssistantTemplateDraft {
    id?: string;
    modelName?: string;
}

interface TemplateConfig {
    prompt?: string;
    guide_word?: string;
    guide_question?: string[];
    temperature?: number;
    max_token?: number;
    knowledge_auth?: boolean;
    [key: string]: unknown;
}

/** A retained draft lets a failed save retry without creating another application. */
export async function instantiateAssistantTemplate(
    template: TemplateConfig,
    form: { name: string; desc: string; url: string },
    draft: AssistantTemplateDraft,
): Promise<string> {
    if (!draft.id) {
        const created = await createAssistantsApi(form.name, '', form.url);
        draft.id = created.id;
        draft.modelName = created.model_name || '';
    }
    const id = draft.id!;
    await saveAssistanttApi({
        id, name: form.name, desc: form.desc, logo: form.url,
        prompt: template.prompt || '',
        guide_word: template.guide_word || '',
        guide_question: template.guide_question?.filter(Boolean) || [],
        temperature: template.temperature ?? 1,
        max_token: template.max_token ?? 32000,
        knowledge_auth: template.knowledge_auth ?? false,
        model_name: draft.modelName || '',
        tool_list: [], flow_list: [], knowledge_list: [],
    });
    return id;
}
