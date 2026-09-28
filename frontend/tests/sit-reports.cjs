// Plan item 2: sit reports are never lost or overwritten. Against fixtures whose fake
// server keeps the real rules (a report only goes up unless it is a correction; a
// write older than the report kept is ignored; END SIT is its own call), with a
// switch for no signal and one for a slow answer:
// - a no-signal SAW ANIMALS waits on the phone, says so after a reload, and a SHOT
//   with signal wins; a glove brush after it says "Still saved: shot"; END SIT ends
//   the sit once, however often it is tapped, and Stands has no Back to sit after;
// - a SHOT tapped while an earlier report is still in the air goes out after it;
// - END SIT with nothing said leaves the stand asking "What happened?" (a correction);
//   "Saved on this phone" only once a send found no signal, never while one is in
//   the air; an END SIT that went later is "Your sit was updated.", not a report;
// - Tonight: "Back to sit" for the sit that is on, and "What happened last night?"
//   (a plain report, and "I didn't go" only for a sit never started);
// - keep-screen-on is taken again after the app comes back to the front;
// - sign-out warns about an unsent report and takes it off the phone;
// - the morning after (a fixed clock): an evening sit nobody ended is over at 06:00,
//   so it is asked about and its stand is free tonight, also from a copy saved
//   before 06:00; a dawn sit is still on (and is "this morning" once over), and
//   another hunter's leaves the evening free. The fake server counts "on" as
//   routes_stands._live does.
// Run like map-and-stands.cjs (BASE_URL, PW_CHANNEL). The same flows against the
// real server: sit-reports-live.cjs.
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert=require('node:assert/strict');
(async()=>{
 const channel=process.env.PW_CHANNEL??'',base=process.env.BASE_URL||'http://127.0.0.1:5173';
 const browser=await chromium.launch({headless:true,...(channel?{channel}:{}),args:['--enable-unsafe-swiftshader']});
 const errors=[];
 try {
 const clock=new Intl.DateTimeFormat('en-GB',{timeZone:'Europe/Madrid',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'});
 const dayFrom=(t,h)=>{const p=Object.fromEntries(clock.formatToParts(new Date(t)).map(x=>[x.type,x.value]));return new Date(Date.UTC(+p.year,+p.month-1,+p.day,+p.hour,+p.minute)-h*3600e3).toISOString().slice(0,10)};
 const nightOf=t=>dayFrom(t,6),before=n=>new Date(Date.parse(n+'T00:00:00Z')-864e5).toISOString().slice(0,10);
 // The fake server's clock, and the page's: fixed for the morning-after checks.
 let fixed=null;const now=()=>fixed??Date.now();
 const tonight=nightOf(Date.now()),last=before(tonight);
 const ago=m=>new Date(Date.now()-m*60e3).toISOString();
 const RANK={nothing:0,seen:1,shootable_no_shot:2,shot:3},rank=o=>o in RANK?RANK[o]:-1;
 let stands=[{id:'s1',name:'Barranco high seat',lat:39.09,lon:-1.36}];
 const sit=(id,over={})=>({id,stand_id:'s1',stand:stands[0].name,night:tonight,user_id:'me',outcome:'unreported',started_at:ago(30),ended_at:null,reported_at:null,wind_status:'clean',wind_text:'Wind is right for Barranco high seat.',...over});
 let sits=[],past=[],signal=true,down=false,slowNext=false;const writes=[];
 const all=()=>[...sits,...past],find=id=>all().find(s=>s.id===id);
 // On now, as routes_stands._live: tonight's for 12 h; after 06:00 only a dawn sit
 // (started from 03:00 that morning) from the night before, for 6 h.
 const isOn=s=>{if(!s.started_at||s.ended_at||s.outcome==='cancelled')return false;
  const t=nightOf(now()),age=now()-Date.parse(s.started_at);
  return s.night===t?age<=12*3600e3:s.night===before(t)&&dayFrom(s.started_at,3)>=t&&age<=6*3600e3};
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
  if(down)return route.abort('internetdisconnected');
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
  // As the server: tonight's reservations hold a stand; /sits is tonight's and any on now.
  const t=nightOf(now()),held=all().filter(s=>s.night===t&&s.outcome!=='cancelled');
  const mine=all().filter(s=>s.user_id==='me'&&s.outcome!=='cancelled');
  const result=p==='/auth/me'?{id:'me',email:'me@x.local',role:'member'}
   :p==='/stands'?stands.map(st=>{const c=held.find(s=>s.stand_id===st.id);return{...st,claimed_tonight:!!c,claimed_by:c?c.user_id:null}})
   :p==='/sits'?all().filter(s=>s.night===t||isOn(s))
   :p==='/sits/mine'?{live:mine.filter(isOn),to_report:mine.filter(s=>!isOn(s)&&s.outcome==='unreported'&&(s.night<t||s.ended_at||s.started_at))}:undefined;
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

 // ── END SIT with no signal and nothing said: the stand asks, and the answer is a correction ──
 sits=[sit('c')];writes.length=0;signal=false;
 await page.goto(base+'/sit/c');await page.getByText('Barranco high seat',{exact:true}).waitFor();
 await page.getByRole('button',{name:'END SIT'}).click();await page.waitForURL(/\/stands/);
 await until(async()=>(await page.evaluate(()=>window.__wake.releases===window.__wake.requests)),'every wake lock let go');
 const entry=page.locator('#stand-s1');await entry.getByText('Sit over. Nothing reported yet.').waitFor();
 await entry.getByText('Saved on this phone. It goes when there’s signal.').waitFor();
 // Signal back: the END goes when Stands opens. It is not a report.
 signal=true;await page.reload();await page.getByText('Your sit was updated.').waitFor();
 await until(async()=>!!find('c').ended_at&&!(await queue()),'END SIT sent');
 assert.equal(await page.getByText(/sit report.*went through/).count(),0,'an END SIT on its own is not called a report');
 await entry.getByText('Sit over. Nothing reported yet.').waitFor();
 assert.equal(await entry.locator('.stand-unsent').count(),0,'nothing left on the phone');
 assert.equal(await entry.locator('details.stand-outcome[open]').count(),1,'the question is open');
 // A slow answer in the air is not "no signal".
 slowNext=true;await entry.getByRole('button',{name:'Saw nothing',exact:true}).click();
 await page.waitForTimeout(1000);assert.equal(await entry.locator('.stand-unsent').count(),0,'no "saved on this phone" while a send is in the air');
 await entry.getByText('Reported: saw nothing').waitFor();
 await until(async()=>find('c').outcome==='nothing'&&!(await queue()),'the answer sent');
 assert.deepEqual(writes.filter(w=>w.m==='PATCH').map(w=>[w.body.outcome,w.body.correct]),[['nothing',true]]);

 // ── Tonight, the next morning: Back to sit, and "What happened last night?" ──
 // Last night's sit ran in the evening (a fixed 20:30, whatever the time now): one that
 // began after dawn is asked about as "this morning" instead.
 sits=[sit('live')];past=[sit('p1',{night:last,started_at:null,stand:'Charca stand'}),sit('p2',{night:last,started_at:last+'T18:30:00Z',ended_at:last+'T20:00:00Z',stand:'Encinar tower'})];writes.length=0;
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

 // ── the morning after: 07:30 on 27 September, on a fixed clock ──
 const madrid=(day,hm)=>Date.parse(`${day}T${hm}:00+02:00`);
 const setClock=async t=>{fixed=t;await page.clock.setFixedTime(t)};
 await page.evaluate(t=>localStorage.setItem('gs_token',t),tok);
 stands=[{id:'s1',name:'Barranco high seat',lat:39.09,lon:-1.36},{id:'s2',name:'Charca stand',lat:39.1,lon:-1.35},{id:'s3',name:'Alba stand',lat:39.08,lon:-1.37}];
 const iso=t=>new Date(t).toISOString();
 sits=[];past=[
  // Sat from 21:00 and walked home without END SIT: the usual case.
  sit('eve',{night:'2026-09-26',stand_id:'s2',stand:'Charca stand',started_at:iso(madrid('2026-09-26','21:00'))}),
  // A dawn sit, reserved and started before 06:00.
  sit('dawn',{night:'2026-09-26',stand_id:'s3',stand:'Alba stand',started_at:iso(madrid('2026-09-27','05:30'))}),
  // Another hunter's dawn sit.
  sit('bob',{night:'2026-09-26',user_id:'bob',started_at:iso(madrid('2026-09-27','05:00'))})];
 // First at 05:50, still last night: the evening sit is on, and the phone saves that.
 await setClock(madrid('2026-09-27','05:50'));await page.goto(base+'/');
 await page.getByText('Your sit at Charca stand is on.').waitFor();
 // 07:30 with no signal at all: the copy saved at 05:50 must not keep it on.
 await setClock(madrid('2026-09-27','07:30'));down=true;await page.reload();
 await page.getByText('Your sit at Alba stand is on.').waitFor();
 await until(async()=>(await page.locator('.sp-ask').count())===1,'the evening sit is asked about, from the saved copy');
 assert.equal(await page.getByText('Your sit at Charca stand is on.').count(),0,'an evening sit nobody ended is over at 06:00');
 // And with signal, the same.
 down=false;await page.reload();await page.getByText('Your sit at Alba stand is on.').waitFor();
 await until(async()=>(await page.locator('.sp-ask').count())===1,'one card');
 assert.equal(await page.getByText('Your sit at Charca stand is on.').count(),0);
 const eve=page.locator('.sp-ask',{hasText:'Charca stand'});
 await eve.getByRole('heading',{name:'What happened last night?'}).waitFor();
 await eve.getByText('You started the sit and didn’t say.').waitFor();
 assert.equal(await eve.getByRole('button',{name:'I didn’t go'}).count(),0,'it was started');
 await page.goto(base+'/stands');
 const st=id=>page.locator('#stand-'+id);
 await st('s2').getByText('Free tonight').waitFor();
 assert.equal(await st('s2').getByRole('button',{name:'Reserve',exact:true}).count(),1,'last night’s sit holds nothing tonight');
 await st('s3').getByText('Your sit is on').waitFor();
 assert.equal(await st('s3').getByRole('button',{name:'Back to sit'}).count(),1,'the dawn sit is on');
 const order=await st('s3').getByRole('button').allInnerTexts();
 assert.ok(order.includes('Reserve for tonight')&&order.indexOf('Back to sit')<order.indexOf('Reserve for tonight'),'the evening is free, and Back to sit comes first: '+order);
 await st('s1').getByText('Another hunter is in it now, from a dawn sit.').waitFor();
 await st('s1').getByText('Free tonight').waitFor();
 assert.equal(await st('s1').getByRole('button',{name:'Reserve',exact:true}).count(),1);
 await page.getByText('Every stand is free tonight.').waitFor();
 await page.locator('.sp-ask',{hasText:'Charca stand'}).waitFor();
 // Six hours on, the dawn sit nobody ended is over too: "this morning".
 await setClock(madrid('2026-09-27','11:31'));await page.goto(base+'/');
 await until(async()=>(await page.locator('.sp-ask').count())===2,'two cards');
 assert.equal(await page.locator('.sp-live').count(),0,'nothing on');
 await page.locator('.sp-ask',{hasText:'Alba stand'}).getByRole('heading',{name:'What happened this morning?'}).waitFor();

 assert.deepEqual(errors,[]);
 console.log('PASS: no-signal tap waits on the phone through a reload; SHOT wins; a glove brush says what is kept; END SIT once and no Back to sit after; a tap during a slow send goes after it; keep-screen-on taken again and let go; an ended sit asks on its stand (a correction); Tonight offers Back to sit and "What happened last night?" (plain reports, "I didn’t go" only if never started, 56 px); sign-out warns and clears; the morning after, an evening sit nobody ended is asked about and frees its stand (also from a saved copy), a dawn sit stays on and leaves the evening free.');
 } finally { await browser.close() }
})().catch(e=>{console.error(e);process.exit(1)});
