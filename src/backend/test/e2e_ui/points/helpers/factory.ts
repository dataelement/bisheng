import { execFileSync } from 'node:child_process';
import path from 'node:path';

const backendRoot = path.resolve(__dirname, '../../../..');
const python = path.join(backendRoot, '.venv/bin/python');
const script = path.join(__dirname, 'factory_trigger.py');

/**
 * 调用统一 Gate 数据工厂（造数 / 对账 / 开关负例）。
 * @param args CLI 参数，如 ['award_g2', '4', '123', '10']
 */
export function runFactory(args: string[]): Record<string, unknown> {
  const stdout = execFileSync(python, [script, ...args], {
    cwd: backendRoot,
    env: {
      ...process.env,
      config: 'config.yaml',
      PYTHONPATH: backendRoot,
    },
    encoding: 'utf-8',
    maxBuffer: 4 * 1024 * 1024,
  });
  const lines = stdout
    .trim()
    .split('\n')
    .filter((line) => line.startsWith('{') || line.startsWith('['));
  const last = lines[lines.length - 1];
  if (!last) {
    throw new Error(`factory_trigger produced no JSON: ${stdout.slice(-500)}`);
  }
  return JSON.parse(last) as Record<string, unknown>;
}
