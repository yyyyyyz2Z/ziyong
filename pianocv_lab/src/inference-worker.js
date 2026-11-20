import * as ort from 'onnxruntime-web/wasm';
import wasm from 'onnxruntime-web/ort-wasm-simd-threaded.wasm?url';
import mjs from 'onnxruntime-web/ort-wasm-simd-threaded.mjs?url';

let session;

self.onmessage = async ({data: {id, type, url, input, width, height}}) => {
  try {
    if (type === 'initialize') {
      ort.env.wasm.numThreads = 1;
      ort.env.wasm.wasmPaths = {wasm: new URL(wasm, self.location.href).href, mjs: new URL(mjs, self.location.href).href};
      session = await ort.InferenceSession.create(url, {executionProviders: ['wasm'], graphOptimizationLevel: 'all'});
      self.postMessage({id, result: true});
      return;
    }
    const tensor = new ort.Tensor('float32', input, [1, 3, height, width]);
    const outputs = await session.run({[session.inputNames[0]]: tensor}, ['heatmaps', 'presence']);
    const heat = outputs.heatmaps?.data;
    const presence = outputs.presence?.data;
    if (!(heat instanceof Float32Array) || !(presence instanceof Float32Array)) {
      throw new Error('Unexpected pianoCV KeyNet model outputs');
    }
    self.postMessage({id, result: {heat, presence: presence[0], offsets: null}}, [heat.buffer]);
  } catch (error) {
    self.postMessage({id, error: String(error)});
  }
};
