import { useSpaceCapabilities } from './useSpaceCapabilities';
import { useEffect, useMemo, useRef, useState } from 'react';
import { v4 as uuid } from 'uuid';
import { checkProviderFile, sendProviderFile, type UploadOutcome, type UploadReceipt, type UploadTarget } from '~/api/knowledgeProviderUploads';

type State = UploadOutcome['state'] | 'sending' | 'not_sent';
export type ProviderUploadRow = { key: string; name: string; state: State; busy: boolean };
type Entry = { row: ProviderUploadRow; target: UploadTarget; file?: File; checksum?: string; receipt?: UploadReceipt };
const sameReceipt = (a: UploadReceipt, b: UploadReceipt) => a.operation_id === b.operation_id && a.file_id === b.file_id && a.version_id === b.version_id;

export function useProviderFileUploads(spaceId: string, parentId: string | undefined, hasUploadAction: boolean,
  nativeUpload: (files: File[]) => void, onReceived: () => void) {
  const { identity, capabilities, proof, tagScope } = useSpaceCapabilities(spaceId);
  const unavailable = capabilities.error as { status_code?: number; response?: { headers?: Record<string, unknown> } } | null;
  const wikiTenant = proof?.native === false ? proof.tenant
    : capabilities.isError && !capabilities.isFetching && unavailable?.status_code === 18089
      ? unavailable.response?.headers?.['x-management-tenant'] : undefined;
  const canUploadNativeExtras = hasUploadAction && proof?.native === true;
  const canSend = hasUploadAction && proof?.providerUpload === true;
  const scopeKey = JSON.stringify([spaceId, parentId, identity, capabilities.data?.tenant, capabilities.data?.revision]);
  const { entries: store } = useMemo(() => ({ scopeKey, entries: new Map<string, Entry>() }), [scopeKey]);
  const canCheck = hasUploadAction && proof?.native === false;
  const active = useRef({ store, canSend, canCheck, canUploadNativeExtras, onReceived });
  active.current = { store, canSend, canCheck, canUploadNativeExtras, onReceived };
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; store.clear(); };
  }, [store]);
  const [, render] = useState(0);
  const inScope = () => mounted.current && active.current.store === store;
  const current = () => inScope() && active.current.canSend;
  const update = () => { if (inScope()) render(n => n + 1); };
  const run = async (entry: Entry, lookup: boolean) => {
    if (!inScope() || !(lookup ? active.current.canCheck : active.current.canSend) || entry.row.busy) return;
    entry.row = { ...entry.row, busy: true }; update();
    try {
      let response: UploadOutcome;
      if (lookup) response = await checkProviderFile(entry.target);
      else {
        const file = entry.file;
        if (!file) return;
        if (!entry.checksum) {
          try {
            const bytes = await file.arrayBuffer();
            const hash = await crypto.subtle.digest('SHA-256', bytes);
            entry.checksum = Array.from(new Uint8Array(hash), b => b.toString(16).padStart(2, '0')).join('');
          } catch {
            // No network write has started; do not offer a receipt lookup.
            entry.row.state = 'not_sent'; return;
          }
        }
        if (!current()) { entry.row.state = 'not_sent'; return; }
        response = await sendProviderFile(entry.target, file, entry.checksum);
      }
      if (response.receipt && entry.receipt && !sameReceipt(entry.receipt, response.receipt)) {
        entry.row.state = 'conflict';
      } else {
        entry.receipt ??= response.receipt;
        entry.row.state = response.state;
      }
      if (entry.row.state === 'accepted' || entry.row.state === 'conflict') entry.file = undefined;
      return entry.row.state === 'accepted';
    } catch {
      // A lost response does not prove non-receipt. Only a read is safe now.
      entry.row.state = 'unknown';
    } finally {
      entry.row = { ...entry.row, busy: false }; update();
    }
  };
  const uploadFiles = async (list?: FileList | File[]) => {
    if (!list?.length || !inScope()) return;
    const files = Array.from(list);
    if (canUploadNativeExtras && active.current.canUploadNativeExtras) { nativeUpload(files); return; }
    if (!current() || !proof) return;
    const entries = files.map(file => {
      const key = uuid();
      const entry: Entry = { file, row: { key, name: file.name, state: 'sending', busy: false }, target: { key, spaceId, parentId, tenant: proof.tenant } };
      store.set(key, entry); return entry;
    });
    update();
    let received = false;
    for (const entry of entries) {
      if (!current()) { entry.row.state = 'not_sent'; update(); continue; }
      if (await run(entry, false)) received = true;
    }
    // Refresh once: refreshing the file list also invalidates container permissions.
    if (received && inScope()) active.current.onReceived();
  };
  const recover = async (key: string, lookup: boolean) => {
    const entry = store.get(key);
    if (!entry || (lookup ? entry.row.state !== 'unknown' : !['reupload_required', 'not_sent'].includes(entry.row.state))) return;
    if (await run(entry, lookup) && inScope()) active.current.onReceived();
  };
  const retry = (key: string) => void recover(key, false);
  const check = (key: string) => void recover(key, true);
  return { tagScope, uploadFiles, retry, check, items: hasUploadAction ? Array.from(store.values(), e => ({ ...e.row, busy: e.row.busy || !(e.row.state === 'unknown' ? canCheck : canSend) })) : [],
    // An unready binding cannot supply upload capabilities. Only the independently authorized Wiki status may identify it.
    wikiDiscovery: typeof wikiTenant === 'string' && /^[1-9]\d*$/.test(wikiTenant) ? { tenant: wikiTenant } : null,
    canUploadFile: canUploadNativeExtras || canSend, canUploadNativeExtras, canPreview: proof?.preview === true, isNative: proof?.native === true };
}
