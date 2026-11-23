type Translate = (key: string) => string

/**
 * Text of the organisation column — the same three sentinel captions on every
 * audit tab, its CSV and the backend runtime-record CSV (spec AC-10).
 */
export const orgLabel = (deptId: number | null | undefined, path: string | null | undefined, t: Translate): string => {
  if (deptId == null) return t('log.org.unrecorded')
  if (deptId === 0) return t('log.org.none')
  if (deptId < 0) return t('log.org.notApplicable')
  return path || t('log.org.unrecorded')
}
