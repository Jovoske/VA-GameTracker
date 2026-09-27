// Alerts that respect the hunter (plan item 15, feature 19), against fixtures and a
// stand-in for the browser's push API: the app sends its subscription again when it
// opens and Settings says what that check found (D-04); quick taps on the animal
// switches go to the server one save at a time and end as the screen shows them,
// and a failed save shows what the server has (D-14, I-14); the permission prompt
// is asked for before anything is saved (D-19); signing out drops the phone's
// subscription with the leaving person's token (D-17); the plan switch and quiet
// hours save and say so, glove-sized; Recent says what happened to each alert; an
// alert's link opens its photo by its time however many photos came after (K-07);
// Tonight doesn't say twice that a camera went quiet (G-23). The plan switch turns
// Alerts on when they are off (the plan comes through them); with no signal a
// failed save goes back to what the server last confirmed; coming back to the app
// after hours sends the subscription again; quiet updates fold into their alert in
// Recent; the clock pickers stack on a narrow phone; an iPhone is told where the
// count goes. The service worker's side is frontend/tests/sw-push.cjs.
// Run like map-and-stands.cjs (BASE_URL, PW_CHANNEL).
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert=require('node:assert/strict');
(async()=>{
 const channel=process.env.PW_CHANNEL??'msedge',base=process.env.BASE_URL||'http://127.0.0.1:5173';
 const browser=await chromium.launch({headless:true,...(channel?{channel}:{}),args:['--enable-unsafe-swiftshader']});
 const errors=[];
 try {
 const tile=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==','base64');
 const ago=h=>new Date(Date.now()-h*3600e3).toISOString();
 const keyBytes=Array.from({length:65},(_,i)=>i===0?4:i);
 const publicKey=Buffer.from(keyBytes).toString('base64url');
 const sleep=ms=>new Promise(r=>setTimeout(r,ms));

 // The server: what it has saved, and what it was asked.
 let server,log,subscribeFails;
 const reset=()=>{
  server={enabled:true,species:{wild_boar:true,red_deer:false,roe_deer:false},subs:[],quiet_start:null,quiet_end:null,plan_push:false};
  log=[];subscribeFails=false;
 };
 const settings=()=>({enabled:server.enabled,configured:true,
  species:[['wild_boar','Wild boar',120],['red_deer','Red deer',40],['roe_deer','Roe deer',12]].map(([id,common_name,detections])=>({id,common_name,detections,selected:server.species[id]})),
  cameras:[{id:'c1',name:'Charca',alerts:true}],quiet_start:server.quiet_start,quiet_end:server.quiet_end,plan_push:server.plan_push,
  public_key:publicKey,subscriptions:server.subs.length});
 const feed={unread:0,items:[
  {id:'n1',kind:'summary',title:'While you sat',body:'Wild boar 2 visits, last one 21:40.',url:'/photos?species=wild_boar',push_status:'sent',created_at:ago(1),read_at:ago(1)},
  {id:'n2',kind:'sighting',title:'Wild boar at Charca',body:'1 visit at 21:40.',url:'/photos?species=wild_boar',push_status:'in_summary',created_at:ago(2),read_at:ago(1)},
  {id:'n3',kind:'sighting',title:'Wild boar at Charca',body:'3 visits since 00:55, last one 01:40.',url:'/photos?species=wild_boar',push_status:'sent',updates:2,updated_at:ago(19),created_at:ago(20),read_at:ago(19)},
 ]};

 // A stand-in for the browser's push API, kept in localStorage so it outlives a reload.
 const fakePush=()=>{
  const get=k=>JSON.parse(localStorage.getItem(k)||'null'),put=(k,v)=>localStorage.setItem(k,JSON.stringify(v));
  window.__push=[];
  Object.defineProperty(Notification,'permission',{configurable:true,get:()=>get('fake_perm')||'default'});
  Notification.requestPermission=async()=>{window.__push.push(['permission',Date.now()]);put('fake_perm','granted');return 'granted'};
  const sub=d=>({endpoint:d.endpoint,options:{applicationServerKey:new Uint8Array(d.key).buffer},
   toJSON:()=>({endpoint:d.endpoint,keys:{p256dh:'BPk',auth:'au'}}),
   unsubscribe:async()=>{window.__push.push(['unsubscribe',Date.now()]);localStorage.removeItem('fake_sub');return true}});
  const pushManager={getSubscription:async()=>{const d=get('fake_sub');return d?sub(d):null},
   subscribe:async o=>{window.__push.push(['subscribe',Date.now()]);const d={endpoint:'https://push.example/new',key:Array.from(new Uint8Array(o.applicationServerKey))};put('fake_sub',d);return sub(d)}};
  const reg={pushManager,update:async()=>{}};
  const sw=navigator.serviceWorker;
  Object.defineProperty(sw,'getRegistration',{value:async()=>reg});
  Object.defineProperty(sw,'register',{value:async()=>reg});
  Object.defineProperty(sw,'ready',{get:()=>Promise.resolve(reg)});
 };

 // Tonight: PL19 went quiet, and the Changed line says so already.
 const win={start_hour:21,end_hour:0,start:'21:15',end:'00:15'};
 const plan={verdict:'BEST_ODDS',changed:{kind:'silence',camera:'PL19',text:'PL19 has had nothing for 4 nights. It usually sees about 2 a night.'},
  wind:{status:'no_wind_data',text:'No wind forecast tonight. Check it yourself.',is_advice:false},calibration:{available:false,n_evaluated:0},
  recommended:{camera:'Charca',camera_id:'c1',species:'Wild boar',runner_up:null,probability:0.7,best_window:win,expect:'Wild boar',classes:[],nights_present:21,active_nights:30,visits:13,photos:40,
   reason:'Wild boar seen 21 of 30 nights at this camera.',caveat:'The camera watches all night.'},
  conditions:{moon_phase:'New Moon',moon_illum:4,darkness_minutes:720,sunset_local:'19:54'},factors:[],where:[],alternates:[],alerts:[],nights_of_data:30,freshness:null};
 // How each PUT is to go, in order: 'ok' (default), 'slow' or 'fail'; `offline`
 // drops every settings request as no signal does.
 const put={plan:[],offline:false};
 const newPage=async({token='alerts-fixture',perm=null,sub=null,photoFeed=null,width=390,locale='en-GB',userAgent}={})=>{
  const page=await browser.newPage({viewport:{width,height:844},serviceWorkers:'block',hasTouch:true,timezoneId:'Europe/Madrid',locale,...(userAgent?{userAgent}:{})});
  await page.addInitScript(([t,perm,sub])=>{
   if(!sessionStorage.getItem('seeded')){
    sessionStorage.setItem('seeded','1');localStorage.setItem('gs_token',t);
    if(perm)localStorage.setItem('fake_perm',JSON.stringify(perm));
    if(sub)localStorage.setItem('fake_sub',JSON.stringify(sub));
   }
  },[token,perm,sub]);
  await page.addInitScript(fakePush);
  page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/api/**',async route=>{
   const req=route.request(),u=new URL(req.url()),p=u.pathname,m=req.method(),json=(b,status=200)=>route.fulfill({status,contentType:'application/json',body:JSON.stringify(b)});
   if(/\/thumb$/.test(p))return route.fulfill({contentType:'image/png',body:tile});
   if(/\/file$/.test(p))return route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="800" height="450"><rect width="800" height="450" fill="#394b3b"/></svg>'});
   if(p==='/api/notifications/subscriptions'&&m==='POST'){
    const b=req.postDataJSON();log.push(['subscribe',b.endpoint,Date.now()]);
    if(subscribeFails)return route.abort('internetdisconnected');
    if(!server.subs.includes(b.endpoint))server.subs.push(b.endpoint);
    return json({status:'subscribed',subscriptions:server.subs.length,public_key:publicKey,enabled:server.enabled});
   }
   if(p==='/api/notifications/subscriptions'&&m==='DELETE'){
    const b=req.postDataJSON();log.push(['unsubscribe',b.endpoint,req.headers()['authorization']]);
    server.subs=server.subs.filter(x=>x!==b.endpoint);return json({status:'removed',subscriptions:server.subs.length});
   }
   if(p==='/api/notifications/settings'&&put.offline){log.push(['offline',m]);return route.abort('internetdisconnected')}
   if(p==='/api/notifications/settings'&&m==='PUT'){
    const b=req.postDataJSON();log.push(['put',b,Date.now()]);
    const how=put.plan.shift()??'ok';
    if(how==='slow')await sleep(1500);
    if(how==='fail')return json({detail:'Server busy'},503);
    if('enabled' in b)server.enabled=b.enabled;
    if(b.species_ids)for(const id of Object.keys(server.species))server.species[id]=b.species_ids.includes(id);
    if('quiet' in b){server.quiet_start=b.quiet?b.quiet_start:null;server.quiet_end=b.quiet?b.quiet_end:null}
    if('plan_push' in b)server.plan_push=b.plan_push;
    return json({enabled:server.enabled,species_ids:Object.keys(server.species).filter(k=>server.species[k]).sort(),muted_camera_ids:[],
     quiet_start:server.quiet_start,quiet_end:server.quiet_end,plan_push:server.plan_push});
   }
   if(p==='/api/notifications/settings')return json(settings());
   if(p==='/api/notifications')return json(feed);
   if(p==='/api/notifications/read')return json({marked:0});
   if(p==='/api/auth/me')return json({id:'me',email:'ana@estate.local',role:'member'});
   if(p==='/api/photos/filters')return json({species:[{id:'wild_boar',common_name:'Wild boar',count:70}],cameras:[]});
   if(p==='/api/photos/highlights')return json({items:[]});
   if(p==='/api/photos'){
    log.push(['photos',u.search]);
    const all=photoFeed??[];const before=u.searchParams.get('before');const limit=+(u.searchParams.get('limit')||60);
    const items=all.filter(x=>!before||Date.parse(x.captured_at)<Date.parse(before)).slice(0,limit);
    return json({items,next_before:items.length===limit?items.at(-1).captured_at:null,next_before_id:items.length===limit?items.at(-1).image_id:null});
   }
   if(p==='/api/sits/mine')return json({live:[],to_report:[]});
   if(p==='/api/forecast/tonight')return json({...plan,generated_at:new Date().toISOString()});
   if(p==='/api/alerts')return json([
    {type:'quiet',severity:'warn',title:'PL19 quiet',camera:'PL19',text:'Nothing on its last 4 watched nights. This camera usually sees more.'},
    {type:'camera',severity:'warn',title:'Charca battery low',text:'15% left. Bring batteries on your next visit.'}]);
   if(p==='/api/sits'||p==='/api/stands'||p==='/api/users'||p==='/api/species'||p==='/api/camera-accounts'||p==='/api/cameras')return json([]);
   return json({detail:'Not Found'},404);
  });
  return page;
 };
 const said=page=>page.locator('.switch-said').first();
 const row=(page,name)=>page.getByRole('switch',{name:new RegExp('^'+name)});

 // ── D-04: the server lost this phone's subscription; opening the app puts it back ──
 reset();
 let page=await newPage({perm:'granted',sub:{endpoint:'https://push.example/phone',key:keyBytes}});
 await page.goto(base+'/');
 for(let i=0;i<40&&!log.some(e=>e[0]==='subscribe');i++)await sleep(100);
 assert.ok(log.some(e=>e[0]==='subscribe'&&e[1]==='https://push.example/phone'),'the app sends its subscription as it opens');
 assert.deepEqual(server.subs,['https://push.example/phone']);
 await page.goto(base+'/settings#notifications');
 await page.getByText('This phone gets alerts.').waitFor();
 // No signal: set up on the phone, but not checked; it says so, and can check again.
 subscribeFails=true;
 await page.reload();
 await page.getByText('Set up on this phone, but the server couldn’t be reached to check it.').waitFor();
 const again=page.getByRole('button',{name:'Check again'});
 assert.ok((await again.boundingBox()).height>=44,'Check again is glove-sized');
 subscribeFails=false;
 await again.click();
 await page.getByText('This phone gets alerts.').waitFor();
 assert.equal(await page.getByRole('button',{name:'Send a test'}).isEnabled(),true);

 // ── Recent says what happened to each alert; quiet updates are in the alert ──
 const recent=await page.locator('.settings-section, section').filter({hasText:'Recent'}).last().innerText();
 assert.match(recent,/in one message/);assert.match(recent,/2 quiet updates/);
 assert.match(recent,/3 visits since 00:55, last one 01:40\./);
 await page.screenshot({path:process.env.SHOT_DIR?process.env.SHOT_DIR+'/alerts-settings.png':'/dev/null',fullPage:true}).catch(()=>{});

 // ── D-14 / I-14: quick taps, a slow save, then a failed one ──
 log=[];put.plan=['slow'];
 await row(page,'Red deer').click();
 await sleep(700); // the first save is out (and slow)
 await row(page,'Roe deer').click();
 await sleep(150);
 await row(page,'Wild boar').click();
 await page.getByText('Saved.').waitFor({timeout:8000});
 const puts=log.filter(e=>e[0]==='put');
 assert.equal(puts.length,2,'two saves: the first, then everything tapped while it was out');
 assert.deepEqual(puts[0][1],{species_ids:['wild_boar','red_deer']});
 assert.deepEqual(puts[1][1],{species_ids:['red_deer','roe_deer']});
 assert.ok(puts[1][2]>=puts[0][2]+1400,'the second save waited for the first');
 assert.deepEqual(server.species,{wild_boar:false,red_deer:true,roe_deer:true},'the server has what the screen shows');
 for(const [name,on] of [['Wild boar',false],['Red deer',true],['Roe deer',true]])
  assert.equal(await row(page,name).getAttribute('aria-checked'),String(on),name);
 // A save that fails: the switches show what the server has, and it says so.
 put.plan=['fail'];
 await row(page,'Wild boar').click();
 await page.getByRole('alert').filter({hasText:'That didn’t save.'}).waitFor();
 assert.equal(await row(page,'Wild boar').getAttribute('aria-checked'),'false','back to what is saved');
 assert.match(await page.getByRole('alert').filter({hasText:'That didn’t save.'}).innerText(),/The switches show what is saved\./);
 // No signal: the save fails and so does asking the server again. The switches go
 // back to what the server last confirmed, never the choice that wasn't saved.
 put.offline=true;
 await row(page,'Roe deer').click();
 await page.getByRole('alert').filter({hasText:'No signal, so that didn’t save.'}).waitFor();
 assert.ok(log.some(e=>e[0]==='offline'&&e[1]==='GET'),'it tried to ask the server again');
 assert.equal(await row(page,'Roe deer').getAttribute('aria-checked'),'true','back to what is saved');
 assert.equal(server.species.roe_deer,true);
 assert.match(await page.getByRole('alert').filter({hasText:'No signal'}).innerText(),/The switches show what was saved last\./);
 put.offline=false;

 // ── The plan before sunset and quiet hours save, and say so ──
 put.plan=[];log=[];
 await row(page,'Tonight’s plan before sunset|Tonight\'s plan before sunset').click();
 await said(page).filter({hasText:'Saved.'}).waitFor();
 assert.equal(server.plan_push,true);
 const planRow=await row(page,'Tonight').boundingBox();
 assert.ok(planRow.height>=44,`the plan switch is glove-sized (${planRow.height})`);
 await row(page,'Quiet hours').click();
 await page.locator('.quiet-hours input').first().waitFor();
 await page.getByText('Saved.').waitFor();
 assert.deepEqual([server.quiet_start,server.quiet_end],['23:00','07:00']);
 const from=page.locator('.quiet-hours input').first();
 assert.ok((await from.boundingBox()).height>=44,'the clock pickers are glove-sized');
 await from.fill('22:30');
 await page.waitForFunction(()=>document.body.innerText.includes('Nothing buzzes from 22:30 to 07:00'));
 for(let i=0;i<40&&server.quiet_start!=='22:30';i++)await sleep(100);
 assert.equal(server.quiet_start,'22:30');
 const overflow=await page.evaluate(()=>document.documentElement.scrollWidth<=document.documentElement.clientWidth);
 assert.ok(overflow,'no sideways scroll at 390px');
 await page.locator('#notifications').screenshot({path:(process.env.SHOT_DIR||'/tmp')+'/alerts-when.png'}).catch(()=>{});

 // ── D-17: signing out drops the phone's subscription, in the leaving person's name ──
 log=[];
 await page.getByRole('button',{name:'Sign out'}).first().click();
 await page.waitForURL(/\/login/);
 for(let i=0;i<40&&!log.some(e=>e[0]==='unsubscribe');i++)await sleep(100);
 const bye=log.find(e=>e[0]==='unsubscribe');
 assert.ok(bye,'the server is told');
 assert.equal(bye[2],'Bearer alerts-fixture','with the token of the person signing out');
 assert.equal(await page.evaluate(()=>localStorage.getItem('fake_sub')),null,'and the phone forgets it');
 await page.close();

 // ── The plan comes through Alerts: turned on with Alerts off, it turns them on ──
 reset();server.enabled=false;
 page=await newPage();
 await page.goto(base+'/settings#notifications');
 await row(page,'Alerts').waitFor();
 assert.equal(await row(page,'Tonight').getAttribute('aria-checked'),'false');
 await page.getByText('Turning it on turns Alerts on too.').waitFor();
 log=[];
 await row(page,'Tonight').click();
 await said(page).filter({hasText:'Alerts are on too'}).waitFor({timeout:8000});
 assert.deepEqual(log.filter(e=>e[0]==='put').map(e=>e[1]),[{enabled:true,plan_push:true}],'one save, both on');
 assert.ok((await page.evaluate(()=>window.__push)).some(e=>e[0]==='permission'),'permission asked from the same tap');
 assert.deepEqual([server.enabled,server.plan_push],[true,true]);
 assert.deepEqual(server.subs,['https://push.example/new'],'this phone subscribed');
 assert.equal(await row(page,'Alerts').getAttribute('aria-checked'),'true');
 assert.equal(await row(page,'Tonight').getAttribute('aria-checked'),'true');
 await page.getByText('This phone gets alerts.').waitFor();
 await page.close();

 // ── An installed app brought back after hours sends its subscription again ──
 reset();
 page=await newPage({perm:'granted',sub:{endpoint:'https://push.example/phone',key:keyBytes}});
 await page.goto(base+'/');
 for(let i=0;i<40&&!log.some(e=>e[0]==='subscribe');i++)await sleep(100);
 server.subs=[];log=[]; // the server lost it meanwhile
 await page.evaluate(()=>{document.dispatchEvent(new Event('visibilitychange'))});
 await sleep(500);
 assert.equal(log.filter(e=>e[0]==='subscribe').length,0,'not on every flick back to the app');
 await page.evaluate(()=>{const real=Date.now.bind(Date);Date.now=()=>real()+7*3600e3;document.dispatchEvent(new Event('visibilitychange'))});
 for(let i=0;i<40&&!log.some(e=>e[0]==='subscribe');i++)await sleep(100);
 assert.deepEqual(server.subs,['https://push.example/phone'],'back after hours: sent again');
 await page.close();

 // ── A narrow phone with a 12-hour clock: the clock pickers stack, AM/PM shows ──
 reset();server.quiet_start='23:00';server.quiet_end='07:00';
 page=await newPage({width:320,locale:'en-US'});
 await page.goto(base+'/settings#notifications');
 const pick=page.locator('.quiet-hours input');
 await pick.first().waitFor();
 const [a,b]=[await pick.nth(0).boundingBox(),await pick.nth(1).boundingBox()];
 assert.ok(b.y>=a.y+a.height,`stacked at 320px (${JSON.stringify([a,b])})`);
 assert.ok(a.width>=150&&b.width>=150,`wide enough for 11:00 PM (${a.width}, ${b.width})`);
 assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=document.documentElement.clientWidth),'no sideways scroll at 320px');
 await page.locator('#notifications').screenshot({path:(process.env.SHOT_DIR||'/tmp')+'/alerts-320.png'}).catch(()=>{});
 await page.close();
 page=await newPage({locale:'en-US'});
 await page.goto(base+'/settings#notifications');
 await page.locator('.quiet-hours input').first().waitFor();
 const [c,d]=[await page.locator('.quiet-hours input').nth(0).boundingBox(),await page.locator('.quiet-hours input').nth(1).boundingBox()];
 assert.equal(Math.round(c.y),Math.round(d.y),'side by side at 390px');
 await page.close();

 // ── An iPhone is told where the count goes while an animal stays ──
 reset();
 page=await newPage({userAgent:'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1'});
 await page.goto(base+'/settings#notifications');
 await page.getByText('On an iPhone, the count while it stays goes on in Recent below.').waitFor();
 await page.close();

 // ── D-19: turning alerts on asks for permission before anything is saved ──
 reset();server.enabled=false;
 page=await newPage();
 await page.goto(base+'/settings#notifications');
 await row(page,'Alerts').waitFor();
 put.plan=['slow'];
 await row(page,'Alerts').click();
 await page.getByText('On. This phone will get alerts.').waitFor({timeout:8000});
 const asked=(await page.evaluate(()=>window.__push)).find(e=>e[0]==='permission')[1];
 const saved=log.find(e=>e[0]==='put')[2];
 assert.ok(asked<=saved,'the prompt came straight from the tap, before the save');
 assert.deepEqual(server.subs,['https://push.example/new']);
 await page.close();

 // ── K-07: an alert tapped the next morning opens its photo among its burst ──
 reset();
 const old=new Date(Date.now()-10*3600e3);
 const feedPhotos=[
  ...Array.from({length:60},(_,i)=>({image_id:`new${i}`,file_url:`/api/images/new${i}/file`,captured_at:new Date(Date.now()-(i+1)*60e3).toISOString(),camera:'Charca',camera_id:'c1',label:'Wild boar',species_id:'wild_boar',group_size:1,notes_count:0})),
  ...Array.from({length:8},(_,i)=>({image_id:`old${i}`,file_url:`/api/images/old${i}/file`,captured_at:new Date(old.getTime()-i*20e3).toISOString(),camera:'Barranco',camera_id:'c2',label:'Wild boar',species_id:'wild_boar',group_size:1,notes_count:0})),
 ];
 page=await newPage({photoFeed:feedPhotos});
 await page.goto(base+`/photos?species=wild_boar&image=old1&at=${encodeURIComponent(feedPhotos[61].captured_at)}`);
 const box=page.locator('.ov[role="dialog"]').first();await box.waitFor();
 assert.equal(await box.getAttribute('aria-label'),'Barranco · Photo 1 of 6','the photo, with the frames before it');
 const asked2=log.filter(e=>e[0]==='photos').map(e=>new URLSearchParams(e[1]));
 assert.ok(asked2.some(q=>q.get('before')&&q.get('limit')==='6'&&q.get('species')==='wild_boar'),'asked for by its time');
 await page.getByRole('button',{name:'Next photo'}).click();
 assert.equal(await box.getAttribute('aria-label'),'Barranco · Photo 2 of 6','the burst can be swiped');
 await page.close();

 // ── G-23: Tonight doesn't say twice that PL19 went quiet ──
 page=await newPage();
 await page.goto(base+'/');
 const card=page.locator('section',{has:page.getByRole('heading',{name:'Alerts'})});
 await card.getByText('Charca battery low').waitFor();
 assert.equal(await card.getByText('PL19 quiet').count(),0,'the Changed line already says it');
 await page.getByText('PL19 has had nothing for 4 nights.').waitFor();
 await page.close();

 assert.deepEqual(errors,[]);
 console.log('alerts: ok');
 } finally { await browser.close() }
})().catch(e=>{console.error(e);process.exit(1)});
