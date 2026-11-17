import request from '../request';
import type {
    PlatformModelCapabilities,
    PlatformModelListPage,
} from '@/types/flow/platformModel';

const root = '/api/v1/workflow/platform-models';

export async function getPlatformModelCapabilities(): Promise<PlatformModelCapabilities> {
    const env = await request.get<unknown, { workflow: PlatformModelCapabilities; multi_tenant_enabled?: boolean }>('/api/v1/env');
    return {
        platform_llm_enabled: Boolean(env.workflow?.platform_llm_enabled),
        multi_tenant_enabled: env.multi_tenant_enabled,
    };
}

export async function listPlatformModels(
    workflowId: string,
    params?: { page_size?: number; search?: string; cursor?: string },
): Promise<PlatformModelListPage> {
    return await request.get(root, {
        params: {
            workflow_id: workflowId,
            page_size: params?.page_size ?? 20,
            ...(params?.search ? { search: params.search } : {}),
            ...(params?.cursor ? { cursor: params.cursor } : {}),
        },
    });
}

export async function getPlatformModelVersion(
    workflowId: string,
    resourceId: string,
    versionId: string,
): Promise<Record<string, unknown>> {
    return await request.get(
        `${root}/${encodeURIComponent(resourceId)}/versions/${encodeURIComponent(versionId)}`,
        { params: { workflow_id: workflowId } },
    );
}

export const platformLlmTemplate = {
    id: 'platform_llm_xxx',
    type: 'platform_llm',
    name: 'true',
    description: 'true',
    v: 1,
    group_params: [
        {
            name: '模型设置',
            params: [
                {
                    key: 'model_ref',
                    label: 'true',
                    type: 'platform_model_select',
                    value: null,
                    required: true,
                    placeholder: 'true',
                },
                {
                    key: 'temperature',
                    label: 'true',
                    type: 'slide',
                    scope: [0, 2],
                    step: 0.1,
                    value: 1,
                },
            ],
        },
        {
            name: '提示词',
            params: [
                {
                    key: 'system_prompt',
                    label: 'true',
                    type: 'var_textarea',
                    test: 'var',
                    value: '',
                },
                {
                    key: 'user_prompt',
                    label: 'true',
                    type: 'var_textarea',
                    test: 'var',
                    value: '',
                    required: true,
                },
            ],
        },
        {
            name: '输出',
            params: [
                {
                    key: 'output_user',
                    label: 'true',
                    type: 'switch',
                    help: 'true',
                    value: true,
                },
                {
                    key: 'output',
                    global: 'code:value.map(el => ({ label: el.label, value: el.key }))',
                    label: 'true',
                    help: 'true',
                    type: 'var',
                    value: [{ key: 'output', label: 'output' }],
                },
            ],
        },
    ],
};
