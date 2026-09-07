import test from 'node:test';
import assert from 'node:assert/strict';
import { writeFile } from 'node:fs/promises';
import { createSandbox } from '../scripts/sandbox_session.mjs';

const id = '12345678-1234-1234-1234-1234567890ab';
async function fixture() {
  const calls = [], images = [];
  let failure, gate;
  const session = createSandbox({
    emitImage: async image => images.push(image),
    run: async argv => {
      calls.push(argv);
      if (gate) await gate;
      if (argv[0] === failure) throw new Error('injected failure');
      if (argv[0] === 'sandbox-list') return { environments: [{ Id: id }] };
      if (argv[0] === 'status') return { status: 'state: Connected\n' };
      if (argv[0] === 'screenshot') {
        await writeFile(argv[1], Buffer.from('fixture'));
        return { path: argv[1], width: 800, height: 600, session_state: 'Connected', stale: false };
      }
      return { ok: true };
    },
  });
  await session.connect(id);
  return { session, calls, images, fail: value => { failure = value; }, block: value => { gate = value; } };
}

test('one action displays fresh state and consumes the prior observation', async () => {
  const f = await fixture();
  const old = await f.session.get_state();
  const fresh = await f.session.click({ state: old, x: 12, y: 20 });
  assert.equal(f.images.length, 2);
  assert.notEqual(fresh.screenshotId, old.screenshotId);
  await assert.rejects(f.session.click({ state: old, x: 12, y: 20 }), /Reobserve/);
  await assert.rejects(f.session.click({ state: { ...fresh, screenshotId: 'invented' }, x: 12, y: 20 }), /Reobserve/);
  await f.session.click({ state: JSON.parse(JSON.stringify(fresh)), x: 12, y: 20 });
});

test('bounds fail before injection and preserve the usable observation', async () => {
  const f = await fixture();
  const state = await f.session.get_state();
  for (const point of [{ x: -1, y: 2 }, { x: 800, y: 0 }, { x: 0, y: 600 }, { x: 1.5, y: 2 }])
    await assert.rejects(f.session.click({ state, ...point }), /Coordinates/);
  assert.equal(f.calls.filter(c => c[0] === 'click').length, 0);
  await assert.rejects(f.session.click({ state: { ...state, width: 1000 }, x: 900, y: 1 }), /Coordinates/);
  await f.session.click({ state, x: 799, y: 599 });
});

test('refresh failure invalidates input state without repeating action', async () => {
  const f = await fixture();
  const state = await f.session.get_state();
  f.fail('screenshot');
  await assert.rejects(f.session.type_text({ state, text: 'hello' }), /outcome is unknown/);
  await assert.rejects(f.session.type_text({ state, text: 'hello' }), /Reobserve/);
  assert.equal(f.calls.filter(c => c[0] === 'type').length, 1);
  f.fail(null);
  await f.session.get_state();
});

test('input failure is not retried; a fresh observation is required', async () => {
  const f = await fixture();
  const state = await f.session.get_state();
  f.fail('click');
  await assert.rejects(f.session.click({ state, x: 1, y: 1 }), /outcome is unknown/);
  await assert.rejects(f.session.press_key({ state, key: 'Return' }), /Reobserve/);
  assert.equal(f.calls.filter(c => c[0] === 'click').length, 1);
});

test('literal text refuses control characters; keys translate without shell strings', async () => {
  const f = await fixture();
  let state = await f.session.get_state();
  await assert.rejects(f.session.type_text({ state, text: 'hello\n' }), /literal text/);
  state = await f.session.press_key({ state, key: 'Control_L+a' });
  assert.deepEqual(f.calls.find(c => c[0] === 'hotkey'), ['hotkey', '--keys', 'Control_L,a']);
  await f.session.type_text({ state, text: '中文 $() ` literal' });
  assert.deepEqual(f.calls.find(c => c[0] === 'type'), ['type', '--text', '中文 $() ` literal']);
});

test('concurrent operations reject and disconnect invalidates observations', async () => {
  const f = await fixture();
  const state = await f.session.get_state();
  let release;
  f.block(new Promise(resolve => { release = resolve; }));
  const pending = f.session.status();
  await assert.rejects(f.session.get_state(), /in progress/);
  release();
  await pending;
  f.block(null);
  await f.session.disconnect();
  await assert.rejects(f.session.click({ state, x: 1, y: 1 }), /Reobserve/);
  await assert.rejects(f.session.get_state(), /Select and connect/);
});

test('selection requires a returned ID and forbids implicit replacement', async () => {
  const f = await fixture();
  await assert.rejects(f.session.connect(id), /Disconnect/);
  await f.session.disconnect();
  await assert.rejects(f.session.connect('made-up'), /exactly one/);
});
