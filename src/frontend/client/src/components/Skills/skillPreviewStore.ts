import { v4 as uuid } from 'uuid';
import { SkillError, type PersonalSkill, type SkillManifest } from './types';

const STORE = 'skills';

function openStore(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    if (!globalThis.indexedDB) { reject(new SkillError('storage')); return; }
    const request = indexedDB.open('bisheng-skill-center-preview-v1', 1);
    request.onupgradeneeded = () => request.result.createObjectStore(STORE, { keyPath: 'id' }).createIndex('scope', 'scope');
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(new SkillError('storage'));
    request.onblocked = () => reject(new SkillError('storage'));
  });
}

export async function listPersonalSkills(scope: string): Promise<PersonalSkill[]> {
  const db = await openStore();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE, 'readonly');
    const request = tx.objectStore(STORE).index('scope').getAll(scope);
    tx.oncomplete = () => { db.close(); resolve(request.result as PersonalSkill[]); };
    tx.onabort = () => { db.close(); reject(new SkillError('storage')); };
  });
}

type Change =
  | { kind: 'save'; manifest: SkillManifest; file: File; target?: PersonalSkill }
  | { kind: 'toggle'; target: PersonalSkill; enabled: boolean }
  | { kind: 'delete'; target: PersonalSkill };

export async function changePersonalSkill(scope: string, change: Change): Promise<void> {
  if (!scope) throw new SkillError('identity');
  const db = await openStore();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE, 'readwrite');
    const store = tx.objectStore(STORE);
    const request = store.index('scope').getAll(scope);
    let failure = new SkillError('storage');
    tx.oncomplete = () => { db.close(); resolve(); };
    tx.onabort = () => { db.close(); reject(failure); };
    request.onsuccess = () => {
      const skills = request.result as PersonalSkill[];
      const current = change.target && skills.find((skill) => skill.id === change.target?.id);
      if (change.target && (!current || current.revision !== change.target.revision)) {
        failure = new SkillError('conflict'); tx.abort(); return;
      }
      if (change.kind === 'delete' && current) { store.delete(current.id); return; }
      if (change.kind === 'toggle' && current) {
        store.put({ ...current, enabled: change.enabled, revision: uuid() }); return;
      }
      if (change.kind === 'save') {
        if (skills.some((skill) => skill.name === change.manifest.name && skill.id !== current?.id)) {
          failure = new SkillError('duplicate'); tx.abort(); return;
        }
        const record: PersonalSkill = {
          ...change.manifest,
          id: current?.id ?? uuid(),
          scope,
          source: 'personal',
          enabled: current?.enabled ?? true,
          updatedAt: new Date().toISOString(),
          revision: uuid(),
          file: change.file,
        };
        store.put(record);
      }
    };
  });
}
