// components/AudioPlayButton.tsx
import { useState } from 'react';
import { useAudioPlayerStore } from './audioPlayerStore';
import { Loader, Volume2 } from 'lucide-react';
import { textToSpeech } from '@/controllers/API/workbench';
import { message, toast } from '../bs-ui/toast/use-toast';
import i18next from 'i18next';

interface AudioPlayButtonProps {
  messageId: string;
  msg?: string;
  version?: string;
}

export const AudioPlayComponent = ({ messageId, msg = '' }: AudioPlayButtonProps) => {
  const [error, setError] = useState('');
  const [version] = useState(window.chat_version || 'v1');
  const {
    currentPlayingId,
    soundInstance,
    isLoading,
    playAudio,
    pauseAudio,
    resumeAudio,
    stopAudio,
    setLoading,
    setCurrentPlayingId,
  } = useAudioPlayerStore();

  const API_BASE_URL = __APP_ENV__.BASE_URL || '';

  const getAudioUrl = async (text: string) => {
    console.log('请求TTS的文本:', text);

    // 1. 调用API
    const response = await textToSpeech(text, version);
    console.log('TTS API 原始响应:', response);

    // 2. 处理响应
    let audioPath = '';
    if (typeof response === 'string') {
      // 情况A: API直接返回了路径字符串
      audioPath = response;
    } else if (response?.data) {
      // 情况B: API返回了JSON对象
      if (typeof response.data === 'string') {
        audioPath = response.data;
      } else if (response.data?.data) {
        audioPath = response.data.data;
      }
    }

    if (audioPath) {
      // 3. 将相对路径拼接成完整的URL
      const audioUrl = `${API_BASE_URL}${audioPath}`;
      console.log('生成的音频播放链接:', audioUrl);
      return audioUrl;
    } else {
      // 如果无法解析路径，抛出异常
      throw new Error(`播放功能不可用，请联系管理员`);
    }
  };

  const isPlaying = currentPlayingId === messageId && soundInstance?.playing();
  const isThisLoading = currentPlayingId === messageId && isLoading;

  const handlePlay = async () => {
    try {
      setError('');

      if (currentPlayingId === messageId) {
        if (soundInstance?.playing()) {
          pauseAudio();
        } else {
          resumeAudio();
        }
        return;
      }

      if (currentPlayingId) {
        stopAudio();
      }

      setLoading(true);
      setCurrentPlayingId(messageId);

      const audioUrl = await getAudioUrl(msg);
      console.log('成功获取音频链接:', audioUrl);

      playAudio({
        id: messageId,
        audioUrl,
        onEnd: () => {
          // 播放结束后的回调
        },
      });
    } catch (err) {
      console.error('播放请求异常详情:', err);
      toast({
        title: i18next.t('prompt'),
        variant: 'error',
        description: '播放功能不可用，请联系管理员'
      });
      setLoading(false);
      setCurrentPlayingId(null);
    }
  };

  return (
    <div className="audio-play-button-container">
      <button
        onClick={handlePlay}
        disabled={isThisLoading}
        aria-label={isPlaying ? 'Pause' : 'Play'}
      >
        {isThisLoading ? (
          <Loader size={20} strokeWidth={1.8} color="#9ca3af" className={'mt-0.5 mr-1 animate-spin'} />
        ) : (
          <Volume2 size={20} strokeWidth={1.8} color="#9ca3af" className={`cursor-pointer mt-0.5 mr-1 text-primary hover:text-primary`} />

        )}
      </button>
      {error && <div className="error-message">{error}</div>}
    </div>
  );
};