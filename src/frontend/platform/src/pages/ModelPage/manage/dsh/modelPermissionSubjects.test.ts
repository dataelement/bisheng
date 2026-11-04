import { expect, it } from 'vitest'
import { modelDepartmentSource, toModelSubject } from './modelPermissionSubjects'

it('preserves scoped department ancestry for browsing, searching and implicit child selection', async () => {
    const source = modelDepartmentSource([
        { kind: 'DEPARTMENT', id: 10, name: 'Engineering', depth: 0 },
        { kind: 'DEPARTMENT', id: 11, name: 'Platform', depth: 1 },
        { kind: 'DEPARTMENT', id: 12, name: 'Product', depth: 0 },
        { kind: 'ROLE', id: 99, name: 'Reviewer', depth: 0 },
    ], '7')
    expect((await source.fetchChildren!(null)).map(node => node.id)).toEqual([10, 12])
    expect(await source.fetchChildren!(10)).toMatchObject([{ id: 11, path: '/10/11/' }])
    expect(await source.fetchSearch!('platform')).toMatchObject({
        total_matches: 1, roots: [{ id: 10, matched: false, children: [{ id: 11, matched: true }] }],
    })
    expect((await source.fetchPathTree!(11)).roots[0].children[0].id).toBe(11)
    expect((await source.fetchChildren!(null)).every(node => node.id !== 99)).toBe(true)
})
it('maps shared picker groups to model roles and preserves user and department kinds', () => {
    expect(toModelSubject({ type: 'user_group', id: 10, name: 'Reviewer' })).toEqual({ kind: 'ROLE', id: 10 })
    expect(toModelSubject({ type: 'department', id: 10, name: 'Engineering' })).toEqual({ kind: 'DEPARTMENT', id: 10 })
    expect(toModelSubject({ type: 'user', id: 10, name: 'Ada' })).toEqual({ kind: 'USER', id: 10 })
})

it('ships model permission labels in the namespace used by the dialog', async () => {
    const locales = [await import('../../../../../public/locales/zh-Hans/bs.json'), await import('../../../../../public/locales/en-US/bs.json')]
    for (const locale of locales) {
        const labels = locale.default.dsh.unified
        for (const key of ['searchUser', 'searchDepartment', 'searchRole', 'role', 'canUse', 'selectedSubjects', 'addToDraft', 'everyoneVisible', 'everyoneVisibleHelp', 'selectedVisible', 'selectedVisibleHelp'] as const) {
            expect(labels[key]).toBeTruthy()
        }
    }
})
