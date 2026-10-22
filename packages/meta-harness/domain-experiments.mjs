import {registerDomain} from './domain-tools.mjs';
export const name='meta-experiments';
export const inject=['tools','metaControl'];
export function apply(ctx,config){registerDomain(ctx,config,'experiments');}
