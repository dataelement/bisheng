import { useEffect, useRef, useState } from 'react';
import request from '~/api/request';
import { useLocalize } from '~/hooks';
import type { WorkspaceScene } from './scenes';
import { resolveTransportBinding, stripTransportDetail, transportPayload, transportReference, type TransportTask, type TransportVersion } from './transportDetail';

interface TransportDetailProps {
  scene: WorkspaceScene;
  ready: boolean;
  chatId: string;
  locationKey: string;
  toolKey?: string;
  setDraft: (text: string) => void;
  toast: (key: string) => void;
}

export function useTransportDetail(props: TransportDetailProps) {
  const t = useLocalize();
  const { scene, setDraft } = props;
  const localizeRef = useRef(t);
  localizeRef.current = t;
  const latest = useRef(props);
  latest.current = props;
  const pending = useRef<AbortController | null>(null);
  const [resolving, setResolving] = useState(false);
  useEffect(() => () => pending.current?.abort(), [props.chatId, props.locationKey, props.scene]);
  useEffect(() => {
    if (scene !== 'transport') return;
    const fill = (event: MouseEvent) => {
      const link = event.target instanceof Element ? event.target.closest('a[href^="#transport-context-"]') : null;
      const reference = link?.getAttribute('href')?.match(/^#transport-context-[a-f0-9]{48}-(F[0-9]{2,})$/);
      if (!reference) return;
      event.preventDefault();
      setDraft(localizeRef.current('zhgyl.transportDraft', { reference: reference[1] }));
    };
    document.addEventListener('click', fill);
    return () => document.removeEventListener('click', fill);
  }, [scene, setDraft]);
  async function prepare(text: string): Promise<string | false> {
    const scope = latest.current;
    const clean = stripTransportDetail(text);
    const reference = transportReference(clean);
    if (scope.scene !== 'transport' || !reference) return clean;
    if (!scope.ready || pending.current) return false;
    if (scope.chatId === 'new' || !scope.toolKey) { scope.toast('zhgyl.transportMissing'); return false; }
    const controller = new AbortController();
    pending.current = controller;
    setResolving(true);
    const timer = window.setTimeout(() => controller.abort('timeout'), 8000);
    const current = () => {
      const now = latest.current;
      return now.ready && scope.chatId === now.chatId && scope.scene === now.scene && scope.locationKey === now.locationKey && scope.toolKey === now.toolKey;
    };
    const read = async <T,>(path: string, params: Record<string, string>): Promise<T[]> => {
      const result = await request.get<{ data: unknown }>(`/api/v1/linsight/workbench/${path}`, { params, signal: controller.signal });
      if (!Array.isArray(result.data)) throw new Error('Invalid transport task history');
      return result.data as T[];
    };
    try {
      const versions = await read<TransportVersion>('session-version-list', { session_id: scope.chatId });
      const binding = await resolveTransportBinding(scope.chatId, scope.toolKey, versions, id => read<TransportTask>('execute-task-detail', { session_version_id: id }));
      if (controller.signal.aborted || !current()) return false;
      if (!binding) { scope.toast('zhgyl.transportUnavailable'); return false; }
      return transportPayload(clean, reference, binding);
    } catch {
      if (current() && (!controller.signal.aborted || controller.signal.reason === 'timeout')) scope.toast('zhgyl.transportFailed');
      return false;
    } finally {
      window.clearTimeout(timer);
      if (pending.current === controller) { pending.current = null; setResolving(false); }
    }
  }
  return { prepare, resolving };
}
