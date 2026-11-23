import {createHash, randomUUID} from 'node:crypto';
import {mkdir, readFile, rename, rm, writeFile} from 'node:fs/promises';

const directory = new URL(process.argv[2] || '../public/', import.meta.url);
const target = new URL('keynet.onnx', directory);
const expected = '6ad778f91457ccb71d630ff32c180b43d8d29b4bd9bc1ff9186d762cd95c9c29';
const sources = [
  'https://matheusfillipe.github.io/pianoCV/keynet.onnx',
  'https://huggingface.co/mattf/pianoCV/resolve/main/keynet.onnx',
];
const digest = data => createHash('sha256').update(data).digest('hex');

async function prepareModel() {
  const installed = await readFile(target).catch(error => {
    if (error.code === 'ENOENT') return null;
    throw error;
  });
  if (installed && digest(installed) === expected) return;
  await mkdir(directory, {recursive: true});
  const errors = [];
  for (const source of sources) {
    const temporary = new URL(`keynet-${randomUUID()}.part`, directory);
    try {
      const response = await fetch(source, {signal: AbortSignal.timeout(30000)});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = Buffer.from(await response.arrayBuffer());
      if (digest(data) !== expected) throw new Error('模型 SHA-256 与锁定版本不一致');
      await writeFile(temporary, data);
      await rename(temporary, target);
      console.log('已下载并校验 pianoCV KeyNet 模型。');
      return;
    } catch (error) {
      errors.push(`${source} · ${error.message}`);
    } finally {
      await rm(temporary, {force: true});
    }
  }
  throw new Error(`无法取得锁定的 KeyNet 模型。\n${errors.join('\n')}`);
}

await prepareModel();
