import { previewDiagnosticRecorder } from './previewDiagnostics';

const STORAGE_KEY = 'bs:preview-diagnostics-until';
const CHANGE_EVENT = 'bs:preview-diagnostics-change';
const MAX_AGE = 24 * 60 * 60 * 1000;
let memoryDeadline = 0;

/** Diagnostic-only preference; sessionStorage keeps it local to this embedded window. */
export function getPreviewDiagnosticRemaining(): number {
  let deadline = memoryDeadline;
  try {
    deadline = Number(sessionStorage.getItem(STORAGE_KEY)) || memoryDeadline;
  } catch {
    // The host may deny storage; the in-memory toggle still works until reload.
  }
  return Math.max(0, deadline - Date.now());
}

export function getPreviewDiagnosticEnabled(): boolean {
  return getPreviewDiagnosticRemaining() > 0;
}

export function setPreviewDiagnosticEnabled(enabled: boolean): void {
  memoryDeadline = enabled ? Date.now() + MAX_AGE : 0;
  try {
    if (enabled) sessionStorage.setItem(STORAGE_KEY, String(memoryDeadline));
    else sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    // No credentials or business state are stored here.
  }
  if (!enabled) previewDiagnosticRecorder.stop();
  window.dispatchEvent(new Event(CHANGE_EVENT));
}

export function subscribePreviewDiagnosticPreference(listener: () => void): () => void {
  window.addEventListener(CHANGE_EVENT, listener);
  window.addEventListener('focus', listener);
  document.addEventListener('visibilitychange', listener);
  return () => {
    window.removeEventListener(CHANGE_EVENT, listener);
    window.removeEventListener('focus', listener);
    document.removeEventListener('visibilitychange', listener);
  };
}
