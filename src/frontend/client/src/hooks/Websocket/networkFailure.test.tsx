import { act, renderHook } from '@testing-library/react';
import { useLinsightWebSocket } from './index';

const mockUpdate = jest.fn();
const mockReconcile = jest.fn().mockResolvedValue(undefined);
const mockQueryClient = {};
let mockStatus = 'running';
jest.mock('@tanstack/react-query', () => ({ useQueryClient: () => mockQueryClient }));
jest.mock('../useLinsightManager', () => ({
    useLinsightManager: () => ({
        getLinsight: () => ({ status: mockStatus }),
        updateLinsight: mockUpdate,
        reconcileLinsightFromServer: mockReconcile,
    }),
}));
jest.mock('~/api/linsight', () => ({ userInputLinsightEvent: jest.fn(), userStopLinsightEvent: jest.fn() }));
jest.mock('~/Providers', () => ({ useToastContext: () => ({ showToast: jest.fn() }) }));
jest.mock('~/utils', () => ({ toggleNav: jest.fn() }));
jest.mock('~/store/linsight', () => ({ SopStatus: { Running: 'running', Stoped: 'stoped', completed: 'completed' } }));
jest.mock('~/hooks/queries/endpoints/modelRateLimitPolling', () => ({ observeModelRateLimitEvent: jest.fn() }));
jest.mock('~/components/Linsight/Execution/stepFold', () => ({ appendStepFrame: jest.fn() }));

class SocketDouble {
    static OPEN = 1;
    static instances: SocketDouble[] = [];
    readyState = 0;
    onopen?: () => void;
    onclose?: () => void;
    onerror?: () => void;
    constructor() { SocketDouble.instances.push(this); }
    open() { this.readyState = 1; this.onopen?.(); }
    close() { this.readyState = 3; this.onclose?.(); }
}

describe('task transport disconnect', () => {
    const originalSocket = globalThis.WebSocket;
    let online = true;
    let version = 0;
    beforeEach(() => {
        jest.useFakeTimers();
        jest.clearAllMocks();
        SocketDouble.instances = [];
        mockStatus = 'running';
        online = true;
        Object.defineProperty(navigator, 'onLine', { configurable: true, get: () => online });
        globalThis.WebSocket = SocketDouble as unknown as typeof WebSocket;
    });
    afterEach(() => {
        globalThis.WebSocket = originalSocket;
        Reflect.deleteProperty(navigator, 'onLine');
        jest.useRealTimers();
    });
    function mount(id = `network-test-${++version}`) {
        return renderHook(() => useLinsightWebSocket(id));
    }

    it('shows connection loss without changing the task to failed, then clears after reconnect', () => {
        const { result, unmount } = mount();
        act(() => SocketDouble.instances[0].open());
        act(() => {
            online = false;
            window.dispatchEvent(new Event('offline'));
        });
        expect(result.current.networkFailure?.category).toBe('network');
        expect(mockUpdate).not.toHaveBeenCalled();
        act(() => jest.advanceTimersByTime(5000));
        expect(SocketDouble.instances).toHaveLength(1);
        act(() => {
            online = true;
            window.dispatchEvent(new Event('online'));
        });
        expect(SocketDouble.instances).toHaveLength(2);
        act(() => SocketDouble.instances[1].open());
        expect(result.current.networkFailure).toBeUndefined();
        expect(mockReconcile).toHaveBeenCalledTimes(2);
        unmount();
    });

    it('also surfaces an unexpected socket close while the browser is online', () => {
        const { result, unmount } = mount();
        act(() => SocketDouble.instances[0].close());
        expect(result.current.networkFailure?.category).toBe('network');
        act(() => jest.advanceTimersByTime(1000));
        expect(SocketDouble.instances).toHaveLength(2);
        unmount();
    });

    it('ignores offline events after unmount or when the task is complete', () => {
        mockStatus = 'completed';
        const { result, unmount } = mount();
        act(() => window.dispatchEvent(new Event('offline')));
        expect(result.current.networkFailure).toBeUndefined();
        expect(SocketDouble.instances).toHaveLength(0);
        unmount();
        act(() => window.dispatchEvent(new Event('online')));
        expect(SocketDouble.instances).toHaveLength(0);
    });

    it('gives a remounted running task its own socket and reconnect callbacks', () => {
        const id = `network-test-${++version}`;
        const first = mount(id);
        act(() => SocketDouble.instances[0].open());
        first.unmount();
        expect(SocketDouble.instances[0].readyState).toBe(3);
        const second = mount(id);
        expect(SocketDouble.instances).toHaveLength(2);
        act(() => SocketDouble.instances[1].open());
        act(() => SocketDouble.instances[1].close());
        expect(second.result.current.networkFailure?.category).toBe('network');
        act(() => jest.advanceTimersByTime(1000));
        expect(SocketDouble.instances).toHaveLength(3);
        second.unmount();
    });
});
