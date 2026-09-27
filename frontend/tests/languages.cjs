// The app in five languages (English, Suomi, Svenska, Norsk (bokmål), Español), against
// the REAL server like access.cjs:
// - Settings > Language changes every word at once, no reload: the tab bar, the page,
//   <html lang>. The choice is kept on this phone and saved to the person on the server
//   (PATCH /api/auth/me {language}); every request after it asks for that language
//   (Accept-Language), so the server's own words come back in it.
// - The sign-in page's small switch works before signing in, and signing in sends the
//   choice to the server.
// - A phone that has never chosen follows what the person chose on another phone.
// - Chosen with no signal: on screen at once, kept on the phone, sent the next time
//   the app opens.
// - Every page in each language at 320 px: the page never scrolls sideways and no
//   button, chip, tab or heading has words spilling out of it.
// If the server doesn't keep a language yet, /api/auth/me is answered here (the
// contract: GET has "language", PATCH takes {language}); if it does, it is used and
// the admin's language is put back to English at the end.
// Env: BASE_URL, GS_EMAIL, GS_PASSWORD (an admin; the dev seed's by default),
// PLAYWRIGHT_MODULE, PW_CHANNEL.
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert=require('node:assert/strict');
(async()=>{
 const channel=process.env.PW_CHANNEL??'msedge',base=process.env.BASE_URL||'http://127.0.0.1:5173';
 const email=process.env.GS_EMAIL||'admin@gamesense.local',password=process.env.GS_PASSWORD||'changeme';
 const r=await fetch(base+'/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email,password})});
 assert.equal(r.status,200,'sign in');
 const token=(await r.json()).access_token;
 const probe=await fetch(base+'/api/auth/me',{method:'PATCH',headers:{'Content-Type':'application/json',Authorization:'Bearer '+token},body:JSON.stringify({language:'en'})});
 const real=probe.status===200&&'language' in (await probe.json().catch(()=>({})));
 console.log(real?'the server keeps the language':'the server has no language yet: /api/auth/me is answered here');
 const TONIGHT={en:'Tonight',fi:'Tänä yönä',sv:'I kväll',nb:'I kveld',es:'Esta noche'};

 const browser=await chromium.launch({headless:true,...(channel?{channel}:{}),args:['--enable-unsafe-swiftshader']});
 const errors=[];
 async function phone({tok=token,lang=null,server='en',patch='ok',w=390,h=844}={}){
  const ctx=await browser.newContext({viewport:{width:w,height:h},serviceWorkers:'block',hasTouch:true,isMobile:true,timezoneId:'Europe/Madrid',locale:'en-GB'});
  // Once per phone: a reload keeps what the app itself stored.
  await ctx.addInitScript(([t,l])=>{if(sessionStorage.getItem('seeded'))return;sessionStorage.setItem('seeded','1');
   if(t)localStorage.setItem('gs_token',t);if(l)localStorage.setItem('gs_lang',l)},[tok,lang]);
  const state={server,patches:[],langs:[],patch};
  if(!real){
   await ctx.route('**/api/auth/me',async route=>{
    const req=route.request();
    if(req.method()==='PATCH'){
     state.patches.push(JSON.parse(req.postData()||'{}'));
     if(state.patch==='offline')return route.abort('internetdisconnected');
     state.server=state.patches.at(-1).language;
     return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({email,role:'admin',language:state.server})});
    }
    const res=await route.fetch();const body=await res.json().catch(()=>null);
    return body?route.fulfill({response:res,json:{...body,language:state.server}}):route.fulfill({response:res});
   });
  } else {
   await fetch(base+'/api/auth/me',{method:'PATCH',headers:{'Content-Type':'application/json',Authorization:'Bearer '+token},body:JSON.stringify({language:server})});
   await ctx.route('**/api/auth/me',async route=>{
    const req=route.request();
    if(req.method()==='PATCH'){state.patches.push(JSON.parse(req.postData()||'{}'));if(state.patch==='offline')return route.abort('internetdisconnected')}
    return route.continue();
   });
  }
  const page=await ctx.newPage();
  page.on('pageerror',e=>errors.push(e.message));
  // What the app asks for itself (photos are the browser's own requests).
  page.on('request',q=>{if(['fetch','xhr'].includes(q.resourceType())&&q.url().includes('/api/')&&!q.url().includes('/auth/'))state.langs.push(q.headers()['accept-language'])});
  return {ctx,page,state};
 }
 // Requests still on their way when a phone is put down are let go quietly.
 const shut=async ctx=>{await ctx.unrouteAll({behavior:'ignoreErrors'});await ctx.close()};
 const tab=page=>page.locator('.tabbar .tab-label').first().innerText();
 const stored=page=>page.evaluate(()=>[localStorage.getItem('gs_lang'),localStorage.getItem('gs_lang_pending')]);
 const serverLang=async()=>real?(await (await fetch(base+'/api/auth/me',{headers:{Authorization:'Bearer '+token}})).json()).language:null;
 try {
  // Settings > Language: Suomi, at once, saved to both.
  {
   const {ctx,page,state}=await phone({lang:'en'});
   await page.goto(base+'/settings#language');
   await page.getByRole('radio',{name:'English'}).waitFor();
   assert.equal(await tab(page),'Tonight');
   await page.getByRole('radio',{name:'Suomi'}).click();
   await page.getByText('Tallennettu. Kaikki puhelimesi käyttävät tätä kieltä.').waitFor();
   assert.equal(await tab(page),'Tänä yönä','the tab bar changed with no reload');
   assert.equal(await page.locator('h1').first().innerText(),'Asetukset');
   assert.equal(await page.evaluate(()=>document.documentElement.lang),'fi');
   assert.equal(await page.getByRole('radio',{name:'Suomi'}).getAttribute('aria-checked'),'true');
   assert.ok(state.patches.length>0&&state.patches.every(x=>x.language==='fi'),'only Finnish sent: '+JSON.stringify(state.patches));
   assert.deepEqual(await stored(page),['fi',null]);
   if(real)assert.equal(await serverLang(),'fi');
   state.langs.length=0;
   await page.locator('.tabbar').getByRole('link',{name:'Passit'}).click();
   await page.locator('h1',{hasText:'Passit'}).waitFor();
   await page.waitForTimeout(800);
   assert.ok(state.langs.length>0&&state.langs.every(l=>l==='fi'),'every request asks for Finnish: '+state.langs.join(','));
   await page.reload();
   await page.locator('h1',{hasText:'Passit'}).waitFor();
   assert.equal(await tab(page),'Tänä yönä','kept through a reload');
   await shut(ctx);
  }
  // The sign-in page's switch, then signing in sends it.
  {
   const {ctx,page,state}=await phone({tok:null});
   await page.goto(base+'/login');
   await page.locator('button.btn',{hasText:'Sign in'}).waitFor();
   await page.locator('.lang-switch select').selectOption('sv');
   await page.locator('button.btn',{hasText:'Logga in'}).waitFor();
   assert.equal(await page.locator('label[for=login-password]').innerText(),'Lösenord');
   assert.equal(await page.evaluate(()=>document.documentElement.lang),'sv');
   assert.deepEqual(await stored(page),['sv','sv'],'kept, and marked to send once signed in');
   await page.fill('#login-email',email);await page.fill('#login-password',password);
   await page.locator('button.btn').click();
   await page.locator('.tabbar .tab-label',{hasText:'I kväll'}).first().waitFor();
   await page.waitForTimeout(800);
   assert.ok(state.patches.length>0&&state.patches.every(x=>x.language==='sv'),'sent on signing in: '+JSON.stringify(state.patches));
   assert.deepEqual(await stored(page),['sv',null]);
   if(real)assert.equal(await serverLang(),'sv');
   await shut(ctx);
  }
  // A phone that never chose follows the person.
  {
   const {ctx,page,state}=await phone({server:'nb'});
   await page.goto(base+'/');
   await page.locator('.tabbar .tab-label',{hasText:'I kveld'}).first().waitFor();
   assert.deepEqual(await stored(page),['nb',null]);
   assert.equal(state.patches.length,0,'nothing sent back');
   await shut(ctx);
  }
  // No signal when choosing.
  {
   const {ctx,page,state}=await phone({lang:'en',server:'en',patch:'offline'});
   await page.goto(base+'/settings#language');
   await page.getByRole('radio',{name:'Español'}).click();
   await page.getByText('Guardado en este móvil. El servidor lo recibirá cuando haya cobertura.').waitFor({timeout:20000});
   assert.equal(await tab(page),'Esta noche');
   assert.deepEqual(await stored(page),['es','es']);
   state.patch='ok';
   await page.reload();
   await page.locator('.tabbar .tab-label',{hasText:'Esta noche'}).first().waitFor();
   await page.waitForTimeout(1500);
   assert.deepEqual(await stored(page),['es',null],'sent when the app opened again');
   assert.equal(state.patches.at(-1).language,'es');
   if(real)assert.equal(await serverLang(),'es');
   await shut(ctx);
  }
  // Every page, every language, 320 px: nothing spills.
  const spills=vw=>{
   const out=[];
   if(innerWidth>vw+1||document.documentElement.scrollWidth>vw+1)out.push(`the page is ${Math.max(innerWidth,document.documentElement.scrollWidth)} px wide`);
   const scrolls=el=>{for(let p=el.parentElement;p;p=p.parentElement){const o=getComputedStyle(p).overflowX;if(o==='auto'||o==='scroll')return true}return false};
   for(const el of document.querySelectorAll('button, a, select, summary, [role=radio], .tab-label, h1, h2, h3, .bsheet, .more-menu')){
    const st=getComputedStyle(el),r=el.getBoundingClientRect();
    // Map pins carry their count badge outside their box on purpose; screen-reader-only text has no box.
    if(st.display==='inline'||r.width<=2||st.textOverflow==='ellipsis'||scrolls(el)||el.closest('.maplibregl-marker, .maplibregl-ctrl, .sr-only'))continue;
    if(el.scrollWidth>el.clientWidth+1)out.push(`${el.tagName.toLowerCase()} "${el.innerText.trim().slice(0,40)}" ${el.scrollWidth}>${el.clientWidth}`);
   }
   return out;
  };
  for(const lang of ['en','fi','sv','nb','es']){
   const {ctx,page,state}=await phone({lang,server:lang,w:320,h:568});
   for(const path of ['/','/photos','/stands','/cameras','/map','/insights','/animals','/settings']){
    await page.goto(base+path);
    await page.locator('.tabbar .tab-label',{hasText:TONIGHT[lang]}).first().waitFor();
    await page.waitForTimeout(path==='/map'?2500:1500);
    assert.equal(await page.evaluate(()=>document.documentElement.lang),lang);
    assert.deepEqual(await page.evaluate(spills,320),[],`${lang} ${path} at 320 px`);
    if(lang!=='en')assert.ok(await page.locator('.tab-more-btn').isVisible(),`${lang}: Cameras, Insights and Settings under More`);
   }
   await page.goto(base+'/login');
   await page.evaluate(()=>localStorage.removeItem('gs_token'));
   await page.reload();
   await page.locator('.lang-switch select').waitFor();
   assert.deepEqual(await page.evaluate(spills,320),[],`${lang} sign-in page at 320 px`);
   assert.ok(state.langs.every(l=>l===lang),`${lang}: requests ask for ${lang}: ${[...new Set(state.langs)]}`);
   await shut(ctx);
  }
  assert.deepEqual(errors,[]);
  console.log('PASS: switching at once, saved to the phone and the server, the sign-in switch, a new phone following the person, a choice made with no signal, and every page in five languages at 320 px');
 } finally {
  if(real)await fetch(base+'/api/auth/me',{method:'PATCH',headers:{'Content-Type':'application/json',Authorization:'Bearer '+token},body:JSON.stringify({language:'en'})});
  await browser.close();
 }
})().catch(e=>{console.error(e);process.exit(1)});
