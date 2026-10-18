// Legacy host-only smoke entry; new Trials use the isolated transport.
import {apply as container, callContainer} from '../../execution/adapters/quantum_harbor/container_tool.mjs';
export {name,inject,callContainer} from '../../execution/adapters/quantum_harbor/container_tool.mjs';
export function apply(ctx){return container(ctx,undefined,{command:(command,signal)=>callContainer(process.env.PHYEXP_HARBOR_SOCKET,command,signal)});}
