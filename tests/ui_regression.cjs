const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function harness() {
  const elements = new Map(), timers = new Map();
  let timerId = 0;
  const ctx = {
    document: {addEventListener() {}, getElementById(id) {return elements.get(id) || null;}},
    window: {addEventListener() {}}, console, AbortController, alert() {},
    setTimeout(fn) {timers.set(++timerId, fn); return timerId;},
    clearTimeout(id) {timers.delete(id);},
  };
  vm.createContext(ctx);
  vm.runInContext(fs.readFileSync('src/api/static/api-response.js', 'utf8'), ctx);
  vm.runInContext(fs.readFileSync('src/api/static/fastcheck.js', 'utf8'), ctx);
  for (const id of ['line-1','over-odds-1','under-odds-1','ev-1','over-pct-1','under-pct-1']) {
    elements.set(id, {value:'', textContent:'', className:'', title:'', classList:{add(){},remove(){}}});
  }
  return {ctx, elements, timers};
}

test('valid edit invalidates the old response before the new debounce starts', async () => {
  const {ctx,elements} = harness();
  let resolve;
  ctx.fetch = () => new Promise(r => {resolve = r;});
  let renders = 0;
  ctx.applyPredictionToRow = () => {renders++;};
  elements.get('line-1').value = '20.5';
  const request = ctx.calculateSinglePlayer(1,20.5,1.91,1.91,'ATL');
  elements.get('line-1').value = '30.5';
  ctx.onPlayerInputChange(1,'ATL');
  resolve({ok:true,text:async()=>JSON.stringify({line_probabilities:{line:20.5}})});
  await request;
  assert.equal(renders,0);
});

test('clearing line cancels timers and aborted rosters never render', async () => {
  const {ctx,elements,timers} = harness();
  elements.get('line-1').value = '20.5';ctx.onPlayerInputChange(1,'ATL');
  elements.get('line-1').value = '';ctx.onPlayerInputChange(1,'ATL');
  assert.equal(timers.size,0);
  let renders = 0;ctx.renderRoster = () => {renders++;};
  const ctrl = new AbortController();ctrl.abort();
  await ctx.loadBothRosters('CLE','ATL',ctrl.signal);
  assert.equal(renders,0);
});

test('fallback EV accounts for refunded push', () => {
  const {ctx,elements} = harness();
  ctx.applyPredictionToRow(1,{expected_value:20,line_probabilities:{q_over:.45,q_under:.35,q_push:.2}},2,2);
  assert.match(elements.get('over-pct-1').title,/EV: 10\.0%/);
});

test('prediction responses handle plain-text and HTML server errors', async () => {
  const {ctx} = harness();
  for (const body of ['Internal Server Error', '<html>Bad Gateway</html>']) {
    await assert.rejects(ctx.readApiResponse({ok:false,status:500,text:async()=>body}), /HTTP 500/);
  }
});

test('prediction responses preserve JSON validation errors and reject invalid successes', async () => {
  const {ctx} = harness();
  await assert.rejects(ctx.readApiResponse({ok:false,status:422,
    text:async()=>JSON.stringify({detail:[{msg:'Line must be finite'}]})}), /Line must be finite/);
  await assert.rejects(ctx.readApiResponse({ok:false,status:500,
    text:async()=>JSON.stringify({detail:'Internal server error'})}), /Internal server error/);
  await assert.rejects(ctx.readApiResponse({ok:true,status:200,text:async()=>''}), /invalid JSON/);
  const data = await ctx.readApiResponse({ok:true,status:200,text:async()=>'{"expected_value":25}'});
  assert.equal(data.expected_value,25);
});

test('OCR fills all 13 rows and calculates one batch without individual requests', async () => {
  const {ctx,elements} = harness();
  const ids = [202331,1628369,1628401,1628976,1630202,1630217,1630573,1630591,1630532,1629674,1641775,1641783,1641710];
  const lines = [18.5,26.5,12.5,10.5,13.5,18.5,7.5,8.5,21.5,9.5,4.5,11.5,13.5];
  ctx.items = ids.map((id,i)=>({player_id:id,line:lines[i],odds_over:1.67,odds_under:1.93}));
  for (const id of ids) {
    for (const name of ['line','over-odds','under-odds','ev','over-pct','under-pct']) {
      let value = '';
      elements.set(`${name}-${id}`,{get value(){return value;},set value(v){value=String(v);},
        textContent:'',title:'',className:'',classList:{add(){},remove(){}}});
    }
  }
  elements.set('team1-select',{value:'BOS'});
  elements.set('team2-select',{value:'ORL'});
  ctx.document.querySelectorAll = () => ids.map((_,i)=>({dataset:{index:String(i)}}));
  vm.runInContext('currentOcrData={items};team1Roster=items.slice(0,3);team2Roster=items.slice(3)',ctx);
  const calls = [];
  ctx.fetch = async (url,opts) => {
    calls.push(url);
    const requests = JSON.parse(opts.body);
    assert.equal(requests.length,13);
    assert.deepEqual(requests.map(r=>r.line),lines);
    return {ok:true,text:async()=>JSON.stringify(requests.map(r=>({player_id:r.player_id,
      expected_value:20,q_over:55,q_under:45,q_push:0,error:null})))};
  };
  await ctx.applyOcrToFastcheck();
  assert.deepEqual(calls,['/api/fastcheck/predict-batch']);
  for(const id of ids) {
    assert.equal(elements.get(`ev-${id}`).textContent,'20.0');
    assert.equal(elements.get(`over-pct-${id}`).textContent,'55%');
    assert.equal(elements.get(`under-pct-${id}`).textContent,'45%');
  }
});

test('batch without an opponent sends null and cancels pending single predictions', async () => {
  const {ctx,elements,timers} = harness();
  elements.set('team1-select',{value:'BOS'});
  elements.set('team2-select',{value:''});
  elements.get('line-1').value='20.5';
  vm.runInContext('team1Roster=[{player_id:1}]',ctx);
  ctx.onPlayerInputChange(1,'');
  assert.equal(timers.size,1);
  ctx.fetch=async(url,opts)=>{
    assert.equal(JSON.parse(opts.body)[0].opponent_override,null);
    return {ok:true,text:async()=>JSON.stringify([{player_id:1,error:'Player has insufficient history'}])};
  };
  await ctx.calculateAll();
  assert.equal(timers.size,0);
  assert.equal(elements.get('ev-1').title,'Player has insufficient history');
});

test('batch HTTP failures retain the real error on every output', async () => {
  const {ctx,elements} = harness();
  elements.set('team1-select',{value:'BOS'});
  elements.set('team2-select',{value:'ORL'});
  elements.get('line-1').value='20.5';
  vm.runInContext('team1Roster=[{player_id:1}]',ctx);
  ctx.fetch=async()=>({ok:false,status:422,text:async()=>JSON.stringify({detail:[{msg:'Invalid opponent'}]})});
  await ctx.calculateAll();
  for(const field of ['ev','over-pct','under-pct'])assert.equal(elements.get(`${field}-1`).title,'Invalid opponent');
});
