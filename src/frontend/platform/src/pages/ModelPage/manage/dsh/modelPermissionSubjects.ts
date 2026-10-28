import type { UseLazyDepartmentTreeOptions } from '@/components/bs-comp/department/useLazyDepartmentTree'
import type { SelectedSubject, SubjectType } from '@/components/bs-comp/permission/types'
import type { PolicySubject, PolicySubjectOption } from '@/controllers/API/dshUnified'
import type { DepartmentTreeNode } from '@/types/api/department'

// The shared group picker presents model ROLE subjects. API writes always use ROLE.
export const modelSubjectKinds: Record<SubjectType, PolicySubject['kind']> = {
    user: 'USER', department: 'DEPARTMENT', user_group: 'ROLE',
}
export function toModelSubject(subject: SelectedSubject): PolicySubject {
    return { kind: modelSubjectKinds[subject.type], id: subject.id }
}

/** Adapt the authorized, depth-first policy catalogue to the shared department tree. */
export function modelDepartmentSource(options: PolicySubjectOption[], scope: string): UseLazyDepartmentTreeOptions {
    const nodes: DepartmentTreeNode[] = []
    const ancestors: DepartmentTreeNode[] = []
    for (const option of options.filter(item => item.kind === 'DEPARTMENT')) {
        ancestors.length = Math.min(ancestors.length, option.depth)
        const parent = ancestors.at(-1)
        const node: DepartmentTreeNode = {
            id: option.id, dept_id: String(option.id), name: option.name,
            parent_id: parent?.id ?? null, path: `${parent?.path ?? '/'}${option.id}/`,
            sort_order: nodes.length, source: 'policy', status: 'active',
            is_tenant_root: false, mounted_tenant_id: null, children: [],
        }
        nodes.push(node)
        ancestors.push(node)
    }
    for (const node of nodes) node.has_children = nodes.some(child => child.parent_id === node.id)
    const prune = (matches: DepartmentTreeNode[]) => {
        const keep = new Set(matches.flatMap(node => node.path.split('/').filter(Boolean).map(Number)))
        const build = (parentId: number | null): DepartmentTreeNode[] => nodes
            .filter(node => node.parent_id === parentId && keep.has(node.id))
            .map(node => ({ ...node, matched: matches.some(match => match.id === node.id), children: build(node.id) }))
        return { roots: build(null), total_matches: matches.length, truncated: false }
    }
    return {
        autoLoad: true, autoExpandRoots: true,
        cacheKey: `model-policy:${scope}:${JSON.stringify(options)}`,
        fetchChildren: async parentId => nodes.filter(node => node.parent_id === parentId),
        fetchSearch: async keyword => prune(nodes.filter(node => node.name.toLocaleLowerCase().includes(keyword.toLocaleLowerCase()))),
        fetchPathTree: async id => prune(nodes.filter(node => node.id === id)),
    }
}
