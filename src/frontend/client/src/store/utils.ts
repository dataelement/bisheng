import { atom } from 'recoil';

interface PreferenceStorage<T> {
  read: () => T;
  write: (value: T) => void;
}

// Improved helper function to create atoms with localStorage
export function atomWithLocalStorage<T>(key: string, defaultValue: T, storage?: PreferenceStorage<T>) {
  return atom<T>({
    key,
    default: defaultValue,
    effects_UNSTABLE: [
      ({ setSelf, onSet }) => {
        if (storage) {
          setSelf(storage.read());
          onSet(storage.write);
          return;
        }

        const savedValue = localStorage.getItem(key);
        if (savedValue !== null) {
          try {
            const parsedValue = JSON.parse(savedValue);
            setSelf(parsedValue);
          } catch (e) {
            console.error(
              `Error parsing localStorage key "${key}", \`savedValue\`: defaultValue, error:`,
              e,
            );
            localStorage.setItem(key, JSON.stringify(defaultValue));
            setSelf(defaultValue);
          }
        }

        onSet((newValue: T) => {
          localStorage.setItem(key, JSON.stringify(newValue));
        });
      },
    ],
  });
}
