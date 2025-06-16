// components/AudioPlayButton.tsx
import { useState } from 'react';
import { useAudioPlayerStore } from '@/store/useAudioPlayerStore';
import { Mic, Square, Loader } from 'lucide-react';
import { textToSpeech } from '@/controllers/API/flow';
import { checkSassUrl } from '../bs-comp/FileView';
import { ThunmbIcon } from '../bs-icons';
import { formatTTSText } from '@/util/utils';

interface AudioPlayButtonProps {
  messageId: string;
  getAudioUrl: () => Promise<string>; // 获取音频的异步函数
}

export const AudioPlayComponent = ({ messageId, msg }: AudioPlayButtonProps) => {
  const [error, setError] = useState('');
  const {
    currentPlayingId,
    soundInstance,
    isLoading,
    playAudio,
    pauseAudio,
    resumeAudio,
    stopAudio,
  } = useAudioPlayerStore();

  const getAudioUrl = async (msg: string) => {
    const res = await textToSpeech({ text: formatTTSText(msg) });
    return checkSassUrl(res.url);
  }

  console.log(currentPlayingId, messageId, soundInstance?.playing());
  
  const isPlaying = currentPlayingId === messageId && soundInstance?.playing();
  const isThisLoading = currentPlayingId === messageId && isLoading;
  console.log('isPlaying', isPlaying);

  const handlePlay = async () => {
    try {
      setError('');
      
      // 当前存在正在播放的音频 则暂停
      if (soundInstance?.playing()) {
        pauseAudio();
        // 猴子补丁
        if (currentPlayingId === messageId) {
          // 如果是暂停当前播放的 直接跳出，否则继续后续逻辑获取新的播放
          return;
        }
      }

      // 如果是暂停状态，恢复播放
      if (currentPlayingId === messageId && soundInstance) {
        resumeAudio();
        return;
      }

      // 否则获取新的音频
      const audioUrl = await getAudioUrl(msg);
      playAudio({
        id: messageId,
        audioUrl: checkSassUrl(audioUrl),
        onEnd: () => {
          // 播放结束后的回调
        },
      });
    } catch (err) {
      setError('Failed to play audio');
      console.error(err);
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
          <ThunmbIcon
            type='loading'
            className={`${'animate-spin'}`}
          />
        ) : (
          <ThunmbIcon
            type='sound'
            className={`${'cursor-pointer'} ${isPlaying && 'text-primary hover:text-primary'}`}
          />
        )}
      </button>
      {error && <div className="error-message">{error}</div>}
    </div>
  );
};