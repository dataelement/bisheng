/* eslint-disable no-restricted-syntax -- CJK fixtures assert the zh-Hans AC-75 explanation wording. */
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useAssistantStore } from '@/store/assistantStore';
import Setting from '../Setting';
import zhHans from '../../../../../../public/locales/zh-Hans/bs.json';
import enUS from '../../../../../../public/locales/en-US/bs.json';
import ja from '../../../../../../public/locales/ja/bs.json';

vi.mock('@/components/Pro/security/AssistantSetting', () => ({ default: () => null }));
vi.mock('@/components/bs-comp/selectComponent/knowledge', () => ({ default: () => null }));
vi.mock('@/components/bs-comp/sheets/ToolsSheet', () => ({ default: () => null }));
vi.mock('../ModelSelect', () => ({ default: () => null }));
vi.mock('../Temperature', () => ({ default: () => null }));

function renderSetting() {
    return render(<MemoryRouter><Setting /></MemoryRouter>);
}

function memorySwitch() {
    return screen.getByRole('switch', { name: 'build.assistantMemory' });
}

beforeEach(() => useAssistantStore.getState().destroy());
afterEach(cleanup);

describe('assistant memory switch', () => {
    it('AC-69: the switch is off for an assistant that never turned it on', () => {
        renderSetting();
        expect(memorySwitch()).toHaveAttribute('aria-checked', 'false');
        expect(useAssistantStore.getState().assistantState.memory_enabled).toBeFalsy();
    });

    it('AC-69: toggling writes memory_enabled into the assistant state that the save request sends', () => {
        renderSetting();
        fireEvent.click(memorySwitch());
        expect(useAssistantStore.getState().assistantState.memory_enabled).toBe(true);
        expect(useAssistantStore.getState().changed).toBe(true);
        expect(memorySwitch()).toHaveAttribute('aria-checked', 'true');
        fireEvent.click(memorySwitch());
        expect(useAssistantStore.getState().assistantState.memory_enabled).toBe(false);
    });

    it('AC-69: a saved assistant with memory on shows the switch on', () => {
        useAssistantStore.setState(state => ({ assistantState: { ...state.assistantState, memory_enabled: true } }));
        renderSetting();
        expect(memorySwitch()).toHaveAttribute('aria-checked', 'true');
    });

    it('AC-75: the explanation is shown next to the switch in all three languages', () => {
        renderSetting();
        expect(screen.getByText('build.assistantMemoryDesc')).toBeInTheDocument();
        const zhDesc = zhHans.build.assistantMemoryDesc;
        expect(zhDesc).toContain('读取并写入');
        expect(zhDesc).toContain('回答与输出');
        expect(zhDesc).toContain('互不可见');
        for (const locale of [zhHans, enUS, ja]) {
            expect(locale.build.memory.length).toBeGreaterThan(0);
            expect(locale.build.assistantMemory.length).toBeGreaterThan(0);
            expect(locale.build.assistantMemoryDesc.length).toBeGreaterThan(0);
        }
    });
});
