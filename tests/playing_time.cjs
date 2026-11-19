const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
function harness(){
  const elements=new Map(['playing-time-card','playing-time-minutes','playing-time-interval','playing-time-risks'].map(id=>[id,{textContent:'',style:{}}]));
  const ctx={document:{addEventListener(){},getElementById:id=>elements.get(id)||null}};
  vm.createContext(ctx);vm.runInContext(fs.readFileSync('src/api/static/app.js','utf8'),ctx);
  return {ctx,elements};
}
test('playing time distinguishes prediction, conditional minutes and uncertainty',()=>{
  const {ctx,elements}=harness();
  ctx.renderPlayingTime({expected_minutes:31.2,interval_80:{lower:21.3,upper:37.4},risk_flags:['Variable Rotation']});
  assert.equal(elements.get('playing-time-minutes').textContent,'31.2');
  assert.match(elements.get('playing-time-interval').textContent,/80%.*21.3.*37.4/);
  assert.equal(elements.get('playing-time-risks').textContent,'Variable Rotation');
  const html=fs.readFileSync('src/api/static/index.html','utf8');
  assert.match(html,/If Plays.*Includes OT/);
  assert.doesNotMatch(html,/playing-time-starter|rotation estimate, not verified/);
  assert.doesNotMatch(html,/game-context-score/);
});
test('unavailable model never displays invented minutes',()=>{
  const {ctx,elements}=harness();
  ctx.renderPlayingTime({status:'unavailable',reason:'No prior played games'});
  assert.equal(elements.get('playing-time-minutes').textContent,'—');
  assert.equal(elements.get('playing-time-interval').textContent,'');
  assert.equal(elements.get('playing-time-risks').textContent,'No prior played games');
});
test('new player and failed predictions hide previous playing time',()=>{
  const {ctx,elements}=harness();
  ctx.renderPlayingTime({expected_minutes:30});
  assert.equal(elements.get('playing-time-card').style.display,'block');
  ctx.resetPredictionOutputs();
  assert.equal(elements.get('playing-time-card').style.display,'none');
  ctx.renderPlayingTime(null);
  assert.equal(elements.get('playing-time-card').style.display,'none');
});
