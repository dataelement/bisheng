import { fireEvent, render, screen } from '@testing-library/react';
import { createRef } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { CustomForm, CustomFormHandle } from './CustomForm';

describe('discovery connection and speech configuration', () => {
  it('retains speech fields while publishing connection changes', () => {
    const ref = createRef<CustomFormHandle>();
    const onConnectionChange = vi.fn();
    render(<CustomForm ref={ref} showDefault={false} provider="tencent" modelTypes={['llm', 'asr']}
      formData={{ api_key: 'chat-key', base_url: 'https://gateway.example/v1', speech_app_id: '123', speech_secret_id: 'id', speech_secret_key: 'speech-key' }}
      onConnectionChange={onConnectionChange} />);
    fireEvent.change(screen.getByDisplayValue('chat-key'), { target: { value: 'edited' } });
    expect(onConnectionChange).toHaveBeenCalledOnce();
    expect(ref.current?.getData()).toEqual([expect.objectContaining({ api_key: 'edited', speech_secret_key: 'speech-key' }), '']);
  });

  it('validates speech-only connections with their own fields', () => {
    const ref = createRef<CustomFormHandle>();
    render(<CustomForm ref={ref} showDefault={true} provider="volcengine" modelTypes={['asr']} formData={{ speech_api_key: 'speech-key' }} />);
    expect(ref.current?.getData()).toEqual([expect.objectContaining({
      speech_api_key: 'speech-key',
      speech_resource_id: 'volc.seedasr.sauc.duration',
      base_url: 'https://ark.cn-beijing.volces.com/api/v3',
      api_key: '',
    }), '']);
    expect(screen.getByLabelText('Base URL')).toBeInTheDocument();
    expect(screen.getByLabelText('API Key')).toBeInTheDocument();
  });

  it('requires the catalog API key before listing when speech-only rows omit it from save validation', () => {
    const ref = createRef<CustomFormHandle>();
    render(<CustomForm ref={ref} showDefault={false} provider="tencent" modelTypes={['asr_rt']}
      formData={{ base_url: 'https://tokenhub.tencentmaas.com/v1', api_key: '', speech_app_id: '1', speech_secret_id: 'id', speech_secret_key: 'key' }} />);
    expect(ref.current?.getData()[1]).toBe('');
    expect(ref.current?.getCatalogError()).toBe('API Key');
  });

  it('shows the vendor base url in the field when a saved address is blank', () => {
    render(<CustomForm showDefault={false} provider="qianfan" modelTypes={['asr_rt']}
      formData={{ base_url: '', api_key: '********', speech_app_id: '124474393', speech_api_key: '********' }} />);
    expect(screen.getByLabelText('Base URL')).toHaveValue('https://qianfan.baidubce.com/v2');
    expect(screen.getByLabelText('API Key')).toHaveValue('********');
  });

  it('shows Tencent SecretId and SecretKey beside the API key', () => {
    const ref = createRef<CustomFormHandle>();
    render(<CustomForm ref={ref} showDefault={false} provider="tencent" modelTypes={['llm']}
      formData={{ api_key: 'chat-key', base_url: 'https://tokenhub.tencentmaas.com/v1' }} />);
    expect(screen.getByLabelText(/SecretId/)).toBeInTheDocument();
    expect(screen.getByLabelText(/SecretKey/)).toBeInTheDocument();
    expect(screen.queryByText('model.speechCredentials')).toBeNull();
    expect(ref.current?.getCatalogError()).toBe('SecretId');
    expect(ref.current?.getData()[1]).toBe('SecretId');
  });

  it('allows listing when the API key is set and Base URL keeps the vendor default', () => {
    const ref = createRef<CustomFormHandle>();
    render(<CustomForm ref={ref} showDefault={false} provider="tencent" modelTypes={['asr_rt']}
      formData={{ base_url: '', api_key: 'token', speech_app_id: '1', speech_secret_id: 'id', speech_secret_key: 'key' }} />);
    expect(ref.current?.getCatalogError()).toBe('');
  });
});
