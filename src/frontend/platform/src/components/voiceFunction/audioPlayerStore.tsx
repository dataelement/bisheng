      
// stores/audioPlayerStore.ts
import { create } from 'zustand';
import { Howl } from 'howler';

interface AudioPlayerState {
  currentPlayingId: string | null;
  soundInstance: Howl | null;
  isLoading: boolean;
  progress: number; // 0-1
  duration: number;
  playAudio: (params: {
    id: string;
    audioUrl: string;
    onEnd?: () => void;
  }) => void;
  pauseAudio: () => void;
  resumeAudio: () => void;
  stopAudio: () => void;
  setLoading: (isLoading: boolean) => void;
  setCurrentPlayingId: (id: string | null) => void;
}

export const useAudioPlayerStore = create<AudioPlayerState>((set, get) => ({
  currentPlayingId: null,
  soundInstance: null,
  isLoading: false,
  progress: 0,
  duration: 0,

  playAudio: ({ id, audioUrl, onEnd }) => {
    const { stopAudio, currentPlayingId } = get();
    
    // 如果已经在播放，先停止
    if (currentPlayingId) {
      stopAudio();
    }

    set({ isLoading: true, currentPlayingId: id });

    const sound = new Howl({
      src: [audioUrl],
      html5: true, // 使用 HTML5 Audio API
      onload: () => {
        const currentId = get().currentPlayingId;
        // 只有当当前播放ID仍然是该音频的ID时，才播放
        if (currentId === id) {
          set({ isLoading: false, duration: sound.duration() });
          sound.play();
        } else {
          // 否则，清理该音频的状态
          set({ isLoading: false });
          // 销毁声音实例
          sound.unload();
        }
      },
      onplay: () => {
        // 更新进度
        const updateProgress = () => {
          if (sound.playing()) {
            set({
              progress: sound.seek() / sound.duration(),
            });
            requestAnimationFrame(updateProgress);
          }
        };
        updateProgress();
      },
      onend: () => {
        set({ currentPlayingId: null, soundInstance: null, progress: 0 });
        onEnd?.();
      },
      onpause: () => {
        // 暂停时逻辑
      },
      onstop: () => {
        set({ progress: 0 });
      },
      onerror: () => {
        set({ isLoading: false, currentPlayingId: null });
      },
    });

    set({ soundInstance: sound });
  },

  pauseAudio: () => {
    const { soundInstance } = get();
    soundInstance?.pause();
  },

  resumeAudio: () => {
    const { soundInstance } = get();
    soundInstance?.play();
  },

  stopAudio: () => {
    const { soundInstance } = get();
    soundInstance?.stop();
    set({ currentPlayingId: null, soundInstance: null, progress: 0 });
  },

  setLoading: (isLoading) => set({ isLoading }),
  setCurrentPlayingId: (id) => set({ currentPlayingId: id }),
}));

    