const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function harness() {
  const elements=new Map(),timers=new Map(),calls=[];let next=0;
  for(const [id,value] of [['input-line','24.5'],['input-odds-over','1.91'],['input-odds-under','1.91'],
    ['select-stat','pts'],['select-history-range','recent'],['select-history-venue','all'],['prediction-status',''],['current-player-name','']]) {
    elements.set(id,{value,textContent:'',listeners:{},addEventListener(name,fn){this.listeners[name]=fn;}});
  }
  const ctx={AbortController,console,document:{addEventListener(){},querySelectorAll:()=>[],getElementById:id=>elements.get(id)||null},
    window:{},setTimeout(fn){timers.set(++next,fn);return next;},clearTimeout:id=>timers.delete(id),
    readApiResponse:async response=>response.json()};
  vm.createContext(ctx);
  vm.runInContext(fs.readFileSync('src/api/static/app.js','utf8'),ctx);
  ctx.resetPredictionOutputs=()=>{};ctx.renderPlayerHistory=()=>{};ctx.updateDashboard=data=>{ctx.result=data;};
  ctx.fetch=async(url,options)=>{
    calls.push({url,options});
    return {json:async()=>url.startsWith('/api/players')?[{player_id:1628378,membership_verified:true}]:{expected_value:20}};
  };
  ctx.setupEventListeners();
  async function flush(){const fn=[...timers.values()].at(-1);timers.clear();fn();await new Promise(setImmediate);}
  return {ctx,elements,timers,calls,flush};
}

test('line and both odds inputs automatically submit only the latest values',async()=>{
  const h=harness();
  for(const [id,value] of [['input-line','25.5'],['input-odds-over','1.8'],['input-odds-under','2.1']]) {
    const input=h.elements.get(id);input.value=value;input.listeners.input();
  }
  assert.equal(h.timers.size,1);
  assert.equal(h.calls.length,0);
  await h.flush();
  const predictions=h.calls.filter(x=>x.url==='/api/predict');
  assert.equal(predictions.length,1);
  const payload=JSON.parse(predictions[0].options.body);
  assert.deepEqual([payload.line,payload.odds_over,payload.odds_under],[25.5,1.8,2.1]);
  assert.equal(payload.opponent_override,null);
});

test('clearing line or entering invalid odds cancels pending auto calculation',()=>{
  const h=harness();
  const line=h.elements.get('input-line'),odds=h.elements.get('input-odds-over');
  line.listeners.input();assert.equal(h.timers.size,1);
  line.value='';line.listeners.input();assert.equal(h.timers.size,0);
  line.value='0';line.listeners.input();assert.equal(h.timers.size,1);
  odds.value='1';odds.listeners.input();assert.equal(h.timers.size,0);
  assert.equal(h.calls.length,0);
});

test('dropdown changes market and automatically recalculates',async()=>{
  const h=harness(),select=h.elements.get('select-stat');
  select.value='reb';select.listeners.change();
  assert.equal(h.elements.get('input-line').value,'6.5');
  await h.flush();
  assert.equal(JSON.parse(h.calls.find(x=>x.url==='/api/predict').options.body).stat,'reb');
});

test('editing during an in-flight request prevents its response from rendering',async()=>{
  const h=harness();let resolve;
  h.ctx.fetch=()=>new Promise(r=>{resolve=r;});
  const old=h.ctx.runPrediction();
  const input=h.elements.get('input-line');input.value='30.5';input.listeners.input();
  resolve({json:async()=>[{player_id:1628378,membership_verified:true}]});
  await old;
  assert.equal(h.ctx.result,undefined);
  assert.equal(h.timers.size,1);
});

test('navbar heading displays player name without team',()=>{
  const h=harness();
  h.ctx.updatePlayerHeading('LeBron James','LAL');
  assert.equal(h.elements.get('current-player-name').textContent,'LeBron James');
  h.ctx.updatePlayerHeading('Other player',null);
  assert.equal(h.elements.get('current-player-name').textContent,'Other player');
});

test('compact probability cards render without Push or EV elements and clear stale values',()=>{
  const h=harness();
  for(const id of ['over-line-val','under-line-val','prob-over','prob-under'])h.elements.set(id,{textContent:''});
  h.ctx.renderProbabilityMetrics({line:20,q_over:.45,q_under:.35,q_push:.2});
  assert.equal(h.elements.get('prob-over').textContent,'45.0%');
  assert.equal(h.elements.get('prob-under').textContent,'35.0%');
  h.ctx.renderProbabilityMetrics(null);
  assert.equal(h.elements.get('prob-over').textContent,'--%');
  assert.equal(h.elements.get('under-line-val').textContent,'--');
});

test('history dropdown switches the range without issuing prediction requests',()=>{
  const h=harness(),select=h.elements.get('select-history-range');
  let renders=0;h.ctx.renderPlayerHistory=()=>{renders++;};
  select.value='last5';select.listeners.change();
  assert.equal(vm.runInContext('currentHistoryTab',h.ctx),'last5');
  select.value='h2h';select.listeners.change();
  assert.equal(vm.runInContext('currentHistoryTab',h.ctx),'h2h');
  assert.equal(renders,2);
  assert.equal(h.calls.length,0);
});

test('venue dropdown filters reference history without changing prediction requests',()=>{
  const h=harness(),select=h.elements.get('select-history-venue');
  let renders=0;h.ctx.renderPlayerHistory=()=>{renders++;};
  select.value='away';select.listeners.change();
  assert.equal(vm.runInContext('currentHistoryVenue',h.ctx),'away');
  assert.equal(renders,1);
  assert.equal(h.calls.length,0);
});
