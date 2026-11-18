import { useEffect, useRef, useState } from 'react';

/** Ignore retired reads even when the host request wrapper cannot cancel transport. */
export function useMoveResource<T>(load: (signal: AbortSignal) => Promise<T>, onError: (error: unknown) => void) {
  const errorHandler = useRef(onError);
  errorHandler.current = onError;
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<{
    load: typeof load;
    data?: T;
    loading: boolean;
    error: boolean;
  }>({ load, loading: true, error: false });

  useEffect(() => {
    const controller = new AbortController();
    setState({ load, loading: true, error: false });
    void load(controller.signal).then((data) => {
      if (!controller.signal.aborted) setState({ load, data, loading: false, error: false });
    }).catch((error: unknown) => {
      if (!controller.signal.aborted) {
        setState({ load, loading: false, error: true });
        errorHandler.current(error);
      }
    });
    return () => controller.abort();
  }, [load, attempt]);

  return {
    ...(state.load === load ? state : { loading: true, error: false, data: undefined }),
    retry: () => setAttempt((value) => value + 1),
  };
}
