const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function harness() {
  class Element {
    constructor(){this.listeners={};this.children=[];this.value='';this.attrs={};this.open=false;}
    addEventListener(name,fn){this.listeners[name]=fn;}
    setAttribute(name,value){this.attrs[name]=value;}
    appendChild(child){this.children.push(child);}
    replaceChildren(){this.children=[];}
    focus(){this.focused=true;}
    click(){this.listeners.click?.({target:this});}
    showModal(){this.open=true;}
    close(){this.open=false;this.listeners.close?.();}
    getBoundingClientRect(){return {left:20,right:780,top:80,bottom:600};}
    querySelector(selector){return this.parts?.[selector] || (selector==='button'?this.children[0]:null);}
  }
  const trigger=new Element(),input=new Element(),results=new Element(),status=new Element(),close=new Element();
  const dialog=new Element();dialog.parts={'input':input,'.player-search-results':results,'.player-search-status':status,'.player-search-close':close};
  const timers=new Map();let next=0;
  const ctx={AbortController,console,
    document:{addEventListener(name,fn){this.ready=fn;},getElementById(){return trigger;},
      body:new Element(),createElement:tag=>tag==='dialog'?dialog:new Element()},
    window:{location:{assign(url){ctx.destination=url;}}},
    setTimeout(fn){timers.set(++next,fn);return next;},clearTimeout(id){timers.delete(id);},
    readApiResponse:async r=>r.json()};
  vm.createContext(ctx);
  vm.runInContext(fs.readFileSync('src/api/static/player-search.js','utf8'),ctx);
  ctx.suggestions=Array.from({length:10},(_,i)=>({player_id:i===0?2544:201938+i,
    full_name:i===1?'Stephen Curry':`Player ${i}`,membership_verified:true}));
  ctx.fetch=async()=>({json:async()=>ctx.suggestions});
  ctx.document.ready();
  return {ctx,trigger,input,results,status,dialog,timers,close};
}

test('empty search opens ten verified suggestions and selection updates Player',async()=>{
  const h=harness();let selected;
  h.ctx.window.selectPlayer=(id,name)=>{selected={id,name};};
  h.trigger.click();
  await [...h.timers.values()].at(-1)();
  assert.equal(h.dialog.open,true);
  assert.equal(h.input.focused,true);
  assert.equal(h.results.children.length,10);
  assert.equal(new Set(h.results.children.map(x=>x.textContent)).size,10);
  h.results.children[1].click();
  assert.equal(selected.name,'Stephen Curry');
  assert.equal(h.dialog.open,false);
  assert.equal(h.trigger.attrs['aria-expanded'],'false');
});

test('partial-name search returns multiple matches and clearing defeats stale responses',async()=>{
  const h=harness();h.trigger.click();
  let resolve;
  h.ctx.fetch=url=>{
    if (url.includes('query=&')) return Promise.resolve({json:async()=>h.ctx.suggestions});
    assert.match(url,/query=Cur/);assert.match(url,/active_only=true/);
    return new Promise(r=>{resolve=r;});
  };
  h.input.value='Cur';h.input.listeners.input();
  const pending=[...h.timers.values()][0]();
  resolve({json:async()=>[{player_id:201939,full_name:'Stephen Curry',membership_verified:true},{player_id:203552,full_name:'Seth Curry',membership_verified:true}]});
  await pending;
  assert.deepEqual(h.results.children.map(x=>x.textContent),['Stephen Curry','Seth Curry']);
  h.input.value='Cur';h.input.listeners.input();
  const late=[...h.timers.values()].at(-1)();
  h.input.value='';h.input.listeners.input();
  await [...h.timers.values()].at(-1)();
  resolve({json:async()=>[{player_id:1,full_name:'Old result'}]});
  await late;
  assert.equal(h.results.children.length,10);
  assert.ok(!h.results.children.some(x=>x.textContent==='Old result'));
});

test('FastCheck selection navigates to Player and outside click closes dialog',async()=>{
  const h=harness();h.trigger.click();await [...h.timers.values()].at(-1)();h.results.children[0].click();
  assert.match(h.ctx.destination,/player_id=2544/);
  h.trigger.click();
  h.dialog.listeners.click({target:h.dialog,clientX:0,clientY:0});
  assert.equal(h.dialog.open,false);
  assert.equal(h.trigger.focused,true);
});

test('search never offers unverified players and has no hardcoded fallback on roster failure',async()=>{
  const h=harness();
  h.ctx.fetch=async()=>({json:async()=>[{player_id:1,full_name:'Former player',is_active:true}]});
  h.trigger.click();await [...h.timers.values()].at(-1)();
  assert.equal(h.results.children.length,0);
  h.ctx.fetch=async()=>{throw new Error('Roster unavailable. Sync required.');};
  h.input.listeners.input();await [...h.timers.values()].at(-1)();
  assert.equal(h.results.children.length,0);
  assert.match(h.status.textContent,/Sync required/);
});
