// Plan item 2 against the REAL server (sit-reports.cjs runs the same flows on a fake
// one, and could drift from it). For a dev stack only: it logs in as an admin and
// adds two stands named "Sit check ..." with a sit each, which stay in that database.
// - No signal (every write refused, as in a valley): Start sit opens the seat at
//   once; SAW ANIMALS, SHOT and a glove brush wait on the phone; END SIT goes to the
//   stand, which says the report is saved on the phone. Nothing has reached the
//   server. Signal back: start, the shot, then the end go out in that order, and
//   the server keeps shot, started and ended.
// - With signal: Tonight says "Your sit at X is on" with Back to sit while a sit is
//   on, and once it is ended with nothing said asks what happened; one tap reports it.
// Env: BASE_URL (the web app, which passes /api to the server), GS_EMAIL and
// GS_PASSWORD (an admin; default the seed's), PLAYWRIGHT_MODULE, PW_CHANNEL.
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert=require('node:assert/strict');
(async()=>{
 const channel=process.env.PW_CHANNEL??'msedge',base=process.env.BASE_URL||'http://127.0.0.1:5173';
 const email=process.env.GS_EMAIL||'admin@gamesense.local',password=process.env.GS_PASSWORD||'changeme';
 const login=await fetch(base+'/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email,password})});
 assert.equal(login.status,200,`log in as ${email}`);
 const tok=(await login.json()).access_token;
 const call=async(path,method='GET',body)=>{const r=await fetch(base+'/api'+path,{method,headers:{'Content-Type':'application/json',Authorization:'Bearer '+tok},...(body?{body:JSON.stringify(body)}:{})});
  const text=await r.text();assert.ok(r.ok,`${method} ${path}: ${r.status} ${text}`);return text?JSON.parse(text):null};
 const stamp=new Date().toISOString().slice(11,19).replace(/:/g,'');
 const a=await call('/stands','POST',{name:`Sit check ${stamp} A`}),b=await call('/stands','POST',{name:`Sit check ${stamp} B`});
 const sitA=await call('/sits','POST',{stand_id:a.id});
 const serverSit=async id=>(await call('/sits')).find(s=>s.id===id);

 const browser=await chromium.launch({headless:true,...(channel?{channel}:{}),args:['--enable-unsafe-swiftshader']});
 const errors=[];
 try {
 const ctx=await browser.newContext({viewport:{width:390,height:844},serviceWorkers:'block',hasTouch:true,isMobile:true,timezoneId:'Europe/Madrid'});
 await ctx.addInitScript(t=>{if(!sessionStorage.getItem('gs_boot')){sessionStorage.setItem('gs_boot','1');localStorage.setItem('gs_token',t)}},tok);
 const page=await ctx.newPage();page.on('pageerror',e=>errors.push(e.message));
 // No signal: every write is refused before it leaves the phone. Reads still work,
 // so the pages paint; the queue is what is under test.
 let signal=true;const sent=[];
 await page.route('**/api/**',route=>{
  const r=route.request(),m=r.method(),p=new URL(r.url()).pathname.replace(/^\/api/,'');
  if(m==='GET')return route.continue();
  if(!signal)return route.abort('internetdisconnected');
  sent.push(`${m} ${p}`);return route.continue();
 });
 const until=async(fn,what)=>{for(let i=0;i<150;i++){if(await fn())return;await page.waitForTimeout(100)}throw new Error('timed out: '+what)};

 // ── no signal: Start sit, SAW ANIMALS, SHOT, a brush, END SIT ──
 await page.goto(`${base}/stands?stand=${a.id}`);
 const entry=page.locator('#stand-'+a.id);await entry.getByText('Yours tonight').waitFor();
 signal=false;
 const tapped=Date.now();
 await entry.getByRole('button',{name:'Start sit'}).click();
 await page.waitForURL(new RegExp(`/sit/${sitA.id}$`),{timeout:10_000});
 await page.getByText(a.name,{exact:true}).waitFor();
 await page.getByText('Saved on phone, no signal').waitFor();
 await page.getByRole('button',{name:/^Saw animals/}).click();await page.getByText('Saved: saw animals').waitFor();
 await page.getByRole('button',{name:'SHOT',exact:true}).click();await page.getByText('Saved: shot').waitFor();
 await page.getByRole('button',{name:/^Saw animals/}).click();await page.getByText('Still saved: shot').waitFor();
 await page.getByRole('button',{name:'END SIT'}).click();
 await page.waitForURL(new RegExp(`/stands\\?stand=${a.id}`),{timeout:10_000});
 await entry.getByText('Reported: shot').waitFor();
 await entry.getByText('Saved on this phone. It goes when there’s signal.').waitFor();
 assert.equal(await entry.getByRole('button',{name:'Back to sit'}).count(),0,'ended on the phone');
 let got=await serverSit(sitA.id);
 assert.deepEqual([got.outcome,got.started_at,got.ended_at],['unreported',null,null],'nothing reached the server');
 assert.deepEqual(sent,[]);

 // ── signal back: the phone says so, and it all goes, in order ──
 signal=true;const back=Date.now();
 await page.evaluate(()=>window.dispatchEvent(new Event('online')));
 await until(async()=>{got=await serverSit(sitA.id);return !!got.ended_at},'the sit reached the server');
 assert.deepEqual(sent,[`POST /sits/${sitA.id}/start`,`PATCH /sits/${sitA.id}`,`POST /sits/${sitA.id}/end`],'start, report, end, once each');
 assert.equal(got.outcome,'shot','the server keeps the shot');
 const started=Date.parse(got.started_at),ended=Date.parse(got.ended_at);
 assert.ok(started>=tapped-60e3&&started<back,'started when START was tapped, not when signal came back');
 assert.ok(ended>=started&&ended<back,'ended when END SIT was tapped');
 await until(async()=>(await entry.locator('.stand-unsent').count())===0,'"saved on this phone" gone');
 await entry.getByText('Reported: shot').waitFor();
 assert.equal(await page.evaluate(()=>localStorage.getItem('gs_sit_queue')),null,'nothing left on the phone');

 // ── with signal: Back to sit on Tonight, then "What happened?" once it is ended ──
 const sitB=await call('/sits','POST',{stand_id:b.id});
 await call(`/sits/${sitB.id}/start`,'POST',{});
 await page.goto(base+'/');
 const live=page.locator('.sp-live',{hasText:b.name});
 await live.getByText(`Your sit at ${b.name} is on.`).waitFor();
 assert.equal(await live.getByRole('link',{name:'Back to sit'}).getAttribute('href'),`/sit/${sitB.id}`);
 await call(`/sits/${sitB.id}/end`,'POST',{});
 await page.reload();
 const ask=page.locator('.sp-ask',{hasText:b.name});
 await ask.getByText('You ended the sit without saying.').waitFor();
 assert.equal(await page.locator('.sp-live',{hasText:b.name}).count(),0,'an ended sit is not on');
 await ask.getByRole('button',{name:'Saw nothing'}).click();await ask.getByText('Saved: saw nothing.').waitFor();
 assert.equal((await serverSit(sitB.id)).outcome,'nothing');
 await page.reload();await page.waitForTimeout(1500);
 assert.equal(await page.locator('.sp-ask',{hasText:b.name}).count(),0,'answered, so not asked again');

 assert.deepEqual(errors,[]);
 console.log('PASS (real server): with no signal Start sit opens the seat, the taps and END SIT wait on the phone and the stand says so; with signal back the start, the shot and the end go once each, in order, with the times they were tapped; Tonight has Back to sit while a sit is on and asks what happened once it is ended, one tap.');
 } finally { await browser.close() }
})().catch(e=>{console.error(e);process.exit(1)});
