import { act, renderHook } from '@testing-library/react';
import { createRef, useState } from 'react';
import { it, expect } from 'vitest';
import { useVoiceDraft } from '../../../client/src/hooks/Input/useVoiceDraft';

it('applies consecutive hypotheses before React commits the textarea value', () => {
  const ref = { current: document.createElement('textarea') };
  ref.current!.value = 'Old ';
  const { result } = renderHook(() => {
    const [text, setText] = useState('Old ');
    return { text, voice: useVoiceDraft(ref, text, setText) };
  });
  act(() => {
    result.current.voice.props.onRecordingStart();
    result.current.voice.props.onChange('draft');
    result.current.voice.props.onChange('final');
    result.current.voice.props.onRecordingEnd();
  });
  expect(result.current.text).toBe('Old final');
});

it('defers transcription through IME composition and keeps the final on pause', () => {
  const ref = createRef<HTMLTextAreaElement>();
  const { result } = renderHook(() => {
    const [text, setText] = useState('Old ');
    return { text, voice: useVoiceDraft(ref, text, setText) };
  });
  act(() => {
    result.current.voice.props.onRecordingStart();
    result.current.voice.compositionStart();
    result.current.voice.props.onChange('final');
    result.current.voice.props.onRecordingEnd();
  });
  expect(result.current.text).toBe('Old ');
  act(() => result.current.voice.compositionEnd());
  expect(result.current.text).toBe('Old final');
});
