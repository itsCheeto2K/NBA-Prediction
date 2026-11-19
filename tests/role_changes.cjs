const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
function harness(){
  const element=()=>({textContent:'',className:'',style:{},children:[],appendChild(child){this.children.push(child);},replaceChildren(){this.children=[];}});
  const elements=new Map(['role-context-card','role-context-summary','role-context-volume','role-context-notice','role-context-teammates'].map(id=>[id,element()]));
  const ctx={document:{addEventListener(){},getElementById:id=>elements.get(id)||null,createElement:element}};
  vm.createContext(ctx);vm.runInContext(fs.readFileSync('src/api/static/app.js','utf8'),ctx);
  return {ctx,elements};
}
test('role summary distinguishes confirmed Out from uncertain and shows actual FGA',()=>{
  const {ctx,elements}=harness();
  ctx.renderRoleContext({status:'available',out_count:1,uncertain_count:2,missing:{min:36,fga:19},missing_fga_share:.19,teammates:[]});
  assert.equal(elements.get('role-context-summary').textContent,'1 Reported Out · 2 Uncertain');
  assert.match(elements.get('role-context-volume').textContent,/36.0 MIN.*19.0 FGA.*19.0%/);
});
test('historical comparisons retain zeros and display sample support',()=>{
  const {ctx,elements}=harness();
  ctx.renderRoleContext({status:'available',out_count:1,uncertain_count:0,missing:{min:30,fga:10},teammates:[{
    player_name:'<script>untrusted</script>',status:'out',profile:{min:30,fga:10,fta:0,games:10},
    comparison:{with_games:5,without_games:2,with:{min:20,fga:8,pts:0},without:{min:25,fga:10,pts:5},delta:{min:5,fga:2,pts:5},supported:false}}]});
  const card=elements.get('role-context-teammates').children[0];
  assert.equal(card.children[0].children[0].textContent,'<script>untrusted</script>');
  assert.match(card.children[1].textContent,/0.0 FTA/);
  assert.equal(card.children[2].children[9].textContent,'0.0');
  assert.match(card.children[3].textContent,/\+2.0 FGA/);
  assert.equal(card.children[4].textContent,'Small Sample');
});
test('missing injury evidence displays unknown rather than zero opportunity',()=>{
  const {ctx,elements}=harness();
  ctx.renderRoleContext({status:'unavailable',reason:'Injury Report Unavailable Or Stale'});
  assert.match(elements.get('role-context-summary').textContent,/Stale/);
  assert.equal(elements.get('role-context-volume').textContent,'');
  assert.equal(elements.get('role-context-teammates').children.length,0);
});
test('switching players or a failed prediction hides the old role context',()=>{
  const {ctx,elements}=harness();
  ctx.renderRoleContext({status:'available',out_count:0,uncertain_count:0,missing:{min:0,fga:0},teammates:[]});
  ctx.resetPredictionOutputs();
  assert.equal(elements.get('role-context-card').style.display,'none');
});
