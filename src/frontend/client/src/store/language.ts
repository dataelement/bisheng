import Cookies from 'js-cookie';
import { atomWithLocalStorage } from './utils';

/**
 * 推断并规范化默认语言，并清理不合法的本地存储
 */
const defaultLang = (): string => {
  const supported = new Set([
    'en','ar','de','es','et','fr','it','pl','pt-BR','pt-PT','ru','ja','ka','sv','ko','vi','tr','nl','id','he','fi','zh-Hans','zh-Hant'
  ]);
  const regionMap: Record<string, string> = { 'pt-br': 'pt-BR', 'pt-pt': 'pt-PT' };

  const normalize = (lang?: string | null): string | null => {
    if (!lang) return null;
    const lower = lang.toLowerCase();
    if (lower.startsWith('zh')) {
      return (lower.includes('tw') || lower.includes('hk') || lower.includes('hant')) ? 'zh-Hant' : 'zh-Hans';
    }
    const mapped = regionMap[lower];
    if (mapped && supported.has(mapped)) return mapped;
    const primary = lower.split('-')[0];
    return supported.has(primary) ? primary : null;
  };

  // 清理 i18next 语言 Cookie，避免冲突
  try { Cookies.remove('i18next', { path: '/' }); } catch {}

  // 读取并规范化历史值
  const cookieRaw = Cookies.get('lang');
  const storageRaw = localStorage.getItem('lang');

  const cookieNorm = normalize(cookieRaw);
  if (cookieRaw && !cookieNorm) {
    try { Cookies.remove('lang', { path: '/' }); } catch {}
  }
  if (cookieNorm) return cookieNorm;

  const storageNorm = normalize(storageRaw);
  if (storageRaw && !storageNorm) {
    try { localStorage.removeItem('lang'); } catch {}
  }
  if (storageNorm) return storageNorm;

  // 浏览器语言
  const browserNorm = normalize(navigator.language || (navigator.languages && navigator.languages[0]) || 'en');
  return browserNorm || 'en';
};

const lang = atomWithLocalStorage('lang', defaultLang());

export default { lang };
