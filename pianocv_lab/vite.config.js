import {fileURLToPath} from 'node:url';
import {defineConfig} from 'vite';

const headers = {
  'Cross-Origin-Opener-Policy': 'same-origin',
  'Cross-Origin-Embedder-Policy': 'require-corp',
};

export default defineConfig({
  // Import the two modules we use so Vite does not also emit pianoCV's WebGPU worker.
  resolve: {dedupe: ['onnxruntime-web'], alias: {
    '#pianocv-session': fileURLToPath(new URL('keynetsession.ts', import.meta.resolve('pianocv'))),
    '#pianocv-core': fileURLToPath(new URL('keycore.ts', import.meta.resolve('pianocv'))),
  }},
  optimizeDeps: {include: ['onnxruntime-web/wasm']},
  worker: {format: 'es'},
  server: {headers, fs: {allow: [fileURLToPath(new URL('../', import.meta.url))]}},
  preview: {headers},
});
