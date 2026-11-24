import { describe, expect, it } from 'vitest';
import { canConfigureBuiltinTool } from './builtinConfigPolicy';

describe('built-in configuration administration', () => {
    it('admits global and own-tenant administrators', () => {
        expect(canConfigureBuiltinTool({ is_global_super: true }, 5)).toBe(true);
        expect(canConfigureBuiltinTool({ is_child_admin: true, tenant_id: 5 }, 5)).toBe(true);
    });
    it('rejects foreign and Root tools for child administrators', () => {
        const user = { is_child_admin: true, tenant_id: 5, leaf_tenant_id: 5 };
        expect(canConfigureBuiltinTool(user, 1)).toBe(false);
        expect(canConfigureBuiltinTool(user, 6)).toBe(false);
    });
    it('does not treat resource ownership or legacy role labels as administrative identity', () => {
        expect(canConfigureBuiltinTool({ role: 'owner', tenant_id: 5 }, 5)).toBe(false);
        expect(canConfigureBuiltinTool({ role: 'manager', tenant_id: 5 }, 5)).toBe(false);
        expect(canConfigureBuiltinTool({ role: 'admin', tenant_id: 5 }, 5)).toBe(false);
        expect(canConfigureBuiltinTool(null, 5)).toBe(false);
    });
});
