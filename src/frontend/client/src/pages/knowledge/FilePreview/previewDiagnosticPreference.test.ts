import {
  getPreviewDiagnosticEnabled,
  setPreviewDiagnosticEnabled,
  subscribePreviewDiagnosticPreference,
} from './previewDiagnosticPreference';

describe('in-app preview diagnostic preference', () => {
  beforeEach(() => {
    setPreviewDiagnosticEnabled(false);
    sessionStorage.clear();
  });

  it('defaults to disabled without requiring an editable address', () => {
    expect(getPreviewDiagnosticEnabled()).toBe(false);
    setPreviewDiagnosticEnabled(true);
    expect(getPreviewDiagnosticEnabled()).toBe(true);
  });

  it('notifies a mounted collector immediately when toggled', () => {
    const states: boolean[] = [];
    const unsubscribe = subscribePreviewDiagnosticPreference(() => {
      states.push(getPreviewDiagnosticEnabled());
    });
    setPreviewDiagnosticEnabled(true);
    setPreviewDiagnosticEnabled(false);
    unsubscribe();
    setPreviewDiagnosticEnabled(true);
    expect(states).toEqual([true, false]);
    setPreviewDiagnosticEnabled(false);
  });

  it('expires after a day instead of remaining enabled indefinitely', () => {
    jest.useFakeTimers();
    try {
      setPreviewDiagnosticEnabled(true);
      jest.advanceTimersByTime(24 * 60 * 60 * 1000 + 1);
      expect(getPreviewDiagnosticEnabled()).toBe(false);
    } finally {
      setPreviewDiagnosticEnabled(false);
      jest.useRealTimers();
    }
  });
});
