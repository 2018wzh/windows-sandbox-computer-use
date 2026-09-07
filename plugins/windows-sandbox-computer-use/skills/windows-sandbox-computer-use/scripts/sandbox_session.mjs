import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { fileURLToPath } from 'node:url';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { randomUUID } from 'node:crypto';

const exec = promisify(execFile);
const adapter = fileURLToPath(new URL('./sandbox_cua.py', import.meta.url));

export async function runAdapter(argv, { python = 'python', endpoint } = {}) {
  try {
    const { stdout } = await exec(python, [adapter, ...(endpoint ? ['--endpoint', endpoint] : []), ...argv],
      { timeout: 60000, maxBuffer: 1024 * 1024, windowsHide: true, encoding: 'utf8' });
    const result = JSON.parse(stdout);
    if (result.ok !== true) throw new Error('Adapter returned an unsuccessful response');
    return result;
  } catch (cause) {
    let detail;
    try { detail = JSON.parse(cause.stderr); } catch { /* Non-adapter launch errors retain their cause. */ }
    const error = new Error(detail?.message ?? cause.message, { cause });
    error.category = detail?.category ?? 'adapter_transport_error';
    throw error;
  }
}

// One session owns the daemon while connected. No hidden connections or input retries.
export function createSandbox({ emitImage, python, endpoint, run = argv => runAdapter(argv, { python, endpoint }) } = {}) {
  if (typeof emitImage !== 'function') throw new TypeError('emitImage callback is required');
  let target = null, observation = null, busy = false, sequence = 0;
  const sessionId = randomUUID();
  async function exclusive(task) {
    if (busy) throw new Error('Another Sandbox operation is in progress');
    busy = true;
    try { return await task(); } finally { busy = false; }
  }
  async function capture() {
    observation = null;
    if (!target) throw new Error('Select and connect a returned Sandbox first');
    const directory = await mkdtemp(join(tmpdir(), 'sandbox-cua-'));
    try {
      const shot = await run(['screenshot', join(directory, 'frame.png')]);
      if (shot.stale || shot.session_state !== 'Connected' || !Number.isInteger(shot.width) || !Number.isInteger(shot.height) || shot.width <= 0 || shot.height <= 0)
        throw new Error('No usable connected screenshot was returned');
      await emitImage({ bytes: await readFile(shot.path), mimeType: 'image/png' });
      observation = Object.freeze({ sandbox: target, screenshotId: `${sessionId}:${++sequence}`, width: shot.width, height: shot.height, accessibility: null });
      return observation;
    } finally { await rm(directory, { recursive: true, force: true }); }
  }
  function point(state, x, y) {
    if (!Number.isInteger(x) || !Number.isInteger(y) || x < 0 || y < 0 || x >= state.width || y >= state.height)
      throw new RangeError('Coordinates must be inside the latest full-frame screenshot');
  }
  async function act(state, build) {
    return exclusive(async () => {
      if (!state || !observation || state.screenshotId !== observation.screenshotId || state.sandbox?.id !== target?.id)
        throw new Error('Reobserve and inspect the latest state before input');
      const commands = build(observation);
      observation = null;
      try {
        const status = await run(['status']);
        if (!/^state:\s*Connected\s*$/mi.test(status.status)) throw new Error('Sandbox is not connected');
        for (const command of commands) await run(command);
        return await capture();
      } catch (cause) {
        observation = null;
        throw new Error('Input or refresh outcome is unknown; reobserve before retrying', { cause });
      }
    });
  }
  return Object.freeze({
    doctor: () => exclusive(() => run(['doctor'])),
    list_sandboxes: () => exclusive(() => run(['sandbox-list'])),
    status: () => exclusive(() => run(['status'])),
    start_daemon: () => exclusive(() => run(['daemon-start'])),
    connect: id => exclusive(async () => {
      if (target) throw new Error('Disconnect the selected Sandbox before selecting another');
      const { environments } = await run(['sandbox-list']);
      const candidates = environments.filter(item => item.Id?.toLowerCase() === id?.toLowerCase());
      if (candidates.length !== 1) throw new Error('Expected exactly one returned Sandbox ID');
      observation = null;
      await run(['sandbox-connect', '--id', candidates[0].Id]);
      await run(['wait-connected', '--stable-seconds', '8']);
      target = Object.freeze({ id: candidates[0].Id });
      return target;
    }),
    get_state: () => exclusive(capture),
    click: ({ state, x, y, mouse_button = 'left', click_count = 1 }) => act(state, s => {
      point(s, x, y);
      return [['click', '--x', String(x), '--y', String(y), '--button', mouse_button, '--count', String(click_count)]];
    }),
    drag: ({ state, from_x, from_y, to_x, to_y }) => act(state, s => {
      point(s, from_x, from_y); point(s, to_x, to_y);
      return [['drag', '--from-x', String(from_x), '--from-y', String(from_y), '--to-x', String(to_x), '--to-y', String(to_y)]];
    }),
    scroll: ({ state, x, y, delta, horizontal = false }) => act(state, s => {
      point(s, x, y);
      if (!Number.isInteger(delta) || delta < -32768 || delta > 32767) throw new RangeError('Invalid wheel delta');
      return [['scroll', '--x', String(x), '--y', String(y), '--delta', String(delta), ...(horizontal ? ['--horizontal'] : [])]];
    }),
    press_key: ({ state, key }) => act(state, () => {
      const keys = key.split('+').map(s => s.trim());
      return [keys.length === 1 ? ['key', '--name', keys[0]] : ['hotkey', '--keys', keys.join(',')]];
    }),
    type_text: ({ state, text }) => act(state, () => {
      if (typeof text !== 'string' || !text || /[\x00-\x1f\x7f]/.test(text)) throw new TypeError('Use literal text; use press_key for control keys');
      return [['type', '--text', text]];
    }),
    disconnect: () => exclusive(async () => {
      observation = null;
      await run(['disconnect']);
      target = null;
    }),
  });
}
