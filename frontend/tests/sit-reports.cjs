// Plan item 2: sit reports are never lost or overwritten. Against fixtures whose fake
// server keeps the real rules (a report only goes up unless it is a correction; a
// write older than the report kept is ignored; END SIT is its own call), with a
// switch for no signal and one for a slow answer:
// - a no-signal SAW ANIMALS waits on the phone, says so after a reload, and a SHOT
//   with signal wins; a glove brush after it says "Still saved: shot"; END SIT ends
//   the sit once, however often it is tapped, and Stands has no Back to sit after;
// - a SHOT tapped while an earlier report is still in the air goes out after it;
// - END SIT with nothing said leaves the stand asking "What happened?" (a correction);
// - Tonight: "Back to sit" for the sit that is on, and "What happened last night?"
//   (a plain report, and "I didn't go" only for a sit never started);
// - keep-screen-on is taken again after the app comes back to the front;
// - sign-out warns about an unsent report and takes it off the phone.
// Run like map-and-stands.cjs (BASE_URL, PW_CHANNEL).
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert=require('node:assert/strict');
(async()=>{
 const channel=process.env.PW_CHANNEL??'msedge',base=process.env.BASE_URL||'http://127.0.0.1:5173';
 const browser=await chromium.launch({headless:true,...(channel?{channel}:{}),args:['--enable-unsafe-swiftshader']});
 const errors=[];
 try {
 const clock=new Intl.DateTimeFormat('en-GB',{timeZone:'Europe/Madrid',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'});
 const nightOf=t=>{const p=Object.fromEntries(clock.formatToParts(new Date(t)).map(x=>[x.type,x.value]));return new Date(Date.UTC(+p.year,+p.month-1,+p.day,+p.hour,+p.minute)-6*3600e3).toISOString().slice(0,10)};
 const tonight=nightOf(Date.now()),last=new Date(Date.parse(tonight+'T00:00:00Z')-864e5).toISOString().slice(0,10);
 const ago=m=>new Date(Date.now()-m*60e3).toISOString();
 const RANK={nothing:0,seen:1,shootable_no_shot:2,shot:3},rank=o=>o in RANK?RANK[o]:-1;
 const stand={id:'s1',name:'Barranco high seat',lat:39.09,lon:-1.36,claimed_tonight:true,claimed_by:'me'};
 const sit=(id,over={})=>({id,stand_id:'s1',stand:stand.name,night:tonight,user_id:'me',outcome:'unreported',started_at:ago(30),ended_at:null,reported_at:null,wind_status:'clean',wind_text:'Wind is right for Barranco high seat.',...over});
 let sits=[],past=[],signal=true,slowNext=false;const writes=[];
 const find=id=>[...sits,...past].find(s=>s.id===id);
 // The server's rules, as routes_stands.update_sit keeps them.
 const patch=(s,b)=>{const at=b.at||new Date().toISOString();
  if(s.reported_at&&at<s.reported_at)return;
  if(b.outcome===s.outcome)return;
  if(b.correct||b.outcome==='cancelled'||rank(b.outcome)>rank(s.outcome)){s.outcome=b.outcome;s.reported_at=at}};
 const page=await browser.newPage({viewport:{width:390,height:844},serviceWorkers:'block',hasTouch:true,isMobile:true});
 // A token whose subject is 'me', so the phone knows whose reports it holds.
 const tok='x.'+Buffer.from(JSON.stringify({sub:'me'})).toString('base64url')+'.y';
 await page.addInitScript(t=>{if(!sessionStorage.getItem('gs_boot')){sessionStorage.setItem('gs_boot','1');localStorage.setItem('gs_token',t)}
  window.__wake={requests:0,releases:0};let vis='visible';
  Object.defineProperty(document,'visibilityState',{get:()=>vis,configurable:true});
  window.__setVis=v=>{vis=v;document.dispatchEvent(new Event('visibilitychange'))};
  Object.defineProperty(navigator,'wakeLock',{configurable:true,value:{request:async()=>{window.__wake.requests++;let gone=false;return{release:async()=>{if(!gone){gone=true;window.__wake.releases++}}}}}})},tok);
 page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/api/**',async route=>{
  const r=route.request(),u=new URL(r.url()),p=u.pathname.replace(/^\/api/,''),m=r.method();
  if(m!=='GET'){
   const body=r.postDataJSON()||{};writes.push({m,p,body});
   if(!signal)return route.abort('internetdisconnected');
   if(slowNext&&m==='PATCH'){slowNext=false;await new Promise(d=>setTimeout(d,2500))}
   const hit=p.match(/^\/sits\/([^/]+)(?:\/(start|end))?$/),s=hit&&find(hit[1]);
   if(!s)return route.fulfill({status:404,json:{detail:'That sit isn’t on the app.'}});
   if(hit[2]==='start'){s.started_at??=body.at||new Date().toISOString()}
   else if(hit[2]==='end'){s.ended_at??=body.at||new Date().toISOString()}
   else patch(s,body);
   return route.fulfill({json:s});
  }
  const live=sits.filter(s=>s.started_at&&!s.ended_at&&s.outcome!=='cancelled');
  const result=p==='/auth/me'?{id:'me',email:'me@x.local',role:'member'}:p==='/stands'?[stand]:p==='/sits'?sits
   :p==='/sits/mine'?{live,to_report:[...past,...sits].filter(s=>s.outcome==='unreported'&&(s.night<tonight||s.ended_at)&&!live.includes(s))}:undefined;
  if(result===undefined)return route.fulfill({status:404,json:{detail:'Not Found'}});
  return route.fulfill({json:result});
 });
 const queue=()=>page.evaluate(()=>localStorage.getItem('gs_sit_queue'));
 const until=async(fn,what)=>{for(let i=0;i<100;i++){if(await fn())return;await page.waitForTimeout(100)}throw new Error('timed out: '+what)};

 // ── a no-signal tap, a reload, SHOT with signal, a glove brush, END SIT twice ──
 sits=[sit('a')];signal=false;
 await page.goto(base+'/sit/a');await page.getByText('Barranco high seat',{exact:true}).waitFor();
 await page.getByRole('button',{name:/^Saw animals/}).click();
 await page.getByText('Saved on phone, no signal').waitFor();
 await page.reload();await page.getByText('Saved on phone, no signal').waitFor();
 signal=true;await page.getByRole('button',{name:'SHOT',exact:true}).click();
 await page.getByText('Saved: shot').waitFor();
 await until(async()=>find('a').outcome==='shot'&&!(await queue()),'shot sent, queue empty');
 await page.getByRole('button',{name:/^Saw animals/}).click();await page.getByText('Still saved: shot').waitFor();
 assert.equal(find('a').outcome,'shot','a lower tap never lowers the report');
 const end=page.getByRole('button',{name:'END SIT'});await end.click();await end.click({force:true,timeout:500}).catch(()=>{});
 await page.waitForURL(/\/stands\?stand=s1/);
 assert.equal(writes.filter(w=>w.p==='/sits/a/end').length,1,'END SIT is sent once');
 await page.getByText('Reported: shot').waitFor();
 assert.ok(find('a').ended_at,'END SIT ended the sit');
 assert.equal(await page.getByRole('button',{name:'Back to sit'}).count(),0,'an ended sit has no Back to sit');
 assert.ok(writes.filter(w=>w.m==='PATCH').every(w=>w.body.at),'every report carries the time of the tap');

 // ── SHOT tapped while an earlier report is still in the air ──
 sits=[sit('b')];writes.length=0;slowNext=true;
 await page.goto(base+'/sit/b');await page.getByText('Barranco high seat',{exact:true}).waitFor();
 await page.getByRole('button',{name:/^Saw animals/}).click();await page.waitForTimeout(300);
 await page.getByRole('button',{name:'SHOT',exact:true}).click();
 await until(async()=>find('b').outcome==='shot'&&!(await queue()),'shot after the slow send');
 assert.deepEqual(writes.filter(w=>w.m==='PATCH').map(w=>w.body.outcome),['seen','shot'],'one sender: nothing wiped, nothing twice');

 // ── keep-screen-on taken again after the app comes back ──
 const w0=await page.evaluate(()=>window.__wake.requests);
 await page.evaluate(()=>{window.__setVis('hidden');window.__setVis('visible')});
 await until(async()=>(await page.evaluate(()=>window.__wake.requests))===w0+1,'wake lock re-taken');

 // ── END SIT with nothing said: the stand asks, and the answer is a correction ──
 sits=[sit('c')];writes.length=0;
 await page.goto(base+'/sit/c');await page.getByText('Barranco high seat',{exact:true}).waitFor();
 await page.getByRole('button',{name:'END SIT'}).click();await page.waitForURL(/\/stands/);
 await until(async()=>(await page.evaluate(()=>window.__wake.releases===window.__wake.requests)),'every wake lock let go');
 const entry=page.locator('#stand-s1');await entry.getByText('Sit over. Nothing reported yet.').waitFor();
 assert.equal(await entry.locator('details.stand-outcome[open]').count(),1,'the question is open');
 await entry.getByRole('button',{name:'Saw nothing',exact:true}).click();await entry.getByText('Reported: saw nothing').waitFor();
 await until(async()=>find('c').outcome==='nothing'&&!(await queue()),'the answer sent');
 assert.deepEqual(writes.filter(w=>w.m==='PATCH').map(w=>[w.body.outcome,w.body.correct]),[['nothing',true]]);

 // ── Tonight, the next morning: Back to sit, and "What happened last night?" ──
 sits=[sit('live')];past=[sit('p1',{night:last,started_at:null,stand:'Charca stand'}),sit('p2',{night:last,started_at:ago(900),ended_at:ago(700),stand:'Encinar tower'})];writes.length=0;
 await page.goto(base+'/');
 await page.getByText('Your sit at Barranco high seat is on.').waitFor();
 await until(async()=>(await page.locator('.sp-ask').count())===2,'two cards');
 assert.equal(await page.getByRole('heading',{name:'What happened last night?'}).count(),2);
 assert.equal(await page.getByRole('button',{name:'I didn’t go'}).count(),1,'only a sit never started offers “I didn’t go”');
 const enc=page.locator('.sp-ask',{hasText:'Encinar tower'});await enc.getByRole('button',{name:'Saw animals'}).click();await enc.getByText('Saved: saw animals.').waitFor();
 const cha=page.locator('.sp-ask',{hasText:'Charca stand'});await cha.getByRole('button',{name:'I didn’t go'}).click();await cha.getByText('Saved: you didn’t go.').waitFor();
 assert.deepEqual(writes.map(w=>[w.p,w.body.outcome,!!w.body.correct]),[['/sits/p2','seen',false],['/sits/p1','cancelled',true]],'a morning answer can only fill in an unreported sit');
 for(const b of await page.locator('.sp-answer, .sp-primary').all())assert.ok((await b.boundingBox()).height>=56,'glove-sized');
 await page.getByRole('link',{name:'Back to sit'}).click();await page.waitForURL(/\/sit\/live$/);

 // ── sign-out warns about an unsent report and takes it off the phone ──
 signal=false;await page.getByRole('button',{name:'SHOT',exact:true}).click();await page.getByText('Saved on phone, no signal').waitFor();
 await page.goto(base+'/settings');const said=[];page.once('dialog',d=>{said.push(d.message());d.accept()});
 await page.locator('#account').getByRole('button',{name:'Sign out'}).click();await page.waitForURL(/\/login/);
 assert.match(said[0]||'',/A sit report hasn’t reached the server yet/);
 assert.deepEqual(await page.evaluate(()=>Object.keys(localStorage).filter(k=>k==='gs_sit_queue'||k.startsWith('gs_cache:/sits'))),[]);

 assert.deepEqual(errors,[]);
 console.log('PASS: no-signal tap waits on the phone through a reload; SHOT wins; a glove brush says what is kept; END SIT once and no Back to sit after; a tap during a slow send goes after it; keep-screen-on taken again and let go; an ended sit asks on its stand (a correction); Tonight offers Back to sit and "What happened last night?" (plain reports, "I didn’t go" only if never started, 56 px); sign-out warns and clears.');
 } finally { await browser.close() }
})().catch(e=>{console.error(e);process.exit(1)});
