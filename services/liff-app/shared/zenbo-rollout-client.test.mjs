import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const {create}=createRequire(import.meta.url)('./zenbo-rollout-client.js');
const session={session_id:'synthetic-id',robot_slug:'robot-a',state:'LOCKED',revision:0,
  dry_run:true,physical_authorized:false,mqtt_publish_attempted:false,
  events:[{state:'LOCKED',actor:'synthetic',at_ms:1000}]};
const wrap=row=>({session:row,dry_run:true,physical_authorized:false,mqtt_publish_attempted:false});
const calls=[];let result=wrap(session);
const client=create({apiBase:'/liff-api',fetch:async(url,options)=>{
  calls.push({url,options});return {ok:true,json:async()=>result};
}});
await client.run('active');assert.equal(calls.length,0);
client.select('robot-a');await client.run('active');assert.equal(client.state().session.revision,0);
assert.equal(calls[0].url,'/liff-api/api/v1/robots/robot-a/rollout-drills/active');
assert.equal(calls[0].options.method,'GET');
result={...session,state:'SIMULATED_L1',revision:1};await client.run('advance');
assert.deepEqual(JSON.parse(calls[1].options.body),{revision:0});
result={...session,state:'ROLLED_BACK',revision:2};await client.run('rollback');
assert.deepEqual(JSON.parse(calls[2].options.body),{revision:1});
assert.ok(calls[2].url.endsWith('/synthetic-id/rollback'));
await client.run('advance');assert.equal(calls.length,3);
let failedCalls=0;let mode='lost';
const lost=create({apiBase:'',fetch:async()=>{
  failedCalls++;if(mode==='lost')throw new Error('synthetic disconnect');
  return {ok:true,json:async()=>wrap(session)};
}});
lost.select('robot-a');await lost.run('start',{permitId:'permit'});
assert.equal(lost.state().uncertain,true);await lost.run('start',{permitId:'permit'});
assert.equal(failedCalls,1,'no automatic or manual retry until readback');
mode='read';await lost.run('active');assert.equal(lost.state().uncertain,false);
assert.equal(lost.state().session.session_id,'synthetic-id');
const bad=create({apiBase:'',fetch:async()=>({ok:true,json:async()=>wrap({...session,physical_authorized:true})})});
bad.select('robot-a');await bad.run('active');assert.equal(bad.state().uncertain,true);
assert.equal(bad.state().session,null);
let release;let racingCalls=0;
const race=create({apiBase:'',fetch:async()=>{racingCalls++;return new Promise(resolve=>{release=resolve;});}});
race.select('robot-a');const pending=race.run('active');await race.run('active');
assert.equal(racingCalls,1);race.select('robot-b');release({ok:true,json:async()=>wrap(session)});await pending;
assert.equal(race.state().session,null);assert.equal(race.state().robot,'robot-b');
const conflict=create({apiBase:'',fetch:async()=>({ok:false,json:async()=>({detail:{code:'REVISION_CONFLICT'}})})});
conflict.select('robot-a');await conflict.run('start',{permitId:'permit'});assert.match(conflict.state().message,/REVISION_CONFLICT/);
assert.equal(conflict.state().uncertain,true);
assert.ok(calls.every(call=>call.url.includes('/rollout-drills/') && !call.url.includes('relative-motion')));
console.log('Rollout client tests passed: revision binding, recovery, no retry, terminal and target gates.');

const stalled=create({apiBase:'',timeoutMs:1,fetch:async(url,options)=>new Promise((resolve,reject)=>{
  options.signal.addEventListener('abort',()=>reject(new Error('synthetic timeout')));
})});
stalled.select('robot-a');await stalled.run('start',{permitId:'permit'});
assert.equal(stalled.state().busy,false);assert.equal(stalled.state().uncertain,true);
