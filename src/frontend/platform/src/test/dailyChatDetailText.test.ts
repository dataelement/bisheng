import { expect, it } from 'vitest';
import { extractDailyDisplayText } from '@/pages/LogPage/useAppLog/dailyChatDetailText';

it('keeps an unused tool prep failure in the detail text', () => {
    const text = extractDailyDisplayText({
        text: JSON.stringify({
            msg: '你好',
            events: [
                { type: 'tool_call', tool_call_id: 'init_fail_abc', error: '联网搜索未配置' },
                { type: 'thinking', content: '先打个招呼' },
            ],
        }),
    });
    expect(text).toContain('联网搜索未配置');
    expect(text).toContain('你好');
    expect(text).toContain('先打个招呼');
});

it('keeps a real tool failure sentence as well', () => {
    const text = extractDailyDisplayText({
        text: JSON.stringify({
            msg: '部分结果',
            events: [{ type: 'tool_call', tool_call_id: 'call_1', error: '网络中断' }],
        }),
    });
    expect(text).toContain('网络中断');
    expect(text).toContain('部分结果');
});

it('leaves a plain answer unchanged', () => {
    expect(extractDailyDisplayText({ text: '好的' })).toBe('好的');
    expect(extractDailyDisplayText({
        isCreatedByUser: true,
        text: JSON.stringify({ query: '你好' }),
    })).toBe('你好');
});
