import type { LinsightInfo } from '~/store/linsight';
import { runningConversationIds } from './runningConversations';

const task = (session_id: string, status: string, sessionSteps: unknown[] = []) =>
  ({ session_id, status, sessionSteps, tasks: [] }) as unknown as LinsightInfo;
const tasks = (...rows: LinsightInfo[]) => new Map(rows.map((row, index) => [`version-${index}`, row]));

it('combines streaming answers with task runs that still drive the spinner', () => {
  const ids = runningConversationIds(
    { 'chat-b': true, 'chat-a': true, 'chat-idle': false, new: true, 'new:scope:draft': true, 'bad id': true },
    tasks(
      task('task-running', 'running'),
      task('task-starting', 'not_started'),
      task('task-done', 'completed'),
      task('task-parked', 'running', [{ step_type: 'call_user_input', is_completed: false }]),
      task('chat-a', 'sopGenerating'),
    ),
  );
  expect(ids).toEqual(['chat-a', 'chat-b', 'task-running', 'task-starting']);
});
