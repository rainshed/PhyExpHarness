import test from 'node:test';
import assert from 'node:assert/strict';
import os from 'node:os';
import fs from 'node:fs';
import path from 'node:path';
import {execFileSync} from 'node:child_process';
import {dataDirectory} from '../../scripts/local-paths.mjs';

test('UI and control resolve the same data directory across platform, XDG and explicit overrides',()=>{
 for(const platform of ['darwin','linux'])for(const values of [
  {},{XDG_DATA_HOME:'/tmp/phyexp xdg'}, {XDG_DATA_HOME:'~/phyexp-xdg'},
  {XDG_DATA_HOME:''},{PHYEXP_DATA_DIR:'./relative-data'},
  {PHYEXP_DATA_DIR:'~/phyexp data',XDG_DATA_HOME:'/tmp/unused'}
 ]){
  const env={...process.env,PHYEXP_DATA_DIR:'',XDG_DATA_HOME:'',...values};
  const python=execFileSync('python3',['-B','-c',
   'import sys; sys.platform=sys.argv[1]; from src.control.paths import data_dir; print(data_dir())',platform],{env,encoding:'utf8'}).trim();
  assert.equal(dataDirectory({env,platform}),python,JSON.stringify({platform,values}));
 }
 assert.equal(dataDirectory({env:{XDG_DATA_HOME:'/tmp/custom'},platform:'linux'}),path.join(fs.realpathSync('/tmp'),'custom/PhyExpHarness'));
 assert.equal(dataDirectory({env:{},platform:'darwin'}),path.join(os.homedir(),'Library/Application Support/PhyExpHarness'));
});
