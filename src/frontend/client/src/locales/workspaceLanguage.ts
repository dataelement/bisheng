import Cookies from 'js-cookie';

const LANGUAGE_KEY = 'lang';
const SHARED_LANGUAGE_KEY = 'i18nextLng';

export type WorkspaceLanguage = 'zh-Hans' | 'en' | 'ja';

/** Map browser tags and legacy saved values to the translation bundles we ship. */
export function normalizeWorkspaceLanguage(value: unknown): WorkspaceLanguage | undefined {
  if (typeof value !== 'string') return undefined;
  const primary = value.trim().toLowerCase().split('-')[0];
  if (primary === 'zh') return 'zh-Hans';
  if (primary === 'en') return 'en';
  if (primary === 'ja' && !window.APP_CONFIG?.disableJa) return 'ja';
  return undefined;
}

function readSavedLanguage(): WorkspaceLanguage | undefined {
  try {
    const raw = window.localStorage.getItem(LANGUAGE_KEY);
    if (!raw) return undefined;
    try {
      return normalizeWorkspaceLanguage(JSON.parse(raw));
    } catch {
      // Older workspaces stored the tag directly.
      return normalizeWorkspaceLanguage(raw);
    }
  } catch {
    // Some embedded browsers block localStorage.
    return undefined;
  }
}

export function readWorkspaceLanguage(): WorkspaceLanguage {
  const saved = readSavedLanguage();
  if (saved) return saved;

  const cookie = normalizeWorkspaceLanguage(Cookies.get(LANGUAGE_KEY));
  if (cookie) return cookie;

  try {
    const shared = normalizeWorkspaceLanguage(window.localStorage.getItem(SHARED_LANGUAGE_KEY));
    if (shared) return shared;
  } catch {
    // Use the browser preference when localStorage is unavailable.
  }

  return normalizeWorkspaceLanguage(navigator.language || navigator.languages?.[0]) || 'en';
}

export function saveWorkspaceLanguage(value: string): void {
  const language = normalizeWorkspaceLanguage(value) || 'en';
  try {
    window.localStorage.setItem(LANGUAGE_KEY, JSON.stringify(language));
    window.localStorage.setItem(SHARED_LANGUAGE_KEY, language);
  } catch {
    // The language cookie is the fallback when localStorage is unavailable.
  }
  Cookies.set(LANGUAGE_KEY, language, { expires: 365, path: '/' });
}
