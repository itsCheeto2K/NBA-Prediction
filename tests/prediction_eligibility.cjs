const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function harness() {
  const team={textContent:''};
  const ctx={AbortController,console:{error(){}},document:{addEventListener(){},
    getElementById:id=>id==='prediction-status'?team:null},window:{},clearTimeout(){},
    alert(){throw new Error('Eligibility failures should not show prediction alerts');},
    readApiResponse:async response=>response.json()};
  vm.createContext(ctx);
  vm.runInContext(fs.readFileSync('src/api/static/app.js','utf8'),ctx);
  ctx.resetPredictionOutputs=()=>{};
  ctx.updateDashboard=data=>{ctx.updated=data;};
  return {ctx,team};
}

test('retired or unverified deep-link player never reaches prediction API',async()=>{
  const {ctx,team}=harness(),calls=[];
  ctx.fetch=async url=>{calls.push(url);return {json:async()=>[]};};
  await ctx.runPrediction();
  assert.equal(calls.length,1);
  assert.match(calls[0],/active_only=true&player_id=/);
  assert.ok(team.textContent.length>0);
  assert.equal(ctx.updated,undefined);
});

test('verified player reaches prediction API after membership check',async()=>{
  const {ctx}=harness(),calls=[];
  ctx.fetch=async url=>{
    calls.push(url);
    return {json:async()=>url.startsWith('/api/players')?
      [{player_id:1628378,membership_verified:true}]:{player_id:1628378,expected_value:20}};
  };
  await ctx.runPrediction();
  assert.equal(calls[1],'/api/predict');
  assert.equal(ctx.updated.expected_value,20);
});

test('unavailable roster blocks inference without falling back to old players',async()=>{
  const {ctx}=harness(),calls=[];
  ctx.fetch=async url=>{calls.push(url);return {json:async()=>{throw new Error('Sync required');}};};
  await ctx.runPrediction();
  assert.equal(calls.length,1);
  assert.equal(ctx.updated,undefined);
});
