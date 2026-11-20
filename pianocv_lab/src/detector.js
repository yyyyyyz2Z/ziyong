import {createKeyNetSession} from '#pianocv-session';
import {keyOutlines, loadKeycore} from '#pianocv-core';

let modelPromise;

function model() {
  modelPromise ??= makeRunner().catch(error => {
    modelPromise = null;
    throw error;
  });
  return modelPromise;
}

async function makeRunner() {
  const worker = new Worker(new URL('./inference-worker.js', import.meta.url), {type: 'module'});
  const pending = new Map();
  let requestId = 0;
  let failure;
  const fail = error => {
    failure = error;
    worker.terminate();
    modelPromise = null;
    for (const request of pending.values()) {
      clearTimeout(request.timer);
      request.reject(error);
    }
    pending.clear();
  };
  worker.onmessage = ({data: {id, result, error}}) => {
    const request = pending.get(id);
    if (!request) return;
    pending.delete(id);
    clearTimeout(request.timer);
    if (error) request.reject(new Error(error));
    else request.resolve(result);
  };
  worker.onerror = event => fail(new Error(event.message || 'ONNX worker failed to load'));

  function ask(message, transfer = [], timeout = 15000) {
    if (failure) return Promise.reject(failure);
    return new Promise((resolve, reject) => {
      const id = ++requestId;
      const timer = setTimeout(() => fail(new Error('ONNX worker timed out')), timeout);
      pending.set(id, {resolve, reject, timer});
      worker.postMessage({...message, id}, transfer);
    });
  }

  try {
    const url = new URL(`${import.meta.env.BASE_URL}keynet.onnx`, location.href).href;
    await Promise.all([loadKeycore(), ask({type: 'initialize', url}, [], 30000)]);
  } catch (error) {
    fail(error);
    throw error;
  }
  return {backend: 'wasm', run: (input, width, height) => ask({type: 'infer', input, width, height}, [input.buffer])};
}

export async function detectFrame(frame, size, progress) {
  const runner = await model();
  const session = createKeyNetSession(runner);
  let fit = null;
  // The upstream tracker votes over successive observations before locking onto a board.
  // Reuse this captured frame so the exported outline corresponds to the chosen video time.
  for (let attempt = 0; attempt < 16; attempt++) {
    progress(attempt, runner.backend);
    const result = await session.step(frame, size, performance.now());
    if (result?.fit) fit = result.fit;
    if (fit?.lift && attempt >= 8) break;
  }

  const keys = fit ? keyOutlines(fit).filter(key => key.bar.length >= 3 &&
    [...key.bar, ...key.top].every(point => Number.isFinite(point.x) && Number.isFinite(point.y))) : [];
  return {keys, fit, backend: runner.backend};
}
