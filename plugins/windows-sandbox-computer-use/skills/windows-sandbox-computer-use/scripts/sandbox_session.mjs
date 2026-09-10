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
  const timeoutIndex = argv.indexOf('--timeout');
  const timeoutSeconds = timeoutIndex >= 0 ? Number(argv[timeoutIndex + 1]) : 0;
  const timeout = Number.isFinite(timeoutSeconds) && timeoutSeconds > 0 ? Math.max(60000, (timeoutSeconds + 40) * 1000) : 60000;
  try {
    const { stdout } = await exec(python, [adapter, ...(endpoint ? ['--endpoint', endpoint] : []), ...argv],
      { timeout, maxBuffer: 1024 * 1024, windowsHide: true, encoding: 'utf8' });
    const result = JSON.parse(stdout);
    if (result.ok !== true) throw new Error('Adapter returned an unsuccessful response');
    return result;
  } catch (cause) {
    let detail;
    try { detail = JSON.parse(cause.stderr); } catch { /* Non-adapter launch errors retain their cause. */ }
    const error = new Error(detail?.message ?? cause.message, { cause });
    error.category = detail?.category ?? 'adapter_transport_error';
    error.result = detail;
    throw error;
  }
}

// One session owns the daemon while connected. No hidden connections or input retries.
export function createSandbox({ emitImage, python, endpoint, run = argv => runAdapter(argv, { python, endpoint }) } = {}) {
  if (emitImage !== undefined && typeof emitImage !== 'function') throw new TypeError('emitImage must be a function');
  let target = null, observation = null, busy = false, sequence = 0;
  let selected = null;
  const sessionId = randomUUID();
  async function exclusive(task) {
    if (busy) throw new Error('Another Sandbox operation is in progress');
    busy = true;
    try { return await task(); } finally { busy = false; }
  }
  async function capture() {
    observation = null;
    if (!emitImage) throw new Error('Visual control requires an emitImage callback');
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
  async function select(id) {
    if (target) throw new Error('Disconnect visual control before selecting a target');
    const { environments } = await run(['sandbox-list']);
    const candidates = id === undefined ? environments : environments.filter(item => item.Id?.toLowerCase() === id?.toLowerCase());
    if (candidates.length !== 1 || typeof candidates[0].Id !== 'string') throw new Error('Expected exactly one returned Sandbox; specify its ID when multiple are running');
    selected = Object.freeze({ id: candidates[0].Id });
    observation = null;
    return selected;
  }
  function selectedId() {
    if (!selected) throw new Error('Select a Sandbox first');
    return selected.id;
  }
  function execArgs(request) {
    const { command, cwd, run_as = 'ExistingLogin', timeout = 30 } = typeof request === 'string' ? { command: request } : request ?? {};
    if (typeof command !== 'string' || !command.trim() || command.includes('\0')) throw new TypeError('command must be non-empty and NUL-free');
    if (!['ExistingLogin', 'System'].includes(run_as)) throw new TypeError('Unsupported run_as');
    if (!Number.isFinite(timeout) || timeout <= 0 || timeout > 300) throw new RangeError('timeout must be between 0 and 300 seconds');
    if (cwd !== undefined && (typeof cwd !== 'string' || !/^[a-z]:\\/i.test(cwd) || cwd.split(/[\\/]/).includes('..') || cwd.includes('\0'))) throw new TypeError('cwd must be an absolute guest drive path without parent traversal');
    return ['sandbox-exec', '--id', selectedId(), '--command', command, '--run-as', run_as, '--timeout', String(timeout), ...(cwd === undefined ? [] : ['--cwd', cwd])];
  }
  return Object.freeze({
    select: id => exclusive(() => select(id)),
    exec: request => exclusive(async () => {
      const args = execArgs(request);
      observation = null;
      return await run(args);
    }),
    exec_many: requests => exclusive(async () => {
      if (!Array.isArray(requests) || requests.length === 0 || requests.length > 32) throw new RangeError('Provide 1 to 32 commands');
      const commands = requests.map(execArgs);
      observation = null;
      const results = [];
      for (const args of commands) {
        try { results.push(await run(args)); }
        catch (cause) {
          const error = new Error(`Command ${results.length + 1} failed; ${results.length} completed; remaining commands were not run`, { cause });
          error.completed = results;
          error.failed_index = results.length;
          error.result = cause.result;
          error.category = cause.category;
          throw error;
        }
      }
      return results;
    }),
    ip: () => exclusive(() => run(['sandbox-ip', '--id', selectedId()])),
    share: ({ host_path, sandbox_path, allow_write = false }) => exclusive(async () => {
      if (typeof host_path !== 'string' || typeof sandbox_path !== 'string' || typeof allow_write !== 'boolean') throw new TypeError('share requires host_path, sandbox_path and a boolean allow_write');
      observation = null;
      return await run(['sandbox-share', '--id', selectedId(), '--host-path', host_path, '--sandbox-path', sandbox_path, ...(allow_write ? ['--allow-write'] : [])]);
    }),
    doctor: () => exclusive(() => run(['doctor'])),
    list_sandboxes: () => exclusive(() => run(['sandbox-list'])),
    status: () => exclusive(() => run(['status'])),
    start_daemon: () => exclusive(() => run(['daemon-start'])),
    connect: id => exclusive(async () => {
      if (target) throw new Error('Disconnect the selected Sandbox before selecting another');
      id ??= selected?.id;
      const { environments } = await run(['sandbox-list']);
      const candidates = environments.filter(item => item.Id?.toLowerCase() === id?.toLowerCase());
      if (candidates.length !== 1) throw new Error('Expected exactly one returned Sandbox ID');
      observation = null;
      await run(['sandbox-connect', '--id', candidates[0].Id]);
      await run(['wait-connected', '--stable-seconds', '8']);
      target = Object.freeze({ id: candidates[0].Id });
      selected = target;
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
