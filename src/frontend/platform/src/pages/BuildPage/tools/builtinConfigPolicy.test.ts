import { describe, expect, it } from 'vitest';
import { canConfigureBuiltinTool } from './builtinConfigPolicy';

describe('built-in configuration edit authorization', () => {
    it('allows any permission model that grants the edit action', () => {
        expect(canConfigureBuiltinTool(['visible', 'edit', 'delete', 'manage_permission'])).toBe(true);
        expect(canConfigureBuiltinTool(['visible', 'edit'])).toBe(true);
        expect(canConfigureBuiltinTool(['edit'])).toBe(true);
    });
    it('requires edit even when another action is granted', () => {
        expect(canConfigureBuiltinTool(['visible'])).toBe(false);
        expect(canConfigureBuiltinTool(['manage_permission', 'delete'])).toBe(false);
        expect(canConfigureBuiltinTool([])).toBe(false);
        expect(canConfigureBuiltinTool(undefined)).toBe(false);
    });
});
