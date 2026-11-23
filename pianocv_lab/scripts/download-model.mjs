import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';

const executable = fileURLToPath(new URL('../../frontend/scripts/download-pianocv-model.mjs', import.meta.url));
const directory = new URL('../public/', import.meta.url).href;
const result = spawnSync(process.execPath, [executable, directory], {stdio: 'inherit'});
if (result.error) throw result.error;
process.exitCode = result.status ?? 1;
