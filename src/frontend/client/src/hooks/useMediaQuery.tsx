import { useLayoutEffect, useState } from 'react';

export default function useMediaQuery(query: string) {
  const [matches, setMatches] = useState<boolean>(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
      return false;
    }
    return window.matchMedia(query).matches;
  });

  // useLayoutEffect：首帧与窗口缩放时与 matchMedia 同步，避免依赖 useEffect 晚一拍出现错误布局（如应用对话悬浮钮闪现）
  useLayoutEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
      return;
    }
    const media = window.matchMedia(query);
    setMatches(media.matches);

    const listener = (event: MediaQueryListEvent) => setMatches(event.matches);
    if (typeof media.addEventListener === 'function') {
      media.addEventListener('change', listener);
      return () => media.removeEventListener('change', listener);
    }
    // Safari fallback
    media.addListener(listener);
    return () => media.removeListener(listener);
  }, [query]);

  return matches;
}
