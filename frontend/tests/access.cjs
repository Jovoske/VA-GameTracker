// Access and security (plan item 12) against the REAL server, like sit-reports-live.cjs:
// - A fresh phone's sign-in page has no email in it (it used to offer the admin's);
//   after a sign-in it offers the last email used on this phone, and the phone keeps
//   its known-phone mark through sign-out and sends it with the next sign-in.
// - No request the app makes carries the sign-in in its address: photos carry a photo
//   pass (scope img), on every page.
// - A member and a viewer see none of the admin controls on Settings, Cameras and
//   Animals, and the app asks the server nothing it refuses them (no 403, no 4xx at
//   all); an admin sees them (so the checks look for the right things). A viewer is
//   told new photos come every 15 minutes instead of a Check button.
// - A photo with no pass, or with one that ran out, loads again once with a fresh one.
// - Removing a person who reserved a stand tonight works (no 500), and their sign-in
//   stops working. A camera login a removed person added says so, with its Remove
//   (glove-sized). No login can be added here (that asks SPYPOINT), so that one row
//   is added to the server's list on its way to the page.
// For a dev stack only: it signs in as an admin and adds a member and a guest named
// access-*@estate.local; the member stays in that database. Viewers can't be added in
// the app, so it signs in as one that exists (the dev seed's by default).
// Env: BASE_URL (the web app, which passes /api to the server), GS_EMAIL and
// GS_PASSWORD (an admin), GS_VIEWER and GS_VIEWER_PASSWORD (a viewer); defaults the
// dev seed's. PLAYWRIGHT_MODULE, PW_CHANNEL.
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert=require('node:assert/strict');
(async()=>{
 const channel=process.env.PW_CHANNEL??'msedge',base=process.env.BASE_URL||'http://127.0.0.1:5173';
 const email=process.env.GS_EMAIL||'admin@gamesense.local',password=process.env.GS_PASSWORD||'changeme';
 const signIn=async(e,p)=>{const r=await fetch(base+'/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:e,password:p})});
  assert.equal(r.status,200,`sign in as ${e}`);return (await r.json()).access_token};
 const admin=await signIn(email,password);
 const call=async(tok,path,method='GET',body)=>{const r=await fetch(base+'/api'+path,{method,headers:{'Content-Type':'application/json',Authorization:'Bearer '+tok},...(body?{body:JSON.stringify(body)}:{})});
  const text=await r.text();return {status:r.status,body:text?JSON.parse(text):null}};
 const stamp=Date.now().toString(36),pw='access-check-'+stamp;
 const person=async name=>{const e=`access-${name}-${stamp}@estate.local`;const r=await call(admin,'/users','POST',{email:e,password:pw,role:'member'});
  assert.equal(r.status,200,`add ${e}: ${JSON.stringify(r.body)}`);return {id:r.body.id,email:e}};
 const member=await person('member'),guest=await person('guest');
 const viewer={email:process.env.GS_VIEWER||'viewer@gamesense.local',password:process.env.GS_VIEWER_PASSWORD||'changeme'};
 const claims=t=>JSON.parse(Buffer.from(t.split('.')[1],'base64url').toString());
 const tile=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==','base64');

 const browser=await chromium.launch({headless:true,...(channel?{channel}:{}),args:['--enable-unsafe-swiftshader']});
 const errors=[];
 // A phone: every request and every refusal it gets, base-map tiles stubbed, and
 // Settings with its sections open.
 const openAll=()=>{for(const k of['advice','accounts','people','password','version'])localStorage.setItem('gs.settings.open.'+k,'1')};
 const phone=async(token)=>{
  const ctx=await browser.newContext({viewport:{width:390,height:844},serviceWorkers:'block',hasTouch:true,isMobile:true,timezoneId:'Europe/Madrid',locale:'en-GB'});
  await ctx.addInitScript(openAll);
  if(token)await ctx.addInitScript(t=>{if(!localStorage.getItem('gs_token'))localStorage.setItem('gs_token',t)},token);
  await ctx.route(/ign\.es|catastro\.meh\.es|arcgisonline|open-meteo/,r=>r.fulfill({contentType:'image/png',body:tile}));
  const page=await ctx.newPage(),seen={urls:[],refused:[],images:[]};
  page.on('pageerror',e=>errors.push(e.message));
  page.on('dialog',d=>d.accept());
  page.on('request',r=>{seen.urls.push(r.url());if(r.url().includes('/api/images/'))seen.images.push(r.url())});
  page.on('response',r=>{if(r.url().includes('/api/')&&r.status()>=400)seen.refused.push(`${r.status()} ${r.request().method()} ${new URL(r.url()).pathname}`)});
  return {ctx,page,seen};
 };
 const photosLoaded=(page,n)=>page.waitForFunction(k=>[...document.querySelectorAll('img')].filter(i=>i.src.includes('/api/images/')&&i.complete&&i.naturalWidth>0).length>=k,n,{timeout:30000});
 const visit=async(page,path,ready)=>{await page.goto(base+path);if(ready)await page.locator(ready).first().waitFor({timeout:20000});await page.waitForTimeout(1200)};
 try {
 // ── The sign-in page on a fresh phone, and what a sign-in leaves on it ──
 {
  const {ctx,page}=await phone(null);
  await page.goto(base+'/login');await page.locator('#login-email').waitFor();
  assert.equal(await page.inputValue('#login-email'),'','a fresh phone offers no email, the admin’s least of all');
  const typed=member.email.replace('access','Access');
  await page.fill('#login-email',typed);await page.fill('#login-password',pw);
  const sent=page.waitForRequest(r=>r.url().endsWith('/api/auth/login'));
  await page.getByRole('button',{name:'Sign in'}).click();
  assert.equal((await sent).postDataJSON().known_phone,null,'a fresh phone has no mark to send');
  await page.waitForURL(u=>!u.pathname.startsWith('/login'),{timeout:20000});
  const kept=await page.evaluate(()=>({email:localStorage.getItem('gs_last_email'),mark:localStorage.getItem('gs_phone'),pass:localStorage.getItem('gs_img')}));
  assert.equal(kept.email,typed);assert.equal(claims(kept.mark).scope,'phone');assert.equal(claims(kept.pass).scope,'img');
  await visit(page,'/settings','text=Signed in as');
  await page.getByRole('button',{name:'Sign out'}).click();await page.waitForURL(/\/login/);
  assert.equal(await page.inputValue('#login-email'),typed,'the last email used on this phone, nothing else');
  assert.equal(await page.evaluate(()=>localStorage.getItem('gs_phone')),kept.mark,'the mark belongs to the phone, not the sign-in');
  await page.fill('#login-password',pw);
  const again=page.waitForRequest(r=>r.url().endsWith('/api/auth/login'));
  await page.getByRole('button',{name:'Sign in'}).click();
  assert.equal((await again).postDataJSON().known_phone,kept.mark,'and it goes with the next sign-in');
  await page.waitForURL(u=>!u.pathname.startsWith('/login'),{timeout:20000});
  await ctx.close();
 }

 // ── A member, a viewer, an admin: what each is offered, and asked for ──
 const pages={settings:['/settings','text=Signed in as'],cameras:['/cameras','.cam-card, .status-panel'],animals:['/animals','summary:has-text("Named animals")']};
 const offered=async page=>{
  await visit(page,...pages.settings);
  const settings=await page.textContent('main')||await page.textContent('body');
  const s={version:/App version/.test(settings),checking:/Photo checking/.test(settings),people:/Who can sign in/.test(settings),
   hide:await page.locator('button[aria-label^="Hide "]').count(),switches:await page.locator('#advice [role=switch], [data-section=advice] [role=switch]').count(),
   readonly:await page.locator('[data-readonly=advice]').count(),addLogin:await page.locator('#camera-email').count()};
  await visit(page,...pages.cameras);
  const c={check:await page.locator('.cam-sync-btn').count(),viewerNote:(await page.locator('[data-viewer-sync]').allTextContents()).join(''),retire:await page.getByText('Retire camera').count()};
  await visit(page,...pages.animals);await page.click('summary:has-text("Named animals")');await page.waitForTimeout(500);
  const a={repeats:await page.getByRole('button',{name:'Look for repeats'}).count(),note:(await page.locator('.an-fold-note').textContent()||'').trim()};
  return {...s,...c,...a};
 };
 for(const [who,tok] of [['member',await signIn(member.email,pw)],['viewer',await signIn(viewer.email,viewer.password)]]){
  const {ctx,page,seen}=await phone(tok);
  await visit(page,'/photos');await photosLoaded(page,3);
  await visit(page,'/','main');await visit(page,'/map','.maplibregl-canvas');
  const got=await offered(page);
  assert.deepEqual({version:got.version,checking:got.checking,people:got.people,hide:got.hide,switches:got.switches,retire:got.retire,repeats:got.repeats},
   {version:false,checking:false,people:false,hide:0,switches:0,retire:0,repeats:0},`${who}: no admin controls`);
  assert.equal(got.readonly,1,`${who}: the animals say why they can't be changed`);
  assert.match(got.note,/Only an admin can merge or confirm them/);
  if(who==='member'){assert.equal(got.check,1,'a member may ask for new photos');assert.equal(got.addLogin,1,'and add a camera login')}
  else{assert.equal(got.check,0);assert.equal(got.viewerNote,'New photos come in every 15 minutes.');assert.equal(got.addLogin,0,'a viewer adds no camera login')}
  assert.deepEqual(seen.refused,[],`${who}: the app asked nothing the server refuses`);
  // The sign-in never rides in an address; photos carry a photo pass.
  const token=await page.evaluate(()=>localStorage.getItem('gs_token'));
  assert.ok(seen.urls.length>20&&seen.urls.every(u=>!u.includes(token)),`${who}: no address carries the sign-in`);
  const passes=seen.images.map(u=>new URL(u).searchParams.get('token')).filter(Boolean);
  assert.ok(passes.length>0&&passes.every(t=>claims(t).scope==='img'),`${who}: photos carry a photo pass`);
  await ctx.close();
 }
 {
  const {ctx,page,seen}=await phone(admin);
  const got=await offered(page);
  assert.ok(got.version&&got.people&&got.hide>0&&got.switches>0&&got.retire>0&&got.repeats===1&&got.readonly===0,'an admin sees them: '+JSON.stringify(got));
  assert.deepEqual(seen.refused,[]);
  await ctx.close();
 }

 // ── A photo with no pass, or one that ran out, loads again once with a fresh one ──
 {
  const {ctx,page,seen}=await phone(await signIn(member.email,pw));
  await ctx.addInitScript(()=>localStorage.removeItem('gs_img'));
  await visit(page,'/photos');await photosLoaded(page,6);
  const broken=await page.$$eval('img',els=>els.filter(e=>e.src.includes('/api/images/')&&e.complete&&e.naturalWidth===0).length);
  assert.equal(broken,0,'no broken photo with no pass to start with');
  const tries={};for(const u of seen.images){const p=new URL(u).pathname;tries[p]=(tries[p]||0)+1}
  assert.ok(Object.values(tries).every(n=>n<=2),'each photo asked at most twice: '+JSON.stringify(tries));
  // A pass that ran out while the page sat in a pocket, on a photo already on screen.
  const id=new URL(seen.images[0]).pathname.split('/')[3];
  const expired=['e30',Buffer.from(JSON.stringify({scope:'img',exp:Math.floor(Date.now()/1000)-60})).toString('base64url'),'x'].join('.');
  const healed=await page.evaluate(({id,expired})=>new Promise(res=>{
   const img=document.createElement('img');let failed=false;
   img.addEventListener('error',()=>{failed=true});
   img.onload=()=>res({ok:img.naturalWidth>0,failed,src:img.getAttribute('src')});
   setTimeout(()=>res({ok:false,failed,src:img.getAttribute('src')}),15000);
   img.src=`/api/images/${id}/thumb?token=${expired}`;document.body.appendChild(img)}),{id,expired});
  assert.ok(healed.ok&&!healed.failed,'the old pass is swapped for a fresh one, and the page never sees the failure: '+JSON.stringify(healed));
  assert.equal(claims(new URL(healed.src,base).searchParams.get('token')).scope,'img');
  await ctx.close();
 }

 // ── Removing a person who reserved a stand tonight ──
 {
  const guestTok=await signIn(guest.email,pw);
  const stands=(await call(admin,'/stands')).body;
  const free=stands.find(s=>!s.claimed_tonight);
  if(free){const r=await call(guestTok,'/sits','POST',{stand_id:free.id});assert.ok(r.status<300,'the guest reserves a stand: '+JSON.stringify(r.body))}
  const {ctx,page,seen}=await phone(admin);
  await visit(page,'/settings','text=Signed in as');
  await page.locator(`button[aria-label="Remove ${guest.email}"]`).click();
  await page.waitForFunction(()=>/can't sign in any more|can’t sign in any more/.test(document.body.textContent||''),null,{timeout:15000});
  assert.equal((await call(guestTok,'/auth/me')).status,401,'their sign-in stops working');
  assert.deepEqual(seen.refused,[],'no refusal, no 500');
  await ctx.close();
 }

 // ── A camera login added by someone since removed ──
 {
  const {ctx,page}=await phone(admin);
  const now=new Date().toISOString();
  await page.route('**/api/camera-accounts',async route=>{
   if(route.request().method()!=='GET')return route.continue();
   const rows=await (await route.fetch()).json();
   rows.push({id:'removed-owners-login',label:'pedro@spypoint.es',username:'pedro@spypoint.es',provider:'spypoint',owner:email,added_by_removed:'pedro.garcia@gmail.com',
    active:true,primary:false,cameras:2,importing:false,last_sync_at:now,can_remove:true,can_edit:true,
    status:{state:'ok',error:null,last_ok_at:now,last_attempt_at:now,password_problem:false,cameras_failing:0,camera_error:null},
    ubox_min_interval_seconds:null,ubox_max_images_per_day:null,last_import:null});
   await route.fulfill({json:rows});
  });
  await visit(page,'/settings','[data-removed-owner]');
  const marker=(await page.locator('[data-login="removed-owners-login"] [data-removed-owner]').textContent()).trim();
  assert.equal(marker,`Added by pedro.garcia@gmail.com, who was removed. It still fetches photos; ${email} looks after it now.`);
  const remove=page.getByRole('button',{name:'Remove pedro@spypoint.es'});
  assert.ok((await remove.boundingBox()).height>=44,'its Remove is glove-sized');
  await ctx.close();
 }
 assert.deepEqual(errors,[],'no errors on any page');
 console.log('access: all checks passed');
 } finally { await browser.close() }
})().catch(e=>{console.error(e);process.exit(1)});
