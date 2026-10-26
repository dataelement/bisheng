import { useEffect, useRef, useState } from 'react';

type ResourceState<T> = {
  key: string;
  status: 'loading' | 'ready' | 'error';
  data?: T;
  error?: unknown;
};

/** The key includes the resource/access identity; loader identity never triggers a reload. */
export function usePreviewResource<T>(key: string, load: (signal: AbortSignal) => Promise<T>): Omit<ResourceState<T>, 'key'> {
  const loadRef = useRef(load);
  loadRef.current = load;
  const [state, setState] = useState<ResourceState<T>>({ key, status: 'loading' });
  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    const read = loadRef.current;
    if (!key) {
      setState({ key, status: 'ready' });
      return () => { active = false; controller.abort(); };
    }
    setState({ key, status: 'loading' });
    void (async () => {
      try {
        const data = await read(controller.signal);
        if (active) setState({ key, status: 'ready', data });
      } catch (error) {
        if (active) setState({ key, status: 'error', error });
      }
    })();
    return () => { active = false; controller.abort(); };
  }, [key]);
  // Do not expose a previous file between a new render and its effect cleanup.
  return state.key === key ? state : { status: 'loading' };
}
