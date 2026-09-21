const DSH_SECTION_DEFINITIONS = [
    { value: 'license', labelKey: 'dsh.licenseAndSeats', visible: true },
    { value: 'models', labelKey: 'dsh.modelsAndQuotas', visible: true },
    { value: 'usage', labelKey: 'dsh.userUsage', visible: true },
    // Keep the audit implementation available for the upcoming design revision.
    { value: 'operations', labelKey: 'dsh.operations', visible: false },
    { value: 'access', labelKey: 'dsh.accessSettings', visible: true },
    { value: 'plugins', labelKey: 'dsh.enterprisePlugins', visible: true },
] as const

export type DshSection = (typeof DSH_SECTION_DEFINITIONS)[number]['value']
export const DSH_SECTIONS = DSH_SECTION_DEFINITIONS.filter(({ visible }) => visible)

export function resolveDshSection(
    search: string,
    availableSections: readonly DshSection[] = DSH_SECTIONS.map(({ value }) => value),
): DshSection {
    const requestedSection = new URLSearchParams(search).get('tab') as DshSection | null
    return requestedSection && availableSections.includes(requestedSection)
        ? requestedSection
        : availableSections[0] ?? 'license'
}
