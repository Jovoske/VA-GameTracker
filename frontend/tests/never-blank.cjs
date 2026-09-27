// Plan items 1 and 6: the app never goes blank, and Tonight is honest on weak signal.
// Runs the BUILT app (npm run build first) from a small server in this file that
// serves dist/ the way Db01 does and answers /api from fixtures, and can drop the
// connection (no signal), hang (one bar), or answer 530 (Cloudflare, server down).
// So the real service worker is exercised: first visit stores the whole app, the
// next launch with no signal opens on the saved plan with its true age, the map
// opens offline, a deploy offers Reload. Without a worker: a deleted map file
// reloads once, a missing one shows a message with the tab bar, a page that throws
// says "Something broke" and is reported, and the main file never arriving is a
// message too. Tonight paints its saved plan first, times out honestly, keeps its
// chips with no signal and drops a pick no longer offered; Stands opens from its
// saved copy; Photos keeps the viewer and the loaded pages when you come back.
// Round 1 review: a deploy whose entry file doesn't arrive leaves the old worker in
// charge; Stands never calls last night's copy "free tonight" nor your own stand
// someone else's; a chip tap with no answer never becomes the saved pick; "Go to
// Tonight" works on Tonight; a crash drops only its own page's saved copies; a late
// photo lands in its place; Cameras and Sit mode say or show what they have.
// Env: PLAYWRIGHT_MODULE, PW_CHANNEL (as the other tests), DIST (default ../dist).
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),http=require('node:http'),path=require('node:path');
const dist=process.env.DIST||path.join(__dirname,'..','dist');
const png=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==','base64');
// The estate's night, as the server counts it: Madrid wall clock, before 06:00 is the evening before.
const clock=new Intl.DateTimeFormat('en-GB',{timeZone:'Europe/Madrid',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'});
const nightOf=t=>{const p=Object.fromEntries(clock.formatToParts(new Date(t)).map(x=>[x.type,x.value]));return new Date(Date.UTC(+p.year,+p.month-1,+p.day,+p.hour,+p.minute)-6*3600e3).toISOString().slice(0,10)};
const ago=m=>new Date(Date.now()-m*60e3).toISOString();

// ── fixtures ──
const species=[['wild_boar','Wild Boar'],['red_deer','Red Deer'],['fox','Fox']].map(([id,common_name])=>({id,common_name,huntable:true,hidden:false,is_priority:false,detections:40}));
const plan=sp=>({verdict:'BEST_ODDS',recommended:{camera:'Encinar del Pozo',species:sp,runner_up:null,probability:0.6,best_window:{start_hour:22,end_hour:1},nights_present:34,active_nights:46,reason:`${sp} seen 34 of 46 nights at this camera.`,caveat:'Pick the best hours and mind the wind.',classes:[]},
 conditions:{moon_phase:'waxing',moon_illum:50,darkness_minutes:700,wind_dir_deg:null,wind_speed_kmh:null},factors:[],where:[],alternates:[],alerts:[],nights_of_data:46,generated_at:new Date().toISOString()});
const overview={totals:{sightings:10,empty:2,nights:5,cameras:2},by_hour:Array.from({length:24},(_,hour)=>({hour,count:hour>20?3:0})),by_camera:[],by_species:[],best_window:{start_hour:22,end_hour:1,share_pct:30}};
const stands=[{id:'s1',name:'Barranco high seat',lat:39.09,lon:-1.36,claimed_tonight:true,claimed_by:'me'},{id:'s2',name:'Charca stand',lat:39.1,lon:-1.35,claimed_tonight:false,claimed_by:null}];
const sits=()=>[{id:'sit1',stand_id:'s1',stand:'Barranco high seat',night:nightOf(Date.now()),user_id:'me',outcome:'unreported',started_at:null,wind_status:null,wind_text:null}];
const cameras=[{id:'c1',name:'Charca',provider_name:null,name_is_custom:false,can_rename:true,battery_pct:80,battery_level:null,signal_pct:70,model:null,image_count:200,empty_count:10,last_capture:ago(30),last_report_at:ago(30),photo_count:null,photo_limit:null,plan_name:null,cycle_end:null,sd_used_mb:null,sd_total_mb:null,health:null}];
let feed=Array.from({length:200},(_,i)=>({image_id:`p${i}`,file_url:`/api/images/p${i}/file`,captured_at:ago(30+i*7),camera:'Charca',camera_id:'c1',label:'Wild boar',species_id:'wild_boar',group_size:1,notes_count:0}));
const reports=[];
// ── the server: dist/ plus fixtures, and the link's condition ──
// brokenPlan: a plan no server sends (its classes a string), so Tonight throws. No best
// hours (best_window null) is a real answer now: animals never seen when you can sit.
const net={mode:'pass',only:null,missing:null,missingOnce:false,swBuild:null,brokenPlan:false,hangMe:false,entryMissing:false};
const NEW_ENTRY='/assets/index-NEXTBUILD.js';
const types={'.js':'text/javascript','.css':'text/css','.html':'text/html','.json':'application/json','.webmanifest':'application/manifest+json','.png':'image/png','.woff2':'font/woff2','.svg':'image/svg+xml'};
const json=(res,body,status=200)=>{res.writeHead(status,{'Content-Type':'application/json'});res.end(JSON.stringify(body))};
function answerApi(req,res,u){
 const p=u.pathname.slice(4);
 if(req.method==='POST'&&p==='/client-errors'){let b='';req.on('data',c=>b+=c);req.on('end',()=>{reports.push(JSON.parse(b));json(res,{status:'saved'},202)});return}
 if(/^\/images\/[^/]+\/(thumb|file)$/.test(p)){res.writeHead(200,{'Content-Type':'image/png'});return res.end(png)}
 if(p==='/auth/me')return json(res,{id:'me',email:'owner@estate.local',role:'admin'});
 if(p==='/forecast/tonight'){const sp=u.searchParams.get('species');return json(res,net.brokenPlan?{...plan('Wild Boar'),recommended:{...plan('Wild Boar').recommended,classes:'broken'}}:plan(sp?species.find(s=>s.id===sp)?.common_name??sp:'Wild Boar'))}
 if(p==='/analytics/overview')return json(res,overview);
 if(p==='/alerts')return json(res,[]);
 if(p==='/species')return json(res,species);
 if(p==='/stands')return json(res,stands);
 if(p==='/sits')return json(res,sits());
 if(p==='/cameras')return json(res,cameras);
 if(/^\/cameras\/[^/]+\/images$/.test(p))return json(res,[]);
 if(p==='/photos/highlights')return json(res,{items:[]});
 if(p==='/photos/filters')return json(res,{species:species.map(s=>({id:s.id,common_name:s.common_name,count:40})),cameras:[{id:'c1',name:'Charca',count:200}]});
 if(p==='/photos'){const before=u.searchParams.get('before'),limit=+u.searchParams.get('limit')||60;const rest=before?feed.filter(x=>x.captured_at<before):feed;const items=rest.slice(0,limit);return json(res,{items,next_before:rest.length>limit?items.at(-1).captured_at:null})}
 return json(res,{detail:'Not Found'},404);
}
// Requests left hanging; the link drops them when its condition changes (set()), as a
// real one does in the end. A request the service worker holds forever would keep a
// new worker from taking over.
const hanging=new Set();
const server=http.createServer((req,res)=>{
 const u=new URL(req.url,'http://x');
 const hit=!net.only||net.only.test(u.pathname);
 if(hit&&net.mode==='drop')return req.socket.destroy();
 if(hit&&net.mode==='hang')return void hanging.add(req.socket);
 if(hit&&net.mode==='down'){res.writeHead(530,{'Content-Type':'text/html'});return res.end('<title>Cloudflare Tunnel error</title>Error 1033')}
 if(net.hangMe&&u.pathname==='/api/auth/me')return void hanging.add(req.socket);
 if(u.pathname==='/api/health')return json(res,{status:'ok'});
 // A deploy whose new entry file never arrives (the link drops while the phone fetches it).
 if(u.pathname===NEW_ENTRY)return req.socket.destroy();
 if(u.pathname.startsWith('/api/'))return answerApi(req,res,u);
 if(net.missing&&net.missing.test(u.pathname)){if(net.missingOnce)net.missing=null;res.writeHead(404);return res.end('Not Found')}
 let file=path.join(dist,path.normalize(u.pathname).replace(/^(\.\.[/\\])+/,''));
 if(!fs.existsSync(file)||fs.statSync(file).isDirectory())file=path.join(dist,'index.html');
 let body=fs.readFileSync(file);const name=path.basename(file);
 // A deploy, as far as the phone can tell: sw.js names another build.
 if(name==='sw.js'&&net.swBuild)body=Buffer.from(body.toString().replace(/const BUILD = "[^"]*"/,`const BUILD = "${net.swBuild}"`));
 if(name==='index.html'&&net.entryMissing)body=Buffer.from(body.toString().replace(/\/assets\/index-[^"]*\.js/,NEW_ENTRY));
 res.writeHead(200,{'Content-Type':types[path.extname(file)]||'application/octet-stream','Cache-Control':file.includes(`${path.sep}assets${path.sep}`)?'public, max-age=31536000, immutable':'no-cache'});
 res.end(body);
});

(async()=>{
 assert.ok(fs.existsSync(path.join(dist,'sw.js'))&&!fs.readFileSync(path.join(dist,'sw.js'),'utf8').includes('__GS_BUILD__'),'run npm run build first: dist/sw.js must be stamped');
 await new Promise(r=>server.listen(0,'127.0.0.1',r));
 const base=`http://127.0.0.1:${server.address().port}`;
 const channel=process.env.PW_CHANNEL??'msedge';
 const browser=await chromium.launch({headless:true,...(channel?{channel}:{}),args:['--enable-unsafe-swiftshader']});
 const errors=[];
 const context=async(serviceWorkers='block')=>{
  const ctx=await browser.newContext({viewport:{width:390,height:844},serviceWorkers,hasTouch:true,isMobile:true,timezoneId:'Europe/Madrid',locale:'en-GB'});
  await ctx.addInitScript(()=>{if(!localStorage.getItem('gs_token'))localStorage.setItem('gs_token','never-blank-fixture')});
  await ctx.route(/ign\.es|catastro|arcgisonline|openfreemap|maptiler/,r=>r.fulfill({contentType:'image/png',body:png}));
  return ctx;
 };
 const open=async(ctx)=>{const page=await ctx.newPage();page.on('pageerror',e=>errors.push(e.message));return page};
 const fresh=page=>page.locator('.tn-fresh').innerText();
 const waitFresh=(page,re)=>page.waitForFunction(re=>new RegExp(re).test(document.querySelector('.tn-fresh')?.textContent||''),re.source,{timeout:25000});
 const tab=(page,name)=>page.locator('nav.tabbar a',{hasText:name}).click();
 const set=(o)=>{hanging.forEach(s=>s.destroy());hanging.clear();Object.assign(net,{mode:'pass',only:null,missing:null,missingOnce:false,brokenPlan:false,hangMe:false,entryMissing:false},o)};
 const states=page=>page.locator('.stand-state').allInnerTexts();
 try {
 // ── 1. The real service worker ──
 {
  const ctx=await context('allow'),page=await open(ctx);
  await page.goto(base+'/');await page.locator('.tn-verdict').waitFor();
  await page.evaluate(()=>navigator.serviceWorker.ready);
  await page.waitForFunction(async()=>{const k=(await caches.keys()).find(n=>n.startsWith('gamesense-shell-'));if(!k||!navigator.serviceWorker.controller)return false;return (await (await caches.open(k)).keys()).some(r=>/\/assets\/Map-.*\.js$/.test(r.url))},null,{timeout:30000,polling:500});
  await tab(page,'Stands');await page.locator('.stand-entry').first().waitFor();await tab(page,'Tonight');
  set({mode:'drop'});await page.reload();await page.locator('.tn-verdict').waitFor();
  await waitFresh(page,/^No signal\. Plan from just now\./);
  await tab(page,'Map');await page.locator('.maplibregl-canvas').waitFor({timeout:20000});
  assert.equal(await page.locator('nav.tabbar a').count(),7,'the map opens with no signal: its code was stored on the first visit');
  await tab(page,'Stands');await page.locator('.stand-fresh').waitFor();
  assert.match(await page.locator('.stand-fresh').innerText(),/^No signal\. Stands from just now\./);
  assert.match(await page.locator('#stand-s1').innerText(),/Yours tonight/,'who you are is saved too');
  set({mode:'down'});await page.goto(base+'/');await page.locator('.tn-verdict').waitFor();
  await waitFresh(page,/^Can’t reach the server\. Plan from/);
  assert.doesNotMatch(await page.title(),/Cloudflare/,'a 530 from the tunnel opens the saved app, not an error page');
  set({mode:'drop'});
  const later=await open(ctx);await later.clock.install({time:new Date(Date.now()+14*3600e3)});
  await later.goto(base+'/');await later.locator('.tn-verdict').waitFor();
  // 14 h on from after 16:00 is past 06:00, when the plan is last night's and says so.
  await waitFresh(later,/^No signal\. Plan from 14 h ago(\.|, made for last night\.)/);await later.close();
  // One bar: the page gives up on /stands first, so the worker never answers. With
  // nothing saved of its own, the page reads the worker's copy itself (J-06).
  set({});await page.goto(base+'/stands');await page.locator('#stand-s1').waitFor();
  await page.evaluate(()=>{localStorage.removeItem('gs_cache:/stands');localStorage.removeItem('gs_cache:/sits')});
  set({mode:'hang',only:/^\/api\/(stands|sits|map\/tonight)$/});
  const hung=await open(ctx);await hung.clock.install();await hung.goto(base+'/stands');
  await hung.getByText('Loading stands…').waitFor();await hung.clock.fastForward('00:16');
  await hung.locator('#stand-s1').waitFor();
  assert.match(await hung.locator('.stand-fresh').innerText(),/^No answer from the server\. Stands from just now\./);
  await hung.close();
  // A deploy whose new entry file doesn't arrive: the new worker must not take over
  // with a page it can't open. The old one stays, and opens the plan with no signal.
  set({swBuild:'broken-build',entryMissing:true});
  await page.evaluate(()=>navigator.serviceWorker.getRegistration().then(r=>r.update()).catch(()=>{}));await page.waitForTimeout(500);
  await page.waitForFunction(async()=>{const r=await navigator.serviceWorker.getRegistration();return r.active&&!r.installing&&!r.waiting},null,{timeout:30000,polling:300});
  await page.waitForTimeout(500);
  assert.ok(!(await page.evaluate(()=>caches.keys())).includes('gamesense-shell-broken-build'),'half a build is not kept');
  assert.equal(await page.locator('.update-ready').count(),0,'and not offered');
  set({mode:'drop'});await page.goto(base+'/').catch(()=>{});await page.locator('.tn-verdict').waitFor();
  await waitFresh(page,/^No signal\. Plan from/);
  set({swBuild:'next-build'});
  await page.goto(base+'/');await page.locator('.tn-verdict').waitFor();
  await page.evaluate(()=>navigator.serviceWorker.getRegistration().then(r=>r.update()));
  await page.locator('.update-ready').waitFor({timeout:30000});
  assert.match(await page.locator('.update-ready').innerText(),/A new version of GameSense is ready/);
  set({swBuild:null});await ctx.close();
 }
 // ── 2. No service worker: missing files and a page that throws ──
 {
  const ctx=await context(),page=await open(ctx);
  await page.goto(base+'/');await page.locator('.tn-verdict').waitFor();
  set({missing:/\/assets\/Map-.*\.js$/,missingOnce:true});
  await tab(page,'Map');await page.locator('.maplibregl-canvas').waitFor({timeout:30000});
  assert.ok(await page.evaluate(()=>sessionStorage.getItem('gs_reloaded_at')),'a map file deleted by a deploy: one reload by itself, then the map');
  assert.ok(reports.some(r=>r.kind==='chunk'&&r.route==='/map'),'and it was reported');
  await ctx.close();
 }
 {
  const ctx=await context(),page=await open(ctx);
  await page.goto(base+'/');await page.locator('.tn-verdict').waitFor();
  set({missing:/\/assets\/Map-.*\.js$/});
  await tab(page,'Map');await page.locator('.crashed').waitFor({timeout:30000});
  await page.waitForFunction(()=>/still didn’t load/.test(document.querySelector('.crashed').textContent),null,{timeout:15000});
  assert.equal(await page.locator('nav.tabbar a').count(),7,'a file that stays missing: a message, the tab bar kept');
  await tab(page,'Stands');await page.locator('.stand-entry').first().waitFor();
  assert.equal(await page.locator('.crashed').count(),0,'another tab clears it');
  await ctx.close();
 }
 {
  const ctx=await context(),page=await open(ctx);
  await page.goto(base+'/');await page.locator('.tn-verdict').waitFor();
  set({mode:'drop'});
  await tab(page,'Map');await page.locator('.crashed').waitFor({timeout:30000});
  await page.waitForFunction(()=>/No signal, and this page isn’t saved/.test(document.querySelector('.crashed').textContent),null,{timeout:15000});
  assert.ok(page.url().endsWith('/map'),'no signal and the map never opened: a message, not a reload into the browser’s offline page');
  // Signal, but the server (or its tunnel) down: said as that, not as no signal.
  set({mode:'down',only:/^\/api\/health$/});await tab(page,'Stands');await page.locator('.stand-entry').first().waitFor();
  await tab(page,'Map');await page.locator('.crashed').waitFor({timeout:30000});
  await page.waitForFunction(()=>/Can’t reach the server, and this page isn’t saved/.test(document.querySelector('.crashed').textContent),null,{timeout:15000});
  set({});
  set({brokenPlan:true});await page.goto(base+'/');await page.locator('.crashed').waitFor();
  assert.match(await page.locator('.crashed').innerText(),/Something broke\./);
  assert.equal(await page.locator('nav.tabbar a').count(),7);
  const kept=await page.evaluate(()=>Object.keys(localStorage).filter(k=>k.startsWith('gs_cache:')));
  assert.ok(!kept.some(k=>k.startsWith('gs_cache:/forecast/tonight')),'the saved plan that broke Tonight is dropped');
  assert.ok(kept.includes('gs_cache:/stands')&&kept.includes('gs_cache:/sits'),'Stands’ saved copies are not Tonight’s to drop');
  await page.waitForTimeout(500);
  assert.ok(reports.some(r=>r.kind==='render'&&r.route==='/'&&/classes/.test(r.message)&&r.at),'a page that throws is reported, with when');
  set({});await page.getByRole('link',{name:'Go to Tonight'}).click();await page.locator('.tn-verdict').waitFor();
  assert.equal(await page.locator('.crashed').count(),0,'“Go to Tonight” on Tonight tries it again');
  await ctx.close();
 }
 {
  const ctx=await context(),page=await open(ctx);
  set({missing:/\/assets\/index-.*\.js$/});
  await page.goto(base+'/');await page.getByText('GameSense is taking a long time to open.').waitFor({timeout:20000});
  set({});await page.getByRole('button',{name:'Reload'}).click();await page.locator('.tn-verdict').waitFor();
  await ctx.close();
 }
 // ── 3. Tonight on weak signal ──
 {
  const ctx=await context(),page=await open(ctx);const asked=[];
  page.on('request',r=>{if(r.url().includes('/api/'))asked.push(new URL(r.url()).pathname+new URL(r.url()).search)});
  await page.goto(base+'/');await waitFresh(page,/^Plan from just now\./);
  await page.evaluate(()=>{const k='gs_cache:/forecast/tonight',v=JSON.parse(localStorage.getItem(k));v.at=new Date(Date.now()-40*60e3).toISOString();localStorage.setItem(k,JSON.stringify(v))});
  set({mode:'hang',only:/^\/api\/forecast\/tonight$/});
  const t0=Date.now();await page.reload();await page.locator('.tn-verdict').waitFor({timeout:5000});
  assert.ok(Date.now()-t0<3000,'the saved plan is painted first on a link that never answers');
  assert.match(await fresh(page),/^Plan from 40 min ago\. Checking for a newer one…/);
  await waitFresh(page,/^No answer from the server\. Plan from 40 min ago\./);
  set({});await page.reload();await waitFresh(page,/^Plan from just now\./);
  set({mode:'drop',only:/^\/api\/forecast\/tonight$/});
  await page.locator('.tn-chip',{hasText:'Red Deer'}).click();
  await page.getByText('No signal. Still showing the plan you had.').waitFor();
  assert.equal(await page.locator('.tn-chip',{hasText:'Anything'}).getAttribute('aria-pressed'),'true','no signal: the chips go back, the plan stays');
  assert.equal(await page.evaluate(()=>localStorage.getItem('gs_species_filter')),'[]');
  set({});await page.waitForTimeout(300);asked.length=0;
  await Promise.all([page.waitForResponse(r=>r.url().endsWith('species=fox')),page.locator('.tn-chip',{hasText:'Fox'}).click()]);
  await page.waitForTimeout(500);
  assert.deepEqual(asked,['/api/forecast/tonight?species=fox'],'a chip asks for the plan only');
  await page.evaluate(()=>localStorage.setItem('gs_species_filter',JSON.stringify(['roe_deer'])));
  asked.length=0;await page.reload();
  await page.waitForFunction(()=>localStorage.getItem('gs_species_filter')==='[]');await page.waitForTimeout(800);
  assert.equal(await page.locator('.tn-chip',{hasText:'Anything'}).getAttribute('aria-pressed'),'true','a saved pick no longer offered falls back to Anything');
  assert.equal(asked.filter(u=>u.startsWith('/api/forecast/tonight')).at(-1),'/api/forecast/tonight');
  // A tap that never gets an answer is not the pick: not when a second tap fails,
  // not when the hunter leaves. The next launch with no signal opens on the plan.
  set({mode:'hang',only:/^\/api\/forecast\/tonight$/});
  await page.locator('.tn-chip',{hasText:'Red Deer'}).click();await page.waitForTimeout(300);
  await page.locator('.tn-chip',{hasText:'Fox'}).click();await page.waitForTimeout(300);
  set({mode:'drop',only:/^\/api\/forecast\/tonight$/});
  await page.getByText('No signal. Still showing the plan you had.').waitFor();
  assert.deepEqual(await page.locator('.tn-chip[aria-pressed="true"]').allInnerTexts(),['Anything'],'back to the pick the plan on screen answers');
  set({mode:'hang',only:/^\/api\/forecast\/tonight$/});
  await page.locator('.tn-chip',{hasText:'Red Deer'}).click();await page.waitForTimeout(300);
  await tab(page,'Stands');await page.locator('.stand-entry').first().waitFor();
  assert.equal(await page.evaluate(()=>localStorage.getItem('gs_species_filter')),'[]','an unanswered tap is never saved');
  set({mode:'drop',only:/^\/api\//});await page.goto(base+'/');await page.locator('.tn-verdict').waitFor();
  await waitFresh(page,/^No signal\. Plan from/);
  assert.equal(await page.locator('.tn-chip').count(),4);
  set({});await ctx.close();
 }
 // ── 3b. Stands and Sit mode on a link that hangs, from what the phone saved ──
 {
  const ctx=await context(),page=await open(ctx);
  await page.goto(base+'/stands');await page.waitForFunction(()=>/Yours tonight/.test(document.querySelector('#stand-s1')?.textContent||''));
  // Who you are is known at once, before /auth/me answers.
  set({hangMe:true});const cold=await open(ctx);await cold.goto(base+'/stands');await cold.locator('#stand-s1').waitFor();
  await cold.waitForTimeout(1500);
  assert.match(await cold.locator('#stand-s1 .stand-state').innerText(),/^Yours tonight$/,'your own stand is yours while /auth/me hangs');
  assert.equal(await cold.getByRole('button',{name:'Start sit'}).count(),1);await cold.close();
  // Sit mode paints the saved sit while /sits hangs.
  set({mode:'hang',only:/^\/api\/sits$/});const seat=await open(ctx);await seat.goto(base+'/sit/sit1');
  await seat.getByText('Barranco high seat').waitFor({timeout:2500});await seat.close();
  // A copy from an earlier night, the link hanging: tonight's reservations are unknown,
  // not "Every stand is free", and nothing can be reserved on that guess.
  set({});
  await page.evaluate(()=>{for(const k of ['gs_cache:/stands','gs_cache:/sits']){const v=JSON.parse(localStorage.getItem(k));v.at=new Date(Date.now()-30*3600e3).toISOString();if(k.endsWith('/sits'))v.data=v.data.map(x=>({...x,night:'2000-01-01'}));localStorage.setItem(k,JSON.stringify(v))}});
  set({mode:'hang',only:/^\/api\/(stands|sits|map\/tonight)$/});
  await page.reload();await page.locator('.stand-entry').first().waitFor({timeout:5000});await page.waitForTimeout(1000);
  assert.deepEqual(await states(page),['Tonight not known yet','Tonight not known yet']);
  assert.equal(await page.locator('.stand-tonight').count(),0,'no “Every stand is free tonight.”');
  assert.equal(await page.getByRole('button',{name:'Reserve'}).count(),0);
  assert.match(await page.locator('.stand-fresh').innerText(),/^Stands from 1 d ago\. Checking…/);
  set({});await page.reload();await page.waitForFunction(()=>/Yours tonight/.test(document.querySelector('#stand-s1')?.textContent||''));
  assert.equal(await page.locator('.stand-fresh').count(),0,'fresh: no age line');
  // Cameras with no signal says the list is what you saw, and when.
  await tab(page,'Cameras');await page.locator('.cam-card').first().waitFor();
  set({mode:'drop',only:/^\/api\/cameras/});await tab(page,'Stands');await page.locator('.stand-entry').first().waitFor();
  await tab(page,'Cameras');await page.getByText('No signal. Showing what you saw just now.').waitFor();
  set({});await ctx.close();
 }
 // ── 4. Photos: back in the app with the viewer open deep in the feed ──
 {
  const ctx=await context(),page=await open(ctx);await page.clock.install();
  await page.goto(base+'/photos');await page.locator('.photos-tile').nth(59).waitFor();
  for(const n of [60,120]){await page.locator('.photos-more').click();await page.waitForFunction(n=>document.querySelectorAll('.photos-tile').length>n,n)}
  await page.locator('.photos-tile').nth(150).click();await page.getByText('Photo 151 of 180').first().waitFor();
  // One camera delivers late: a photo taken between the two newest on screen.
  const between=new Date((Date.parse(feed[0].captured_at)+Date.parse(feed[1].captured_at))/2).toISOString();
  feed=[{...feed[0],image_id:'new1',file_url:'/api/images/new1/file',captured_at:new Date().toISOString()},feed[0],{...feed[0],image_id:'late1',file_url:'/api/images/late1/file',camera:'Encinar',captured_at:between},...feed.slice(1)];
  const back=()=>page.evaluate(()=>{document.dispatchEvent(new Event('visibilitychange'));window.dispatchEvent(new Event('focus'))});
  await page.clock.fastForward('03:00');await back();await page.waitForTimeout(800);
  assert.ok(await page.getByText('Photo 151 of 180').count(),'back with a photo open: no crash, the same photo');
  await page.keyboard.press('Escape');await page.clock.fastForward('03:00');await back();
  await page.waitForFunction(()=>document.querySelectorAll('.photos-tile').length===182);
  assert.equal(await page.locator('.photos-tile').count(),182,'the newer photo on top, the pages already loaded kept');
  assert.deepEqual(await page.locator('.photos-tile img').evaluateAll(els=>els.slice(0,4).map(e=>new URL(e.src).pathname.split('/')[3])),['new1','p0','late1','p1'],'a photo that arrived late sits where it was taken');
  await ctx.close();
 }
 assert.deepEqual(errors.filter(e=>!/start_hour/.test(e)),[]);
 console.log('PASS: first visit stores the app; no signal, one bar and a 530 open the saved plan with its true age; the map offline; Stands offline with who you are, and from the worker’s copy on one bar; a deploy offers Reload, and one whose entry file never arrives leaves the old app working offline; a deleted map file reloads once; a missing one, no signal, the server down, a page that throws and a main file that never arrives each show a message with a way on, never a blank screen; a crash drops only its own page’s saved copies and “Go to Tonight” works on Tonight; crashes are reported with when; Tonight paints its saved plan first, times out honestly, keeps its chips with no signal, never saves an unanswered tap, asks only for the plan on a chip and drops a pick no longer offered; Stands never shows an earlier night as free nor your stand as someone else’s; Sit mode and Cameras show what they saved; Photos keeps the viewer and the loaded pages on return and puts a late photo in its place.');
 } finally { await browser.close();server.close() }
})().catch(e=>{console.error(e);process.exit(1)});
