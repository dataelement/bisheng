import { t } from "i18next";

// Placeholder for an assistant's role and tasks, shared by the create dialog and the portrait panel
export function assistantRoleExample(): string {
    return `${t('build.example', { ns: 'bs' })}：
${t('build.exampleOne', { ns: 'bs' })}
${t('build.exampleTwo', { ns: 'bs' })}
1. XX
2. XX
3. …`
}
