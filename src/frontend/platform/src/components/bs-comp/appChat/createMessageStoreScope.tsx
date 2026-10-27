import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';
import { useStore, type StoreApi } from 'zustand';
interface HostServices { dispose: () => void }
/** Context passes each panel's store and host services without a global singleton. */
export function createMessageStoreScope<T, S extends HostServices>(createStore: () => StoreApi<T> & { services: S }) {
    const Context = createContext<(StoreApi<T> & { services: S }) | null>(null);
    function MessageStoreProvider({ children }: { children: ReactNode }) {
        const [store] = useState(createStore);
        useEffect(() => () => store.services.dispose(), [store]);
        return <Context.Provider value={store}>{children}</Context.Provider>;
    }
    function useMessageStore(): T & S;
    function useMessageStore<U>(selector: (state: T & S) => U): U;
    function useMessageStore<U>(selector?: (state: T & S) => U): U | (T & S) {
        const store = useContext(Context);
        if (!store) throw new Error('Conversation store provider is missing');
        const value = useStore(store, selector ? state => selector({ ...state, ...store.services }) : state => state as unknown as U);
        return selector ? value : { ...value as unknown as T, ...store.services };
    }
    return { MessageStoreProvider, useMessageStore };
}
