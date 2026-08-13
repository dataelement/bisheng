import { resolveTaskModeOnNavigation, type TaskModeNavigationInput } from './resolveTaskMode';

const base: TaskModeNavigationInput = {
    conversationId: 'c1',
    isTaskConversation: false,
    canUseTaskMode: true,
    navTaskMode: undefined,
    isSelfRewrite: false,
    userToggled: false,
};

const resolve = (overrides: Partial<TaskModeNavigationInput> = {}) =>
    resolveTaskModeOnNavigation({ ...base, ...overrides });

describe('resolveTaskModeOnNavigation', () => {
    // The production bug: a task conversation whose toggle was cleared by an
    // in-conversation navigation (sidebar 首页, whose target IS the current
    // pathname) never came back, because the reset ran on every location.key
    // change while the restore's deps were constant within the visit. The user
    // saw a lit button the whole time (`taskMode || taskRunning`) and their next
    // turn silently went to the daily chain.
    it('keeps a task conversation in task mode across repeated navigations', () => {
        expect(resolve({ isTaskConversation: true })).toBe(true);
        // Same inputs again — a second navigation must not flip it off.
        expect(resolve({ isTaskConversation: true })).toBe(true);
    });

    it('keeps a daily conversation on daily', () => {
        expect(resolve({ isTaskConversation: false })).toBe(false);
    });

    // History loads asynchronously: isTaskConversation is false on the first
    // pass and true once the rows land, so the toggle settles off then on.
    it('settles off before history resolves, then on', () => {
        expect(resolve({ isTaskConversation: false })).toBe(false);
        expect(resolve({ isTaskConversation: true })).toBe(true);
    });

    it('never enters task mode when the user cannot use it', () => {
        expect(resolve({ isTaskConversation: true, canUseTaskMode: false })).toBe(false);
    });

    describe('manual toggle', () => {
        it('is respected within the conversation it was made in', () => {
            // User turned task mode OFF in a task conversation; navigating must
            // not "restore" it against their wishes.
            expect(resolve({ isTaskConversation: true, userToggled: true })).toBeNull();
        });

        it('is respected in a daily conversation too', () => {
            expect(resolve({ isTaskConversation: false, userToggled: true })).toBeNull();
        });
    });

    describe('post-submit self-rewrite (/c/new -> /c/<id>)', () => {
        it('leaves the composing mode alone', () => {
            // Same conversation, new URL: the history has not loaded yet, so
            // deriving here would knock the user out of the mode they just
            // submitted in.
            expect(resolve({ isSelfRewrite: true, isTaskConversation: false })).toBeNull();
        });
    });

    describe('/c/new', () => {
        it('honours a navigation that declares task mode', () => {
            expect(resolve({ conversationId: 'new', navTaskMode: true })).toBe(true);
        });

        it('honours a navigation that declares daily', () => {
            expect(resolve({ conversationId: 'new', navTaskMode: false })).toBe(false);
        });

        // Regression: `newConversation` fires its own state-less
        // navigate('/c/new') a tick after the sidebar button's. Reading the
        // absent state as "daily" made 新建任务 open a daily chat until clicked
        // a second time.
        it('leaves the toggle alone when the navigation declares nothing', () => {
            expect(resolve({ conversationId: 'new', navTaskMode: undefined })).toBeNull();
        });

        it('ignores the loaded-history signal entirely', () => {
            expect(
                resolve({ conversationId: 'new', isTaskConversation: true, navTaskMode: undefined }),
            ).toBeNull();
        });
    });
});
