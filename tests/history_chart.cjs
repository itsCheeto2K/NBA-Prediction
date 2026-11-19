const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function harness() {
  const elements = new Map(), charts = [], buttons = [];
  function element() { return {value:'', textContent:'', innerHTML:'', style:{},
    classList:{toggle(){}}, setAttribute(){}, getContext(){return {};}}; }
  for (const id of ['historyChart','history-chart-container','history-chart-scroll','history-chart-empty',
    'hist-table-body','input-line']) elements.set(id,element());
  for(const range of ['last5','recent','last20','last30','season','h2h']) {
    buttons.push({...element(),dataset:{historyRange:range}});
  }
  const ctx = {console,AbortController,
    document:{addEventListener(){},getElementById:id=>elements.get(id)||null,querySelectorAll:()=>buttons},
    window:{addEventListener(){}},
    Chart:class {
      constructor(canvas,config){Object.assign(this,config);charts.push(this);}
      update(){this.updated=true;}
      destroy(){this.destroyed=true;}
    }};
  vm.createContext(ctx);
  vm.runInContext(fs.readFileSync('src/api/static/app.js','utf8'),ctx);
  return {ctx,elements,charts};
}

function games(count,season='2026-27') {
  return Array.from({length:count},(_,i)=>({game_id:String(i).padStart(5,'0'),
    game_date:new Date(Date.UTC(2026,0,i+1)).toISOString(),season,
    opponent_team_abbr:'HOU',home_away:i%2?'away':'home',pts:i,reb:i+1,ast:i+2})).reverse();
}

test('history ranges include last 5/10/20/30, complete season, and H2H',()=>{
  const {ctx}=harness();
  const current=games(82),old=games(82,'2025-26');
  const data={recent:{rows:[...current,...old]},vs_opponent:{rows:current.slice(0,7)},
    coverage:{seasons_available:['2025-26','2026-27']}};
  for(const [range,count] of [['last5',5],['recent',10],['last20',20],['last30',30],['season',82],['h2h',7]]) {
    const rows=ctx.getHistoryRows(data,range);
    assert.equal(rows.length,count);
    if(range==='season')assert.ok(rows.every(row=>row.season==='2026-27'));
  }
  assert.equal(ctx.getHistoryRows({...data,recent:{rows:old}},'season').length,0);
  assert.equal(current.length,82); // Filtering must not mutate cached results.
});

test('chart preserves home/away labels, zero and missing stats, and chronological order',()=>{
  const {ctx,charts,elements}=harness();
  const rows=games(3);rows[0].pts=null;
  ctx.renderHistoryChart(rows,1.5);
  const chart=charts[0];
  assert.deepEqual(Array.from(chart.data.labels),['HOU','@HOU','HOU']);
  assert.deepEqual(Array.from(chart.data.datasets[0].data),[0,1,null]);
  assert.equal(chart.options.scales.y.title.text,'PTS');
  vm.runInContext('selectedStat="reb"',ctx);
  ctx.renderHistoryChart(rows,100.5);
  assert.equal(charts.length,1);
  assert.equal(chart.updated,true);
  assert.equal(chart.options.scales.y.title.text,'REB');
  assert.ok(chart.options.scales.y.suggestedMax>100.5);
  vm.runInContext('selectedStat="ast"',ctx);
  ctx.renderHistoryChart(rows,0);
  assert.equal(chart.options.scales.y.title.text,'AST');
  assert.equal(chart.options.plugins['history-line'].value,0);
  ctx.renderHistoryChart([],null);
  assert.equal(chart.destroyed,true);
  assert.ok(elements.get('history-chart-empty').textContent);
});

test('white reference line follows the numeric Y scale, including line zero',()=>{
  const {ctx,charts}=harness();
  ctx.renderHistoryChart(games(3),1.5);
  const calls=[];
  const draw={save(){},restore(){},beginPath(){},stroke(){},
    moveTo:(...args)=>calls.push(args),lineTo:(...args)=>calls.push(args)};
  const chart={ctx:draw,scales:{y:{getPixelForValue:v=>100-v*10}},
    chartArea:{left:20,right:300,top:0,bottom:100}};
  const plugin=charts[0].plugins[0];
  plugin.afterDatasetsDraw(chart,{}, {value:1.5});
  assert.equal(draw.strokeStyle,'#ffffff');
  assert.deepEqual(calls,[[20,85],[300,85]]);
  calls.length=0;
  plugin.afterDatasetsDraw(chart,{}, {value:0});
  assert.deepEqual(calls,[[20,100],[300,100]]);
  calls.length=0;
  plugin.afterDatasetsDraw(chart,{}, {value:null});
  assert.equal(calls.length,0);
});

test('chart and table share the selected range and update immediately with line input',()=>{
  const {ctx,elements,charts}=harness();
  ctx.data={recent:{rows:games(30)},coverage:{seasons_available:['2026-27']}};
  vm.runInContext('currentHistoryData=data;currentHistoryTab="last5"',ctx);
  elements.get('input-line').value='24.5';
  ctx.renderPlayerHistory();
  assert.equal(charts[0].data.labels.length,5);
  assert.equal((elements.get('hist-table-body').innerHTML.match(/<tr /g)||[]).length,5);
  elements.get('input-line').value='12.5';
  ctx.renderPlayerHistory();
  assert.equal(charts[0].options.plugins['history-line'].value,12.5);
  elements.get('input-line').value='';
  ctx.renderPlayerHistory();
  assert.equal(charts[0].options.plugins['history-line'].value,null);
});

test('historical Over/Under rates count real zero, exclude missing stats, and include pushes in total',()=>{
  const {ctx,elements}=harness();
  for(const side of ['over','under'])for(const field of ['rate','count'])elements.set(`history-hit-${side}-${field}`,{textContent:''});
  ctx.renderHistoricalHitRates([{pts:30},{pts:24},{pts:0},{pts:25},{pts:null},{}],25);
  assert.equal(elements.get('history-hit-over-rate').textContent,'25%');
  assert.equal(elements.get('history-hit-over-count').textContent,'1/4');
  assert.equal(elements.get('history-hit-under-rate').textContent,'50%');
  assert.equal(elements.get('history-hit-under-count').textContent,'2/4');
  ctx.renderHistoricalHitRates([],25);
  assert.equal(elements.get('history-hit-over-rate').textContent,'--%');
  assert.equal(elements.get('history-hit-under-count').textContent,'--/--');
});

test('hit rates update with selected range, stat and line',()=>{
  const {ctx,elements}=harness();
  for(const side of ['over','under'])for(const field of ['rate','count'])elements.set(`history-hit-${side}-${field}`,{textContent:''});
  ctx.data={recent:{rows:games(10)},coverage:{seasons_available:['2026-27']}};
  vm.runInContext('currentHistoryData=data;currentHistoryTab="last5";selectedStat="reb"',ctx);
  elements.get('input-line').value='8.5';
  ctx.renderPlayerHistory();
  assert.equal(elements.get('history-hit-over-count').textContent,'2/5');
  assert.equal(elements.get('history-hit-under-rate').textContent,'60%');
  elements.get('input-line').value='';ctx.renderPlayerHistory();
  assert.equal(elements.get('history-hit-over-count').textContent,'--/--');
});

test('history table renders sixteen ordered columns, team logos and team-first result',()=>{
  const {ctx,elements}=harness();
  ctx.data={recent:{rows:[{game_id:'g',game_date:'2026-11-01',season:'2026-27',
    player_team_id:1610612738,player_team_abbr:'BOS',opponent_team_id:1610612745,opponent_team_abbr:'HOU',home_away:'away',
    result:'L',team_score:100,opponent_score:105,pts:11,ast:5,reb:7,minutes:33.2,
    fg3m:2,fg3_pct:.4,ft_pct:.75,fg_pct:.5,fga:12,fgm:6,fta:8,ftm:6}]}};
  vm.runInContext('currentHistoryData=data',ctx);ctx.renderPlayerHistory();
  const html=elements.get('hist-table-body').innerHTML;
  const cells=[...html.matchAll(/<td\b[^>]*>([\s\S]*?)<\/td>/g)].map(m=>m[1].replace(/<[^>]*>/g,'').trim());
  assert.equal(cells.length,16);
  assert.equal(cells[1],'BOS');assert.equal(cells[2],'@ HOU');assert.equal(cells[3],'L - 100:105');
  assert.deepEqual(cells.slice(4),['11','5','7','33.2','2','40.0%','75.0%','50.0%','12','6','8','6']);
  assert.match(html,/logos\/nba\/1610612738\/global\/L\/logo.svg/);
  assert.match(html,/logos\/nba\/1610612745\/global\/L\/logo.svg/);
});

test('venue filtering happens before Last N and applies to Season and H2H',()=>{
  const {ctx}=harness();
  const rows=games(20),data={recent:{rows},vs_opponent:{rows:rows.slice(0,8)},coverage:{seasons_available:['2026-27']}};
  for(const venue of ['home','away']) {
    const filtered=ctx.getHistoryRows(data,'last5',venue);
    assert.equal(filtered.length,5);
    assert.ok(filtered.every(row=>row.home_away===venue));
    assert.equal(ctx.getHistoryRows(data,'season',venue).length,10);
    assert.equal(ctx.getHistoryRows(data,'h2h',venue).length,4);
  }
  assert.equal(ctx.getHistoryRows(data,'last5','all').length,5);
  assert.equal(ctx.historyVenueForRow({matchup:'BOS @ HOU'}),'away');
  assert.equal(ctx.historyVenueForRow({matchup:'BOS vs. HOU'}),'home');
  assert.equal(ctx.historyVenueForRow({}),null);
});

test('venue change keeps chart, table and hit-rate denominator in sync',()=>{
  const {ctx,elements,charts}=harness();
  for(const side of ['over','under'])for(const field of ['rate','count'])elements.set(`history-hit-${side}-${field}`,{textContent:''});
  ctx.data={recent:{rows:games(10)}};
  vm.runInContext('currentHistoryData=data;currentHistoryTab="last5";currentHistoryVenue="home"',ctx);
  elements.get('input-line').value='4.5';
  ctx.renderPlayerHistory();
  assert.equal(charts[0].data.labels.length,5);
  assert.ok(charts[0].data.labels.every(label=>label==='HOU'));
  assert.equal((elements.get('hist-table-body').innerHTML.match(/<tr /g)||[]).length,5);
  assert.equal(elements.get('history-hit-over-count').textContent,'2/5');
});
