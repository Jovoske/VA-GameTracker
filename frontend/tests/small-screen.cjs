// Glove-sized and small-screen (plan item 16) and the wind hour by hour (feature 22),
// against fixtures: a "More" tab under 380 px so Settings is never off the edge, every
// tap target 44 px or more, back to the photo an alert opened after signing in (and
// Back never shows the sign-in form again), the wind and the week keeping their room
// on Stands so Reserve doesn't move under a thumb, Insights' weather after its
// findings, Hide asking first, one Add person or password change per tap, and the
// week's line and hour strip on Stands and Tonight at 320, 390 and 768 px: letters a
// dusk-readable size, an evening's speeds under it on a tap, a stand that can't be
// judged saying why once, no signal with only last night's week said in words (never
// "Checking the wind…" for ever), an old copy offering only the hours not yet over,
// with its age, and Sit mode opening on the verdict Stands just showed.
// Run like map-and-stands.cjs (BASE_URL, PW_CHANNEL).
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert=require('node:assert/strict');
(async()=>{
 const channel=process.env.PW_CHANNEL??'msedge',base=process.env.BASE_URL||'http://127.0.0.1:5173';
 const browser=await chromium.launch({headless:true,...(channel?{channel}:{}),args:['--enable-unsafe-swiftshader']});
 const errors=[];
 try {
 const tile=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==','base64');
 const iso=(ms)=>new Date(ms).toISOString();
 // The week: 17 to 24 h, tonight and six evenings. Right at 19-21 tonight, Thursday's row
 // right for two hours; the stand's own line from the server says so.
 const tz='Europe/Madrid',today=new Date().toLocaleDateString('en-CA',{timeZone:tz});
 const nights=[0,1,2,3,4,5,6].map(d=>new Date(Date.parse(today+'T12:00:00Z')+d*86400e3).toISOString().slice(0,10));
 const hourAt=(night,h)=>iso(Date.parse(night+'T00:00:00Z')+(h-2)*3600e3);
 const hours=[17,18,19,20,21,22,23,24];
 // The phone's clock for the pages that read the week: four in the afternoon, or half
 // past nine with 19 and 20 h over. The week's line is the hours not yet over, so a
 // real clock would change what it says through the evening.
 const afternoon=Date.parse(hourAt(nights[0],16)),lateEvening=Date.parse(hourAt(nights[0],21))+30*60e3;
 const weekFor=(id,name,right)=>({stand_id:id,stand:name,status:'ok',line:`Right wind for ${name}: tonight 19–21 h, Thu`,right_tonight:'19–21 h',right_days:['Thu'],
  tonight:{status:'clean',text:`Wind N 12 km/h, clean for ${name}.`,at_local:'20:39',now:false},
  evenings:nights.map((n,i)=>({night:n,right:[],right_evening:i===3,hours:hours.map(h=>({hour:h,at:hourAt(n,h),at_local:`${String(h%24).padStart(2,'0')}:00`,status:(i===0&&right.includes(h))||(i===3&&h>=20&&h<=21)?'clean':h===23?'too_light':'scent_carries',wind_dir_deg:h*20%360,wind_speed_kmh:12}))}))});
 const week={evenings:nights.map((n,i)=>({night:n,day:i===0?'Tonight':['Mon','Tue','Wed','Thu','Fri','Sat'][i-1],tonight:i===0,sunset_local:'19:54'})),hours,
  stands:[weekFor('s1','Charca',[19,20,21]),weekFor('s2','Solana',[])],forecast_fetched_at:iso(Date.now()-600e3),forecast_stale:false,sunset_local:'19:54'};
 const stands=[{id:'s1',name:'Charca',lat:39.09,lon:-1.36,claimed_tonight:false,claimed_by:null},{id:'s2',name:'Solana',lat:39.091,lon:-1.361,claimed_tonight:false,claimed_by:null}];
 const species=[{id:'wild_boar',common_name:'Wild boar',huntable:true,hidden:false,is_priority:true,detections:40,big_game:true},{id:'red_deer',common_name:'Red deer',huntable:true,hidden:false,is_priority:true,detections:20,big_game:true},{id:'fox',common_name:'Fox',huntable:false,hidden:false,is_priority:false,detections:4,big_game:false}];
 const plan={verdict:'BEST_ODDS',wind:{status:'clean',text:'Wind N 12 km/h, clean for Charca.',is_advice:true,at_local:'20:39',now:false,stand:'Charca',stand_id:'s1'},
  recommended:{camera:'PL19 Charca',camera_id:'c1',species:'Wild boar',runner_up:null,probability:.7,best_window:{start_hour:21,end_hour:0,start:'21:15',end:'00:15'},nights_present:30,active_nights:40,reason:'Wild boar seen 30 of 40 nights here.',caveat:''},
  conditions:{moon_phase:'waxing',moon_illum:40,darkness_minutes:700,wind_dir_deg:0,wind_speed_kmh:12,sunset_local:'19:54'},alternates:[],nights_of_data:40,generated_at:iso(Date.now())};
 const insights={outlook:[],composition:[{label:'Boar',count:12,visits:12,top_camera:'PL19'}],correlations:[{kind:'time',statement:'Most boar came between 21 and 24 h.',strength:.6,sample:80}]};
 const patterns={nights:40,tested:true,shuffles:200,scopes:[{key:'all',label:'All animals',drivers:[],total_nights:40,sightings:80},{key:'wild_boar',label:'Wild boar',drivers:[],total_nights:40,sightings:60}]};
 let sitsList=[],role='admin',meId='me',users=[{id:'me',email:'admin@x.es',role:'admin',is_you:true},{id:'u2',email:'pedro@x.es',role:'member',is_you:false}];
 const writes=[],delays={},down=new Set(),loginAuth=[],revoked=new Set();let speciesList=species;
 const sleep=ms=>new Promise(r=>setTimeout(r,ms));
 const newPage=async(viewport,{token='small-screen-fixture',at}={})=>{
  const ctx=await browser.newContext({viewport,serviceWorkers:'block',hasTouch:true,isMobile:viewport.width<500,timezoneId:tz,locale:'en-GB'});
  const page=await ctx.newPage();
  if(at)await page.clock.setFixedTime(new Date(at));
  if(token)await page.addInitScript(t=>{if(!sessionStorage.getItem('seeded')){localStorage.setItem('gs_token',t);sessionStorage.setItem('seeded','1')}},token);
  page.on('pageerror',e=>errors.push(e.message));
  await page.route(/ign\.es|catastro\.meh\.es|arcgisonline/,r=>r.fulfill({contentType:'image/png',body:tile}));
  await page.route('**/api/**',async route=>{
   const req=route.request(),u=new URL(req.url()),method=req.method(),path=u.pathname;
   if(delays[path])await sleep(delays[path]);
   // No signal for these.
   if([...down].some(d=>path.startsWith(d)))return route.abort('internetdisconnected');
   if(path==='/api/auth/login'){loginAuth.push(req.headers()['authorization']??null);return route.fulfill({json:{access_token:`fresh-token-${loginAuth.length}`,image_token:null}})}
   // A sign-in that has run out: every call with it is refused until the next sign-in.
   if(revoked.has((req.headers()['authorization']??'').replace('Bearer ','')))return route.fulfill({status:401,json:{detail:'You were signed out. Sign in again.'}});
   if(method!=='GET'){
    writes.push({path,method,body:req.postDataJSON?.()});
    if(path==='/api/users'){await sleep(700);return route.fulfill({json:{id:'u3'}})}
    if(path==='/api/auth/change-password'){await sleep(700);return route.fulfill({json:{access_token:'fresh-token',image_token:'p',note:'Changed. Other phones are signed out.'}})}
    return route.fulfill({json:{}});
   }
   const result=path==='/api/auth/me'?{id:meId,email:'admin@x.es',role}
    :path==='/api/forecast/wind-week'?(u.searchParams.get('stand')?{...week,stands:week.stands.filter(s=>s.stand_id===u.searchParams.get('stand'))}:week)
    :path==='/api/forecast/tonight'?plan:path==='/api/species'?speciesList:path==='/api/alerts'?[]
    :path==='/api/stands'?stands:path==='/api/sits'?sitsList:path==='/api/users'?users:path==='/api/camera-accounts'?[]
    :path==='/api/insights'?insights:path==='/api/insights/patterns'?patterns
    :path==='/api/photos'?{items:[],next_before:null}:path==='/api/photos/filters'?{species:[],cameras:[]}:path==='/api/photos/highlights'?{items:[]}
    :undefined;
   return result===undefined?route.fulfill({status:404,json:{detail:'Not Found'}}):route.fulfill({json:result});
  });
  return page;
 };
 // A Settings section, opened if it isn't already (they remember being open).
 const openSection=async(page,name)=>{const b=page.getByRole('button',{name});await b.waitFor();if(await b.getAttribute('aria-expanded')==='false')await b.click()};
 const small=async(page)=>page.evaluate(()=>[...document.querySelectorAll('button, a[href], summary, input:not([type=hidden]), select, [role=button], [role=switch]')]
  .filter(el=>{const r=el.getBoundingClientRect();return r.width>0&&r.height>0&&!el.classList.contains('skip-link')&&(r.height<44||r.width<44)})
  .map(el=>`${el.tagName} ${(el.getAttribute('aria-label')||el.textContent||'').trim().slice(0,30)} ${Math.round(el.getBoundingClientRect().width)}x${Math.round(el.getBoundingClientRect().height)}`));

 // ── 320 px: five tabs and "More"; nothing off the edge (K-11) ──
 let page=await newPage({width:320,height:640},{at:afternoon});
 await page.goto(base+'/stands');
 await page.locator('.ww-line').first().waitFor();
 const bar=await page.evaluate(()=>{const t=document.querySelector('.tabbar');return{scroll:t.scrollWidth,client:t.clientWidth,shown:[...t.querySelectorAll(':scope > a, .tab-more-btn')].filter(a=>a.getBoundingClientRect().width>0).map(a=>a.textContent.trim())}});
 assert.equal(bar.scroll,bar.client,'nothing behind a sideways scroll');
 assert.deepEqual(bar.shown,['Tonight','Photos','Stands','Map','More']);
 await page.getByRole('button',{name:'More'}).click();
 const menu=page.locator('#more-menu');await menu.waitFor();
 assert.deepEqual(await menu.locator('a').allInnerTexts(),['Cameras','Insights','Settings']);
 for(const h of await menu.locator('a').evaluateAll(as=>as.map(a=>a.getBoundingClientRect().height)))assert.ok(h>=56,`a More row is ${h}px`);
 await page.keyboard.press('Escape');await menu.waitFor({state:'detached'});
 await page.getByRole('button',{name:'More'}).click();await menu.getByRole('link',{name:'Settings'}).click();
 await page.waitForURL(/\/settings$/);await menu.waitFor({state:'detached'});
 assert.match(await page.locator('.tab-more-btn').getAttribute('class'),/active/,'More says you are under it');
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth),320);

 // ── the week at 320: the strip fits, no sideways scroll ──
 await page.goto(base+'/stands');
 const charca=page.locator('#stand-s1');
 assert.equal(await charca.locator('.ww-line').innerText(),'Right wind for Charca: tonight 19–21 h, Thu');
 assert.equal(await charca.locator('.stand-wind-line').innerText(),'Wind is right. Scent goes away from bedding.\nFor 20:39');
 await charca.locator('.stand-wind > summary').click();
 const table=charca.locator('.ww-table');await table.waitFor();
 assert.equal(await table.locator('tbody tr').count(),7);
 assert.deepEqual(await table.locator('thead th').allInnerTexts().then(t=>t.slice(1)),['17','18','19','20','21','22','23','24']);
 assert.equal(await table.locator('tbody tr').first().locator('td[data-status="clean"]').count(),3);
 assert.equal(await table.locator('tbody tr[data-right]').count(),1,'Thursday reads as a right evening');
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth),320,'the strip fits 320 px');
 // Where the wind comes from, readable at dusk, whole in its cell; the evening's name whole too (R6FE-6).
 const cells=await table.evaluate(t=>({from:[...t.querySelectorAll('.ww-from')].map(e=>({px:parseFloat(getComputedStyle(e).fontSize),cut:e.scrollWidth>e.parentElement.clientWidth})),
  days:[...t.querySelectorAll('.ww-day')].map(b=>({text:b.textContent,cut:b.scrollWidth>b.clientWidth}))}));
 assert.ok(cells.from.every(c=>c.px>=12&&!c.cut),`letters ${JSON.stringify(cells.from.slice(0,3))}`);
 assert.deepEqual(cells.days.filter(d=>d.cut),[],'every evening named in full');
 // No hover on a phone: a tap on an evening puts its speeds under it, and a second takes them away.
 assert.equal(await table.locator('tr.ww-speeds').count(),0);
 const right=table.locator('tbody tr[data-right]'),handle=right.locator('.ww-day');
 await right.locator('td').nth(2).click();
 assert.deepEqual(await table.locator('tr.ww-speeds td').allInnerTexts(),['12','12','12','12','12','12','12','12']);
 assert.equal(await table.locator('tbody tr').nth(4).getAttribute('class'),'ww-speeds','right under that evening');
 assert.equal(await handle.getAttribute('aria-expanded'),'true');
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth),320,'the speeds fit 320 px');
 await handle.click();
 assert.equal(await table.locator('tr.ww-speeds').count(),0);
 assert.deepEqual(await small(page),[]);
 await page.context().close();

 // ── Stands: the wind arriving late moves nothing (I-08) ──
 page=await newPage({width:390,height:844},{at:afternoon});
 delays['/api/forecast/wind-week']=2500;
 await page.goto(base+'/stands');
 const reserve=page.locator('#stand-s2').getByRole('button',{name:'Reserve',exact:true});await reserve.waitFor();
 await page.locator('.stand-wind-wait').first().waitFor();
 const before=(await reserve.boundingBox()).y;
 await page.locator('#stand-s2 .ww-line').waitFor({timeout:10000});
 const after=(await reserve.boundingBox()).y;
 assert.equal(after,before,`Reserve moved from ${before} to ${after}`);
 delete delays['/api/forecast/wind-week'];
 // Tonight: the stand's week under the wind line, the hours behind a fold.
 await page.goto(base+'/');
 await page.locator('.tn-week-line').waitFor();
 assert.equal(await page.locator('.tn-week-line').innerText(),'Right wind for Charca: tonight 19–21 h, Thu');
 await page.locator('.tn-week-hours > summary').click();await page.locator('.tn-week .ww-table').waitFor();
 // Glove-sized chips and Edit list (A-21).
 for(const b of await page.locator('.tn-chip, .tn-chip-edit').evaluateAll(els=>els.map(e=>e.getBoundingClientRect().height)))assert.ok(b>=44,`a chip is ${b}px`);
 assert.deepEqual(await small(page),[]);

 // ── No signal, and the only week on the phone is last night's: said in words within
 //    the wait, never "Checking the wind…" for ever, on Stands and Tonight (R6FE-1) ──
 const age=async(p,at)=>p.evaluate(at=>{for(const k of Object.keys(localStorage))if(k.startsWith('gs_cache:/forecast/wind-week')){const v=JSON.parse(localStorage.getItem(k));v.at=at;localStorage.setItem(k,JSON.stringify(v))}},iso(at));
 await age(page,afternoon-26*3600e3);
 down.add('/api/forecast/wind-week');
 await page.goto(base+'/stands');
 await page.locator('#stand-s2 .stand-wind-wait',{hasText:'No signal. Wind not known yet.'}).waitFor({timeout:15000});
 assert.deepEqual(await page.locator('.stand-wind-wait').allInnerTexts(),['No signal. Wind not known yet.','No signal. Wind not known yet.']);
 assert.equal(await page.locator('.ww-line').count(),0,'last night’s week is never shown as this one');
 await page.goto(base+'/');
 await page.locator('.tn-week-wait',{hasText:'No signal. Wind not known yet.'}).waitFor({timeout:15000});
 down.delete('/api/forecast/wind-week');
 await page.context().close();

 // ── An old copy from earlier tonight: only the hours not yet over, and its age (R6FE-4) ──
 page=await newPage({width:390,height:844},{at:lateEvening});
 await page.goto(base+'/');
 // 19 and 20 h are over at 21:30; the server's line from before still said 19–21 h.
 await page.locator('.tn-week-line').waitFor();
 assert.equal(await page.locator('.tn-week-line').innerText(),'Right wind for Charca: tonight 21 h, Thu');
 assert.equal(await page.locator('.tn-week-age').count(),0,'a fresh answer carries no age');
 await age(page,afternoon+30*60e3);
 down.add('/api/forecast/wind-week');
 await page.reload();
 await page.locator('.tn-week-age').waitFor({timeout:15000});
 assert.equal(await page.locator('.tn-week-line').innerText(),'Right wind for Charca: tonight 21 h, Thu');
 assert.equal(await page.locator('.tn-week-age').innerText(),'No signal. Checked 5 h ago.');
 assert.match(await page.locator('.tn-fresh').innerText(),/^Plan from just now/);
 down.delete('/api/forecast/wind-week');
 await page.context().close();

 // ── Start sit with no signal: Sit mode opens on the verdict Stands just showed, not the
 //    one from the reservation (R6FE-3) ──
 page=await newPage({width:390,height:844},{at:afternoon});
 sitsList=[{id:'t1',stand_id:'s1',stand:'Charca',night:nights[0],user_id:'me',outcome:'unreported',started_at:null,ended_at:null,
  wind_status:'scent_carries',wind_text:'Wind S 10 km/h, wrong for Charca.',claimed_at:iso(afternoon-3600e3),wind_at:hourAt(nights[0],20),sunset_local:'19:54'}];
 await page.goto(base+'/stands');await page.locator('#stand-s1 .ww-line').waitFor();
 down.add('/api/stands/s1/wind');down.add('/api/sits');
 await page.goto(base+'/sit/t1');
 await page.getByText('Wind is right').waitFor({timeout:10000});
 const seat=await page.locator('body').innerText();
 assert.ok(seat.includes('Wind N 12 km/h, clean for Charca.'),seat);
 assert.ok(!/when you reserved/i.test(seat),'not the reservation’s verdict');
 down.delete('/api/stands/s1/wind');down.delete('/api/sits');sitsList=[];
 await page.context().close();

 // ── A stand that can't be judged says why once, and its fold says what to do (R6FE-5) ──
 page=await newPage({width:390,height:844},{at:afternoon});
 stands.push({id:'s3',name:'Loma',lat:null,lon:null,claimed_tonight:false,claimed_by:null});
 week.stands.push({...weekFor('s3','Loma',[]),status:'no_position',line:'Loma isn’t on the map yet, so its wind can’t be judged.',right_tonight:null,right_days:[],
  tonight:{status:'no_position',text:'Wind N 12 km/h. Loma isn’t on the map yet, so where your scent goes can’t be worked out.',now:false}});
 week.stands[2].evenings.forEach(e=>{e.right_evening=false;e.hours.forEach(h=>{h.status='no_position'})});
 // And no forecast at all: said once for tonight and the week, not "No wind forecast tonight." over it.
 const solana=week.stands[1];
 week.stands[1]={...solana,line:'No wind forecast for the week yet.',right_tonight:null,right_days:[],tonight:{status:'no_wind_data',text:'No wind forecast tonight. Check it yourself before you sit Solana.',now:true},
  evenings:solana.evenings.map(e=>({...e,right_evening:false,hours:e.hours.map(h=>({...h,status:'no_wind_data',wind_dir_deg:null,wind_speed_kmh:null}))}))};
 await page.goto(base+'/stands');
 const loma=page.locator('#stand-s3');await loma.locator('.ww-line').waitFor();
 assert.equal(await loma.locator('.stand-wind-slot').innerText(),'Loma isn’t on the map yet, so its wind can’t be judged.');
 assert.equal(await page.locator('#stand-s2 .stand-wind-slot').innerText(),'No wind forecast for the week yet.');
 week.stands[1]=solana;
 await loma.locator('.stand-wind > summary').click();
 assert.equal(await loma.locator('.ww-table').count(),0,'no grid of hours it can’t judge');
 assert.equal(await loma.locator('.stand-wind .ww-note').innerText(),'Place it on the map to see its wind hour by hour.');
 stands.pop();week.stands.pop();

 // ── Insights: the weather comes after the findings, not above them (G-21) ──
 delays['/api/insights']=1500;
 await page.goto(base+'/insights');
 await page.getByText('Reading the cameras…').waitFor();
 assert.equal(await page.locator('.weather-scopes').count(),0,'no weather over the space the findings take');
 const chip=page.getByRole('button',{name:'All animals'});await chip.waitFor({timeout:10000});
 const first=(await chip.boundingBox()).y;await page.waitForTimeout(800);
 assert.equal((await chip.boundingBox()).y,first,'the chip stays under the thumb');
 delete delays['/api/insights'];

 // ── Settings: Hide asks first; one add and one password change per tap ──
 await page.goto(base+'/settings');
 await openSection(page,/^Animals in the advice/);
 const hide=page.getByRole('button',{name:'Hide Wild boar everywhere'});await hide.waitFor();
 let asked='';page.once('dialog',d=>{asked=d.message();d.dismiss()});
 await hide.click();await page.waitForTimeout(300);
 assert.match(asked,/^Hide Wild boar everywhere\?/);
 assert.equal(writes.filter(w=>w.path.startsWith('/api/species')).length,0,'dismissed: nothing hidden');
 const sw=await page.getByRole('switch',{name:'Wild boar in the advice'}).boundingBox();
 assert.ok(sw.width>=44&&sw.height>=44,`the switch is ${sw.width}x${sw.height}`);
 await openSection(page,/^Who can sign in/);
 await page.getByLabel('Email for the new person').fill('maria@x.es');
 await page.getByLabel('Password for the new person').fill('long-enough-1');
 const add=page.getByRole('button',{name:'Add person'});
 await add.dblclick();await page.getByText('Added maria@x.es. They sign in with that email and password.').waitFor();
 assert.equal(writes.filter(w=>w.path==='/api/users'&&w.method==='POST').length,1,'one add for a double tap');
 await openSection(page,/^Password/);
 await page.getByLabel('Current password').fill('old-password-1');await page.getByLabel('New password').fill('new-password-1');
 await page.getByRole('button',{name:'Change password'}).dblclick();
 await page.getByText('Changed. Other phones are signed out.').waitFor();
 assert.equal(writes.filter(w=>w.path==='/api/auth/change-password').length,1,'one change for a double tap');
 assert.deepEqual(await small(page),[]);
 // No animals at all is said, not "Loading…" for ever (D-13).
 speciesList=[];await page.reload();
 await openSection(page,/^Animals in the advice/);
 await page.getByText('No animals yet. They show here once the cameras have caught some.').waitFor();
 speciesList=species;
 await page.context().close();

 // ── Signed out: back to the photo the alert opened, and Back never shows the form (D-10, D-16) ──
 page=await newPage({width:390,height:844},{token:null});
 await page.goto(base+'/photos?species=wild_boar&image=p1');
 await page.waitForURL(/\/login\?next=/);
 assert.equal(new URL(page.url()).searchParams.get('next'),'/photos?species=wild_boar&image=p1');
 await page.getByLabel('Email').fill('admin@x.es');await page.getByLabel('Password').fill('changeme-please');
 await page.getByRole('button',{name:'Sign in'}).click();
 await page.waitForURL(u=>u.pathname==='/photos'&&u.search==='?species=wild_boar&image=p1');
 assert.deepEqual(loginAuth,[null],'signing in never carries an old sign-in');
 const signedIn=await page.evaluate(()=>localStorage.getItem('gs_token'));
 // The sign-in page was replaced, not stacked: Back leaves, it doesn't show the form.
 await page.goBack().catch(()=>{});await page.waitForTimeout(500);
 assert.ok(!page.url().startsWith(base+'/login'),`Back went to ${page.url()}`);
 // A session that runs out on Stands comes back to Stands.
 revoked.add(signedIn);await page.goto(base+'/stands');
 // (Every refused call sends the page to sign in, so wait for the page, not a navigation.)
 await page.getByText('You were signed out. Sign in again.').waitFor();
 assert.equal(new URL(page.url()).search,'?expired=1&next=%2Fstands');
 await page.getByLabel('Password').fill('changeme-please');await page.getByRole('button',{name:'Sign in'}).click();
 await page.waitForURL(u=>u.pathname==='/stands');
 // Opened with a sign-in already there (Back from Tonight): straight on.
 await page.goto(base+'/login?next=%2Fmap');await page.waitForURL(u=>u.pathname==='/map');
 // Never off to another site.
 await page.evaluate(()=>localStorage.removeItem('gs_token'));
 await page.goto(base+'/login?next=%2F%2Fevil.example');
 await page.getByLabel('Password').fill('changeme-please');await page.getByRole('button',{name:'Sign in'}).click();
 await page.waitForURL(u=>u.origin===new URL(base).origin&&u.pathname==='/');
 await page.context().close();

 // ── 768 px: the header's links are a glove's height; the week still reads ──
 page=await newPage({width:768,height:1024});
 await page.goto(base+'/stands');await page.locator('.ww-line').first().waitFor();
 for(const h of await page.locator('.topnav a').evaluateAll(as=>as.map(a=>a.getBoundingClientRect().height)))assert.ok(h>=44,`a header link is ${h}px`);
 assert.deepEqual(await small(page),[]);
 await page.context().close();

 assert.deepEqual(errors,[]);
 console.log('PASS: More tab under 380 px (nothing off the edge, 56 px rows, Escape, active), 44 px targets at 320/390/768, the week line and hour strip on Stands and Tonight (fits 320 px, 12 px letters, speeds on a tap), no signal with last night’s week said in words, an old copy only offers hours not yet over with its age, Sit mode opens on Stands’ verdict, a stand that can’t be judged says so once, Reserve holds still while the wind loads, Insights weather after the findings, Hide asks first, one add and one password change per double tap, no animals said, back to the alert’s photo after sign-in, Back skips the form, an expired session returns to its page, no open redirect.');
 } finally { await browser.close() }
})().catch(e=>{console.error(e);process.exit(1)});
