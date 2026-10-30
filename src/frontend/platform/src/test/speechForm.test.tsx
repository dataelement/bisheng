import { createRef } from 'react';
import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { CustomForm } from '../pages/ModelPage/manage/CustomForm';
import type { CustomFormHandle } from '../pages/ModelPage/manage/CustomForm';

describe('speech credentials form', () => {
    it('allows speech-only setup, then validates LLM fields when a chat model is added', () => {
        const ref = createRef<CustomFormHandle>();
        const config = { speech_app_id: '123', speech_api_key: '********' };
        const props = { ref, showDefault: true, provider: 'qianfan', formData: config, modelTypes: ['asr'] };
        const { rerender } = render(<CustomForm {...props} />);
        expect(ref.current?.getData()).toEqual([{
            ...config,
            base_url: 'https://qianfan.baidubce.com/v2',
            api_key: '',
        }, '']);
        rerender(<CustomForm {...props} modelTypes={['asr', 'llm']} />);
        expect(ref.current?.getData()[1]).toBe('API Key');
        expect(ref.current?.getData()[0].base_url).toBe('https://qianfan.baidubce.com/v2');
    });
    it('shows speech credentials for a realtime-only provider and hides chat fields', () => {
        const ref = createRef<CustomFormHandle>();
        const config = { speech_app_id: '123', speech_secret_id: 'fixture-id', speech_secret_key: '********' };
        const { getByText, queryByText } = render(
            <CustomForm ref={ref} showDefault={true} provider="tencent" formData={config} modelTypes={['asr_rt']} />,
        );
        expect(getByText('model.speechCredentials')).toBeTruthy();
        expect(getByText('API Key')).toBeTruthy();
        expect(getByText('Base URL')).toBeTruthy();
        expect(ref.current?.getData()[1]).toBe('');
    });
    it('preserves existing chat credentials when only ASR fields are displayed', () => {
        const ref = createRef<CustomFormHandle>();
        const config = { base_url: 'https://api.hunyuan.cloud.tencent.com/v1', api_key: '********', speech_app_id: '123', speech_secret_id: 'fixture-id', speech_secret_key: '********' };
        render(<CustomForm ref={ref} showDefault={false} provider="tencent" formData={config} modelTypes={['asr']} />);
        expect(ref.current?.getData()).toEqual([config, '']);
    });
});
