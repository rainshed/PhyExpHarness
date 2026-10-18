import {fileURLToPath} from 'node:url';
import {resolveContainerPatch as resolve} from '../../execution/adapters/quantum_harbor/profile.mjs';
export {verifyToolReceipt} from '../../execution/adapters/quantum_harbor/profile.mjs';
export function resolveContainerPatch(logs){return resolve(logs,fileURLToPath(new URL('./container_tool.mjs',import.meta.url)));}
