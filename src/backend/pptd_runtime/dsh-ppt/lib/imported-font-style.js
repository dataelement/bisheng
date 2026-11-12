/** Resolve Apple's family-plus-weight names to Windows' family/weight contract.
 * Other authored faces and macOS source typography keep their original identity.
 * @param {string | undefined} family
 * @param {NodeJS.Platform} [platform]
 * @returns {{fontFamily?: string, bold?: boolean}}
 */
export function resolveImportedFontStyle(family, platform = process.platform) {
  if (typeof family !== 'string') return {};
  const source = { fontFamily: family };
  if (platform !== 'win32') return source;
  const pingFang = /^PingFang[ -]*SC(?:[ -]*(Ultralight|Thin|Light|Regular|Medium|Semibold))?$/iu.exec(family.trim());
  if (!pingFang) return source;
  const weight = pingFang[1]?.toLowerCase();
  return {
    fontFamily: ['ultralight', 'thin', 'light'].includes(weight) ? 'Microsoft YaHei Light' : 'Microsoft YaHei',
    ...(weight === 'semibold' ? { bold: true } : {})
  };
}
