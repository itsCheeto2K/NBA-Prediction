const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
function harness(){
  const elements=new Map();
  function element(){return {textContent:'',children:[],style:{},replaceChildren(){this.children=[];},appendChild(child){this.children.push(child);}};}
  for(const id of ['season-stats-grid','season-stats-context','season-stats-season'])elements.set(id,element());
  const ctx={AbortController,document:{addEventListener(){},getElementById:id=>elements.get(id)||null,createElement:element},
    readApiResponse:async response=>response.json()};
  vm.createContext(ctx);vm.runInContext(fs.readFileSync('src/api/static/app.js','utf8'),ctx);
  return {ctx,elements};
}
test('season stats render green, yellow, red and neutral without changing predictions',()=>{
  const {ctx,elements}=harness();
  ctx.renderSeasonStats({season:'2026-27',position_raw:'C',position_label:'Centers',games_played:6,
    stats:['above','average','below','unrated'].map((tier,i)=>({key:String(i),label:'PTS',value:i===3?null:10,unit:'per_game',tier,peer_count:6,league_average:9}))});
  const cells=elements.get('season-stats-grid').children;
  assert.equal(cells.length,4);
  assert.match(cells[0].children[1].className,/emerald/);assert.match(cells[1].children[1].className,/amber/);
  assert.match(cells[2].children[1].className,/rose/);assert.match(cells[3].children[1].className,/neutral/);
  assert.match(elements.get('season-stats-context').textContent,/League Comparison/);
});
test('stat labels sit above the colored value and league rank box',()=>{
  const {ctx,elements}=harness();
  ctx.renderSeasonStats({season:'2026-27',position_raw:'G',position_label:'Guards',games_played:10,
    stats:[{label:'PTS',value:24.1,unit:'per_game',tier:'above',peer_count:50,league_average:15,rank:21,rank_out_of:51}]});
  const tile=elements.get('season-stats-grid').children[0];
  assert.equal(tile.children[0].textContent,'PTS');
  assert.equal(tile.children[1].children[0].textContent,'24.1');
  assert.equal(tile.children[1].children[1].textContent,'#21');
  assert.match(tile.title,/League Rank #21\/51/);
});
test('FG and three-point percentages round to nearest integer only for display',()=>{
  const {ctx,elements}=harness();
  const stats=[{label:'FG%',value:49.58,unit:'percent',tier:'average'},
    {label:'3P%',value:38.24,unit:'percent',tier:'average'}];
  ctx.renderSeasonStats({season:'2026-27',games_played:10,stats});
  const cells=elements.get('season-stats-grid').children;
  assert.equal(cells[0].children[1].children[0].textContent,'50.0%');
  assert.equal(cells[1].children[1].children[0].textContent,'38.0%');
  assert.equal(stats[0].value,49.58);
  assert.equal(stats[1].value,38.24);
});
test('extended statistics show value without a rank row and preserve ratios and totals',()=>{
  const {ctx,elements}=harness();
  ctx.renderSeasonStats({season:'2026-27',games_played:10,stats:[
    {label:'AST/TO',value:2.36,unit:'ratio',tier:'descriptive',ranked:false,description:'Total AST / total TOV'},
    {label:'DD',value:4,unit:'total',tier:'descriptive',ranked:false},
    {label:'TS%',value:61.25,unit:'percent',tier:'descriptive',ranked:false},
  ]});
  const cells=elements.get('season-stats-grid').children;
  assert.equal(cells[0].children[1].children.length,1);
  assert.equal(cells[0].children[1].children[0].textContent,'2.36');
  assert.equal(cells[1].children[1].children[0].textContent,'4');
  assert.equal(cells[2].children[1].children[0].textContent,'61.3%');
  assert.equal(cells[0].title,'Total AST / total TOV');
});
test('all 23 season stats fit into a three-row mini grid',()=>{
  const {ctx,elements}=harness();
  ctx.renderSeasonStats({season:'2026-27',games_played:10,stats:Array.from({length:23},()=>({label:'PTS',value:10,unit:'per_game',tier:'average'}))});
  const grid=elements.get('season-stats-grid');
  assert.equal(grid.children.length,23);
  assert.equal(grid.style.gridTemplateColumns,'repeat(8, minmax(36px, 1fr))');
  assert.equal(grid.style.minWidth,'302px');
});
test('switching player prevents late season stats from replacing the new player',async()=>{
  const {ctx,elements}=harness();const resolves=[];
  ctx.fetch=()=>new Promise(resolve=>resolves.push(resolve));
  const old=ctx.fetchSeasonStats(1),current=ctx.fetchSeasonStats(2);
  const result=id=>({json:async()=>({season:'2026-27',position_raw:'C',position_label:String(id),games_played:5+id,stats:[]})});
  resolves[1](result(2));await current;resolves[0](result(1));await old;
  assert.equal(elements.get('season-stats-context').textContent,'League Comparison · 7 GP');
  assert.equal(elements.get('season-stats-grid').children.length,0);
});
