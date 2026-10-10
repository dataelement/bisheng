import { mergeDefaultCheckedSkills } from './useDefaultCheckedSkills';

const skill = (name: string, defaultChecked = false) => ({
    name,
    display_name: name.toUpperCase(),
    description: `${name} desc`,
    default_checked: defaultChecked,
});

describe('mergeDefaultCheckedSkills', () => {
    it('appends preselected skills after the user selection', () => {
        const selected = [{ name: 'a', display_name: 'A', description: 'a desc' }];
        const next = mergeDefaultCheckedSkills(selected, [skill('a'), skill('b', true), skill('c')]);
        expect(next.map((s) => s.name)).toEqual(['a', 'b']);
        // Chips carry only the picker fields, not the admin flag.
        expect(next[1]).toEqual({ name: 'b', display_name: 'B', description: 'b desc' });
    });

    it('does not duplicate a preselected skill the user already picked', () => {
        const selected = [{ name: 'b', display_name: 'B' }];
        const next = mergeDefaultCheckedSkills(selected, [skill('b', true)]);
        expect(next).toBe(selected);
    });

    it('returns the same array when nothing is preselected', () => {
        const selected: { name: string; display_name: string }[] = [];
        expect(mergeDefaultCheckedSkills(selected, [skill('a'), skill('b')])).toBe(selected);
    });
});
