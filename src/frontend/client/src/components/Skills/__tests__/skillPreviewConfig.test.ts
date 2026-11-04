import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const root = resolve(__dirname, '../../..');

function source(path: string) {
  return readFileSync(resolve(root, path), 'utf8');
}

it('does not read the retired skill center preview flag', () => {
  const files = [
    'components/Skills/types.ts',
    'layouts/MainLayout.tsx',
    'routes/index.tsx',
    'components/Chat/Input/ChatKnowledge.tsx',
    'components/Linsight/Input/PlusMenu.tsx',
    'components/Skills/SkillMenuEntries.tsx',
  ];
  for (const file of files) {
    expect(source(file)).not.toContain('skillCenterPreviewEnabled');
  }
});
