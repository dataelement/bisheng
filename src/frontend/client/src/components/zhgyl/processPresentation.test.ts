import zh from '../../locales/zh-Hans/translation.json';
import { readableProcessDetail } from './processPresentation';

const dictionary = zh.zhgyl.flowCopy as Record<string, string>;
const t = (key: string) => dictionary[key.replace('zhgyl.flowCopy.', '')] || key;

test.each(['transport', 'customs'])('labels weight matching as gross weight under the current %s contract', scene => {
  // eslint-disable-next-line no-restricted-syntax -- This is the serialized tool protocol prefix, not UI copy.
  const text = readableProcessDetail('逐级匹配步骤：' + JSON.stringify([
    { criterion: 'weight', before: 6, after: 2, decision: 'same_condition' },
    { criterion: 'size', before: 2, after: 1, decision: 'keep_previous' },
  ]), scene, t);
  expect(text).toContain(`${dictionary.grossWeight}：6 → 2`);
  expect(text).toContain(`${dictionary.packageSize}：2 → 1`);
  expect(text).not.toContain(dictionary.netWeight);
});
