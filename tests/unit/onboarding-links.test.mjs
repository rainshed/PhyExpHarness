import test from 'node:test';
import assert from 'node:assert/strict';
import {entryCampaign} from '../../packages/meta-workbench-studio/client/entry-link.mjs';

test('workbench entry links accept only navigation and an exact activity identity',()=>{
 assert.equal(entryCampaign('#phyexp'),'');
 assert.equal(entryCampaign('#phyexp/campaign_ab-12'),'campaign_ab-12');
 for(const value of ['','#other','#phyexp/../escape','#phyexp/x/start','#phyexp/x?start=1','#phyexp/%3Cscript%3E'])assert.equal(entryCampaign(value),null);
});
