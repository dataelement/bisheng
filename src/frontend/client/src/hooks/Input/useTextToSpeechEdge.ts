// @ts-strict-ignore
import { useRecoilValue } from 'recoil';
import type { MsEdgeTTS } from 'msedge-tts';
import { useState, useCallback, useRef, useEffect, useMemo } from 'react';
import type { VoiceOption } from '~/common';
import { useToastContext } from '~/Providers/ToastContext';
import useLocalize from '~/hooks/useLocalize';
import store from '~/store';

// msedge-tts drags in the Node crypto/stream polyfills (~600 KB). This hook sits behind the
// `~/hooks` barrel that the first screen imports, so load the library only when it is used.
const loadEdgeTTS = () => import('msedge-tts');

interface UseTextToSpeechEdgeReturn {
  generateSpeechEdge: (text: string) => void;
  cancelSpeechEdge: () => void;
  voices: VoiceOption[];
}

function useTextToSpeechEdge({
  setIsSpeaking,
}: {
  setIsSpeaking: React.Dispatch<React.SetStateAction<boolean>>;
}): UseTextToSpeechEdgeReturn {
  const localize = useLocalize();
  const [voices, setVoices] = useState<VoiceOption[]>([]);
  const voiceName = useRecoilValue(store.voice);
  const ttsRef = useRef<MsEdgeTTS | null>(null);
  const audioElementRef = useRef<HTMLAudioElement | null>(null);
  const mediaSourceRef = useRef<MediaSource | null>(null);
  const sourceBufferRef = useRef<SourceBuffer | null>(null);
  const pendingBuffers = useRef<Uint8Array[]>([]);
  const { showToast } = useToastContext();

  const isBrowserSupported = useMemo(
    () => typeof MediaSource !== 'undefined' && MediaSource.isTypeSupported('audio/mpeg'),
    [],
  );

  const getTTS = useCallback(async () => {
    const edgeTTS = await loadEdgeTTS();
    if (!ttsRef.current) {
      ttsRef.current = new edgeTTS.MsEdgeTTS();
    }
    return { tts: ttsRef.current, OUTPUT_FORMAT: edgeTTS.OUTPUT_FORMAT };
  }, []);

  const fetchVoices = useCallback(() => {
    getTTS()
      .then(({ tts }) => tts.getVoices())
      .then((voicesList) => {
        setVoices(
          voicesList.map((v) => ({
            value: v.ShortName,
            label: v.FriendlyName,
          })),
        );
      })
      .catch((error) => {
        console.error('Error fetching voices:', error);
        showToast({
          message: localize('com_nav_voices_fetch_error'),
          status: 'error',
        });
      });
  }, [getTTS, showToast, localize]);

  const initializeTTS = useCallback(() => {
    const availableVoice: VoiceOption | undefined = voices.find((v) => v.value === voiceName);

    if (availableVoice) {
      getTTS()
        .then(({ tts, OUTPUT_FORMAT }) =>
          tts.setMetadata(availableVoice.value, OUTPUT_FORMAT.AUDIO_24KHZ_48KBITRATE_MONO_MP3),
        )
        .catch((error) => {
          console.error('Error initializing TTS:', error);
          showToast({
            message: localize('com_nav_tts_init_error', { 0: (error as Error).message }),
            status: 'error',
          });
        });
    } else if (voices.length > 0) {
      getTTS()
        .then(({ tts, OUTPUT_FORMAT }) =>
          tts.setMetadata(voices[0].value, OUTPUT_FORMAT.AUDIO_24KHZ_48KBITRATE_MONO_MP3),
        )
        .catch((error) => {
          console.error('Error initializing TTS:', error);
          showToast({
            message: localize('com_nav_tts_init_error', { 0: (error as Error).message }),
            status: 'error',
          });
        });
    }
  }, [getTTS, voiceName, showToast, localize, voices]);

  const appendNextBuffer = useCallback(() => {
    if (
      sourceBufferRef.current &&
      !sourceBufferRef.current.updating &&
      pendingBuffers.current.length > 0
    ) {
      const nextBuffer = pendingBuffers.current.shift();
      if (nextBuffer) {
        try {
          sourceBufferRef.current.appendBuffer(nextBuffer);
        } catch (error) {
          console.error('Error appending buffer:', error);
          showToast({
            message: localize('com_nav_buffer_append_error'),
            status: 'error',
          });
          pendingBuffers.current.unshift(nextBuffer);
        }
      }
    }
  }, [showToast, localize]);

  const onSourceOpen = useCallback(() => {
    if (!sourceBufferRef.current && mediaSourceRef.current) {
      try {
        sourceBufferRef.current = mediaSourceRef.current.addSourceBuffer('audio/mpeg');
        sourceBufferRef.current.addEventListener('updateend', appendNextBuffer);
      } catch (error) {
        console.error('Error adding source buffer:', error);
        showToast({
          message: localize('com_nav_source_buffer_error'),
          status: 'error',
        });
      }
    }
  }, [showToast, localize, appendNextBuffer]);

  const initializeMediaSource = useCallback(() => {
    if (!mediaSourceRef.current) {
      mediaSourceRef.current = new MediaSource();
      audioElementRef.current = new Audio();
      audioElementRef.current.src = URL.createObjectURL(mediaSourceRef.current);
    }

    const mediaSource = mediaSourceRef.current;
    if (mediaSource.readyState === 'open') {
      onSourceOpen();
    } else {
      mediaSource.addEventListener('sourceopen', onSourceOpen);
    }
  }, [onSourceOpen]);

  const generateSpeechEdge = useCallback(
    (text: string) => {
      const generate = async () => {
        try {
          if (!ttsRef.current || !audioElementRef.current) {
            throw new Error('TTS or Audio element not initialized');
          }

          setIsSpeaking(true);
          pendingBuffers.current = [];

          const readable = ttsRef.current.toStream(text);

          readable.on('data', (chunk: Buffer) => {
            pendingBuffers.current.push(new Uint8Array(chunk));
            appendNextBuffer();
          });

          readable.on('end', () => {
            if (mediaSourceRef.current && mediaSourceRef.current.readyState === 'open') {
              mediaSourceRef.current.endOfStream();
            }
          });

          audioElementRef.current.onended = () => {
            setIsSpeaking(false);
          };

          await audioElementRef.current.play();
        } catch (error) {
          console.error('Error generating speech:', error);
          showToast({
            message: localize('com_nav_audio_play_error', { 0: (error as Error).message }),
            status: 'error',
          });
          setIsSpeaking(false);
        }
      };

      generate();
    },
    [setIsSpeaking, appendNextBuffer, showToast, localize],
  );

  const cancelSpeechEdge = useCallback(() => {
    try {
      if (audioElementRef.current) {
        audioElementRef.current.pause();
        audioElementRef.current.currentTime = 0;
      }
      if (mediaSourceRef.current && mediaSourceRef.current.readyState === 'open') {
        mediaSourceRef.current.endOfStream();
      }
      pendingBuffers.current = [];
      setIsSpeaking(false);
    } catch (error) {
      console.error('Error cancelling speech:', error);
      showToast({
        message: localize('com_nav_speech_cancel_error'),
        status: 'error',
      });
    }
  }, [setIsSpeaking, showToast, localize]);

  useEffect(() => {
    if (!isBrowserSupported) {
      return;
    }
    fetchVoices();
  }, [fetchVoices, isBrowserSupported]);

  useEffect(() => {
    if (!isBrowserSupported) {
      return;
    }
    initializeTTS();
  }, [voiceName, initializeTTS, isBrowserSupported]);

  useEffect(() => {
    if (!isBrowserSupported) {
      return;
    }
    initializeMediaSource();
    return () => {
      if (mediaSourceRef.current) {
        URL.revokeObjectURL(audioElementRef.current?.src ?? '');
      }
    };
  }, [initializeMediaSource, isBrowserSupported]);

  if (!isBrowserSupported) {
    return {
      generateSpeechEdge: () => ({}),
      cancelSpeechEdge: () => ({}),
      voices: [],
    };
  }

  return { generateSpeechEdge, cancelSpeechEdge, voices };
}

export default useTextToSpeechEdge;
