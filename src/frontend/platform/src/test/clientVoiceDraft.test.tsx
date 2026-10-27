import { act, render, renderHook } from '@testing-library/react';
import { createRef, useRef, useState } from 'react';
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

it('pauses recognition when an input method starts and keeps the typed text', () => {
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
  expect(result.current.voice.props.stopSignal).toBe(1);
  expect(result.current.text).toBe('Old ');
  act(() => result.current.voice.compositionEnd());
  expect(result.current.text).toBe('Old ');
});

it('pauses realtime recognition when the dictated text is edited', () => {
  const ref = createRef<HTMLTextAreaElement>();
  const { result } = renderHook(() => {
    const [text, setText] = useState('Old ');
    return { text, voice: useVoiceDraft(ref, text, setText) };
  });
  act(() => {
    result.current.voice.props.onRecordingStart(true);
    result.current.voice.props.onChange('hello');
  });
  expect(result.current.text).toBe('Old hello');
  const signal = result.current.voice.props.stopSignal;
  act(() => {
    result.current.voice.handleEdit('Old hello!');
    result.current.voice.props.onChange('hello world');
  });
  expect(result.current.voice.props.stopSignal).toBe(signal + 1);
  expect(result.current.text).toBe('Old hello!');
});

it('leaves the caret after the dictated text when recording starts mid-sentence', () => {
  let voice: ReturnType<typeof useVoiceDraft> | null = null;
  function Field() {
    const ref = useRef<HTMLTextAreaElement>(null);
    const [text, setText] = useState('prefix suffix');
    voice = useVoiceDraft(ref, text, setText);
    return <textarea ref={ref} value={text} onChange={() => undefined} />;
  }
  render(<Field />);
  const textarea = document.querySelector('textarea');
  if (!textarea) throw new Error('textarea missing');
  textarea.focus();
  textarea.setSelectionRange(7, 7);
  act(() => {
    voice?.props.onRecordingStart();
    voice?.props.onChange('hello');
  });
  expect(textarea.value).toBe('prefix hellosuffix');
  expect(textarea.selectionStart).toBe(12);
  expect(textarea.selectionEnd).toBe(12);
});

it('pauses recognition when text is added after the dictated span', () => {
  const ref = createRef<HTMLTextAreaElement>();
  const { result } = renderHook(() => {
    const [text, setText] = useState('Old ');
    return { text, voice: useVoiceDraft(ref, text, setText) };
  });
  act(() => {
    result.current.voice.props.onRecordingStart();
    result.current.voice.props.onChange('hello');
  });
  const signal = result.current.voice.props.stopSignal;
  act(() => {
    result.current.voice.handleEdit('Old hello!');
    result.current.voice.props.onChange('hello world');
  });
  expect(result.current.voice.props.stopSignal).toBe(signal + 1);
  expect(result.current.text).toBe('Old hello!');
});
