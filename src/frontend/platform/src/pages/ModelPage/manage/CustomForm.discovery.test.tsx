import { fireEvent, render, screen } from '@testing-library/react';
import { createRef } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { CustomForm, CustomFormHandle } from './CustomForm';

describe('discovery connection and speech configuration', () => {
  it('retains speech fields while publishing connection changes and blur', () => {
    const ref = createRef<CustomFormHandle>();
    const onConnectionChange = vi.fn();
    const onConnectionBlur = vi.fn();
    render(<CustomForm ref={ref} showDefault={false} provider="tencent" modelTypes={['llm', 'asr']}
      formData={{ api_key: 'chat-key', base_url: 'https://gateway.example/v1', speech_app_id: '123', speech_secret_id: 'id', speech_secret_key: 'speech-key' }}
      onConnectionChange={onConnectionChange} onConnectionBlur={onConnectionBlur} />);
    fireEvent.change(screen.getByDisplayValue('chat-key'), { target: { value: 'edited' } });
    fireEvent.blur(screen.getByDisplayValue('edited'));
    expect(onConnectionChange).toHaveBeenCalledOnce();
    expect(onConnectionBlur).toHaveBeenCalledOnce();
    expect(ref.current?.getData()).toEqual([expect.objectContaining({ api_key: 'edited', speech_secret_key: 'speech-key' }), '']);
  });

  it('validates speech-only connections with their own fields', () => {
    const ref = createRef<CustomFormHandle>();
    render(<CustomForm ref={ref} showDefault={true} provider="volcengine" modelTypes={['asr']} formData={{ speech_api_key: 'speech-key' }} />);
    expect(ref.current?.getData()).toEqual([expect.objectContaining({ speech_api_key: 'speech-key', speech_resource_id: 'volc.seedasr.sauc.duration' }), '']);
    expect(screen.queryByLabelText('Base URL')).toBeNull();
  });
});
