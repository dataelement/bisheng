/** Resolve authored fonts consistently for the preview and editable export. */
const latinSans = /^(?:Arial(?: Narrow)?|Helvetica(?: Neue)?|Calibri|Aptos(?: Display)?|Inter|Roboto|DM Sans|sans-serif)$/iu;
const han = /\p{Script=Han}/u;
const firstFace = value => typeof value === 'string' ? value.split(',')[0].trim().replace(/^['"]|['"]$/gu, '') : undefined;

export function resolveFontFace(value, fallback = 'Arial', text = '', platform = process.platform) {
  const cjk = han.test(text);
  const fonts = value && typeof value === 'object' ? value : {};
  const localized = platform === 'darwin' ? fonts.mac ?? fonts.ea : platform === 'win32' ? fonts.win ?? fonts.ea : fonts.ea;
  const family = firstFace(typeof value === 'string' ? value : cjk ? localized ?? fonts.latin : fonts.latin ?? localized) || fallback;
  // Latin-only sans faces need an explicit Chinese face in DrawingML's a:ea.
  if (cjk && latinSans.test(family)) return platform === 'darwin' ? 'PingFang SC' : platform === 'win32' ? 'Microsoft YaHei' : 'Noto Sans CJK SC';
  return family;
}

export function resolveRunFonts(runs, family) {
  return runs.map(run => ({ ...run, options: { ...run.options,
    fontFace: resolveFontFace(run.options?.fontFace ?? family, 'Arial', run.text)
  } }));
}
