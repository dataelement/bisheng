/**
 * F004 (T060): the parameters and the output of a generic tool call of a direct
 * answer. Clicking the tool row expands them under it, as knowledge and web
 * rows expand their results.
 */
import type { AgentToolCall } from '~/api/chatApi';
import { useLocalize } from '~/hooks';

interface ToolCodeOutputProps {
    toolCall: AgentToolCall;
}

function stringify(value: unknown): string {
    if (value === null || value === undefined) return '';
    if (typeof value === 'string') return value;
    try {
        return JSON.stringify(value, null, 2);
    } catch {
        return String(value);
    }
}

/** The code when the call's only meaningful parameter is a code string, else all parameters. */
export function toolCallInputText(args: AgentToolCall['args']): { text: string; isCode: boolean } {
    if (!args || Object.keys(args).length === 0) return { text: '', isCode: false };
    const code = args.code ?? args.python_code;
    if (typeof code === 'string' && code.trim()) return { text: code, isCode: true };
    return { text: stringify(args), isCode: false };
}

export function toolCallOutputText(results: AgentToolCall['results']): string {
    return stringify(results).trim();
}

/** The call has parameters or an output to show under its row (finished, not failed). */
export function hasToolCodeOutput(toolCall: AgentToolCall): boolean {
    if (toolCall.inflight || toolCall.error) return false;
    return !!toolCallInputText(toolCall.args).text || !!toolCallOutputText(toolCall.results);
}

/** The call's parameters (or code) and its output, shown when its row is expanded. */
export function ToolCodeOutput({ toolCall }: ToolCodeOutputProps) {
    const localize = useLocalize();
    const input = toolCallInputText(toolCall.args);
    const output = toolCallOutputText(toolCall.results);
    if (!input.text && !output) return null;

    const blockClass =
        'max-h-64 overflow-auto whitespace-pre-wrap break-words rounded-md bg-fill-1 px-3 py-2 font-mono text-caption text-text-2 scrollbar-os';
    return (
        <div className="flex min-w-0 flex-col gap-2" data-tool-code-output>
            {input.text && (
                <div className="flex min-w-0 flex-col gap-1">
                    <span className="text-caption text-text-3">
                        {localize(input.isCode ? 'runTool.code' : 'runTool.params')}
                    </span>
                    <pre className={blockClass}>{input.text}</pre>
                </div>
            )}
            {output && (
                <div className="flex min-w-0 flex-col gap-1">
                    <span className="text-caption text-text-3">{localize('runTool.output')}</span>
                    <pre className={blockClass}>{output}</pre>
                </div>
            )}
        </div>
    );
}
