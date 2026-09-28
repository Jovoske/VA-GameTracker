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
//   the app opens. Not sent for the next person if the phone is signed out first.
// - Signing in with a language picked on the sign-in page: it reaches the server before
//   the first page asks for anything (the server answers a signed-in person in the
//   language saved there), and if it lands late the page asks again.
// - Words that won't load: an error, and nothing kept. A save that hangs: the new
//   language is on screen at once and another can be picked meanwhile. A slow answer
//   about the person, asked for before a choice, doesn't switch the screen back.
// - Every page in each language at 320 px: the page never scrolls sideways and no
//   button, chip, tab or heading has words spilling out of it. The cameras are made
//   to report at 21:00 some nights back, the longest health words there are.
// If the server doesn't keep a language yet, /api/auth/me is answered here (the
// contract: GET has "language", PATCH takes {language}); if it does, it is used and
// the admin's language is put back to English at the end.
// Env: BASE_URL, GS_EMAIL, GS_PASSWORD (an admin; the dev seed's by default),
// GS_MEMBER_EMAIL, GS_MEMBER_PASSWORD (a second person), PLAYWRIGHT_MODULE, PW_CHANNEL.
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert=require('node:assert/strict');
(async()=>{
 const channel=process.env.PW_CHANNEL??'msedge',base=process.env.BASE_URL||'http://127.0.0.1:5173';
 const email=process.env.GS_EMAIL||'admin@gamesense.local',password=process.env.GS_PASSWORD||'changeme';
 const signIn=async(em,pw)=>{
  const r=await fetch(base+'/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:em,password:pw})});
  assert.equal(r.status,200,'sign in as '+em);
  return (await r.json()).access_token;
 };
 const token=await signIn(email,password);
 const memberEmail=process.env.GS_MEMBER_EMAIL||'member@gamesense.local',memberPassword=process.env.GS_MEMBER_PASSWORD||'changeme';
 const memberToken=await signIn(memberEmail,memberPassword);
 const setServer=(tok,language)=>fetch(base+'/api/auth/me',{method:'PATCH',headers:{'Content-Type':'application/json',Authorization:'Bearer '+tok},body:JSON.stringify({language})});
 const probe=await setServer(token,'en');
 const real=probe.status===200&&'language' in (await probe.json().catch(()=>({})));
 console.log(real?'the server keeps the language':'the server has no language yet: /api/auth/me is answered here');
 // Whether the server writes its own lines in five languages: its refusal to a caller
 // with no sign-in, asked for in Finnish.
 const refusal=async lang=>(await (await fetch(base+'/api/auth/me',{headers:{'Accept-Language':lang}})).json().catch(()=>({}))).detail;
 const speaks=real&&(await refusal('fi'))!==(await refusal('en'));
 console.log(speaks?'the server speaks five languages':'the server speaks English only: its own lines are not checked');
 const TONIGHT={en:'Tonight',fi:'Tänä yönä',sv:'I kväll',nb:'I kveld',es:'Esta noche'};
 const subOf=h=>{try{return JSON.parse(Buffer.from((h||'').replace(/^Bearer /,'').split('.')[1],'base64url').toString()).sub}catch{return null}};

 const browser=await chromium.launch({headless:true,...(channel?{channel}:{}),args:['--enable-unsafe-swiftshader']});
 const errors=[];
 // A phone. `patch`: how the server takes a language ('ok', 'offline', 'hang' until
 // state.release()); `slowMe`: the first "who am I" held this long.
 async function phone({tok=token,lang=null,server='en',patch='ok',slowMe=0,w=390,h=844}={}){
  const ctx=await browser.newContext({viewport:{width:w,height:h},serviceWorkers:'block',hasTouch:true,isMobile:true,timezoneId:'Europe/Madrid',locale:'en-GB'});
  // Once per phone: a reload keeps what the app itself stored.
  await ctx.addInitScript(([t,l])=>{if(sessionStorage.getItem('seeded'))return;sessionStorage.setItem('seeded','1');
   if(t)localStorage.setItem('gs_token',t);if(l)localStorage.setItem('gs_lang',l)},[tok,lang]);
  const state={server,patches:[],langs:[],log:[],patch,held:[],meAsked:0,meAnswered:null};
  let answered;state.meAnswered=new Promise(r=>answered=r);
  state.release=()=>{state.patch='ok';state.held.splice(0).forEach(go=>go())};
  if(real)await setServer(tok||token,server);
  await ctx.route('**/api/auth/me',async route=>{
   const req=route.request();
   if(req.method()==='PATCH'){
    const body=JSON.parse(req.postData()||'{}');
    state.patches.push({...body,who:subOf(req.headers()['authorization']),at:Date.now()});
    state.log.push('PATCH '+body.language);
    if(state.patch==='offline')return route.abort('internetdisconnected');
    if(state.patch==='hang')await new Promise(go=>state.held.push(go));
    if(!real){
     state.server=body.language;
     return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({email,role:'admin',language:state.server})});
    }
    return route.continue().catch(()=>{});
   }
   const first=state.meAsked++===0;
   if(first&&slowMe)await new Promise(r=>setTimeout(r,slowMe));
   const res=await route.fetch().catch(()=>null);
   if(!res)return;
   const body=await res.json().catch(()=>null);
   if(first)setTimeout(answered,50);
   if(real||!body)return route.fulfill({response:res,...(body?{json:body}:{})}).catch(()=>{});
   return route.fulfill({response:res,json:{...body,language:state.server}}).catch(()=>{});
  });
  const page=await ctx.newPage();
  page.on('pageerror',e=>errors.push(e.message));
  // What the app asks for itself (photos are the browser's own requests).
  page.on('request',q=>{
   if(!['fetch','xhr'].includes(q.resourceType())||!q.url().includes('/api/'))return;
   const path=new URL(q.url()).pathname;
   if(!path.startsWith('/api/auth/'))state.langs.push(q.headers()['accept-language']);
   if(q.method()==='GET')state.log.push('GET '+path);
  });
  return {ctx,page,state};
 }
 // Requests still on their way when a phone is put down are let go quietly.
 const shut=async ctx=>{await ctx.unrouteAll({behavior:'ignoreErrors'});await ctx.close()};
 const tab=page=>page.locator('.tabbar .tab-label').first().innerText();
 // The phone's language, and the one it still has to send (whoever it is for).
 const stored=page=>page.evaluate(()=>{const p=localStorage.getItem('gs_lang_pending');let code=p;try{code=JSON.parse(p).code}catch{}return [localStorage.getItem('gs_lang'),code??null]});
 const serverLang=async(tok=token)=>real?(await (await fetch(base+'/api/auth/me',{headers:{Authorization:'Bearer '+tok}})).json()).language:null;
 const tonightText=page=>page.locator('main').innerText().catch(()=>'');
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
   const firstPlan=state.log.findIndex(x=>x.startsWith('GET /api/forecast'));
   assert.ok(firstPlan<0||state.log.indexOf('PATCH sv')<firstPlan,'the language went before the plan was asked for: '+state.log.join(', '));
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
  // Signing in with Suomi picked on the sign-in page, as someone whose server language is
  // English: the first plan on screen is already in Finnish, the server's lines too.
  {
   const {ctx,page,state}=await phone({tok:null,lang:'en',server:'en'});
   if(real)await setServer(memberToken,'en');
   await page.goto(base+'/login');
   await page.locator('.lang-switch select').selectOption('fi');
   await page.locator('button.btn',{hasText:'Kirjaudu'}).waitFor();
   await page.fill('#login-email',memberEmail);await page.fill('#login-password',memberPassword);
   await page.locator('button.btn').click();
   await page.locator('.tabbar .tab-label',{hasText:'Tänä yönä'}).first().waitFor();
   await page.waitForTimeout(1500);
   const firstPlan=state.log.findIndex(x=>x.startsWith('GET /api/forecast'));
   assert.ok(state.log.indexOf('PATCH fi')>=0&&(firstPlan<0||state.log.indexOf('PATCH fi')<firstPlan),'Suomi reached the server before the plan was asked for: '+state.log.join(', '));
   if(real)assert.equal(await serverLang(memberToken),'fi');
   if(speaks){
    await page.waitForFunction(()=>/Villisika/.test(document.querySelector('main')?.innerText||''),null,{timeout:15000});
    assert.ok(!/Wild boar|Red deer/.test(await tonightText(page)),'no English animal names on Tonight: '+(await tonightText(page)).slice(0,300));
   }
   await shut(ctx);
   if(real)await setServer(memberToken,'en');
  }
  // The same, with the server slow to take it (past the few seconds signing in waits):
  // the plan comes in English first, and is asked for again once Suomi lands.
  {
   const {ctx,page,state}=await phone({tok:null,lang:'en',server:'en',patch:'hang'});
   if(real)await setServer(memberToken,'en');
   await page.goto(base+'/login');
   await page.locator('.lang-switch select').selectOption('fi');
   await page.fill('#login-email',memberEmail);await page.fill('#login-password',memberPassword);
   await page.locator('button.btn',{hasText:'Kirjaudu'}).click();
   await page.locator('.tabbar .tab-label',{hasText:'Tänä yönä'}).first().waitFor({timeout:10000});
   await page.waitForTimeout(1000);
   const before=state.log.filter(x=>x.startsWith('GET /api/forecast/tonight')).length;
   assert.ok(before>0,'the plan was asked for while Suomi was on its way: '+state.log.join(', '));
   const at=state.log.length;
   state.release();
   await page.waitForFunction(()=>!localStorage.getItem('gs_lang_pending'),null,{timeout:10000});
   await page.waitForTimeout(1500);
   assert.ok(state.log.slice(at).some(x=>x.startsWith('GET /api/forecast/tonight')),'asked again once the server had Suomi: '+state.log.slice(at).join(', '));
   if(speaks){
    await page.waitForFunction(()=>/Villisika/.test(document.querySelector('main')?.innerText||''),null,{timeout:15000});
    assert.ok(!/Wild boar|Red deer/.test(await tonightText(page)),'no English animal names left: '+(await tonightText(page)).slice(0,300));
   }
   await shut(ctx);
   if(real)await setServer(memberToken,'en');
  }
  // Chosen with no signal, then signed out: the next person to sign in on this phone
  // doesn't get it written to their account.
  {
   const {ctx,page,state}=await phone({lang:'en',server:'en',patch:'offline'});
   if(real)await setServer(memberToken,'en');
   await page.goto(base+'/settings#language');
   await page.getByRole('radio',{name:'Español'}).click();
   await page.getByText('Guardado en este móvil. El servidor lo recibirá cuando haya cobertura.').waitFor({timeout:20000});
   assert.deepEqual(await stored(page),['es','es']);
   page.once('dialog',d=>d.accept());
   await page.locator('main').getByRole('button',{name:'Salir'}).click();
   await page.locator('#login-email').waitFor();
   assert.deepEqual(await stored(page),['es',null],'the phone keeps its language, not the choice to send');
   state.patch='ok';state.patches.length=0;
   await page.fill('#login-email',memberEmail);await page.fill('#login-password',memberPassword);
   await page.locator('button.btn').click();
   await page.locator('.tabbar .tab-label').first().waitFor();
   await page.waitForTimeout(2000);
   assert.deepEqual(state.patches.map(x=>x.language),[],'nothing sent for the member: '+JSON.stringify(state.patches));
   if(real)assert.equal(await serverLang(memberToken),'en','the member is still English on the server');
   if(real)assert.equal(await tab(page),'Tonight','the phone follows the member');
   await shut(ctx);
  }
  // A language whose words won't load: said so, and nothing kept to switch to later.
  {
   const {ctx,page}=await phone({lang:'en',server:'en'});
   const words=u=>/\/src\/i18n\/fi\.ts$|\/assets\/fi-[\w-]+\.js$/.test(u.pathname);
   await page.route(words,r=>r.abort('internetdisconnected'));
   await page.goto(base+'/settings#language');
   await page.getByRole('radio',{name:'Suomi'}).click();
   await page.getByText('That language didn’t load. No signal? Try again when you have a connection.').waitFor({timeout:20000});
   assert.equal(await tab(page),'Tonight');
   assert.equal(await page.evaluate(()=>document.documentElement.lang),'en');
   assert.deepEqual(await stored(page),['en',null],'nothing kept');
   assert.equal(await page.getByRole('radio',{name:'English'}).getAttribute('aria-checked'),'true');
   // Signal back: the same tap works, without opening the app again (a browser keeps
   // a failed file failed; the app asks for it afresh).
   await page.unroute(words);
   await page.getByRole('radio',{name:'Suomi'}).click();
   await page.getByText('Tallennettu. Kaikki puhelimesi käyttävät tätä kieltä.').waitFor({timeout:20000});
   assert.deepEqual(await stored(page),['fi',null]);
   await shut(ctx);
  }
  // Saving to a server that hangs: the language shows at once, the rows stay open, and
  // a mis-tap is put right at once; the last one chosen is what the server keeps.
  {
   const {ctx,page,state}=await phone({lang:'en',server:'en',patch:'hang'});
   await page.goto(base+'/settings#language');
   await page.getByRole('radio',{name:'Svenska'}).click();
   await page.locator('.tabbar .tab-label',{hasText:'I kväll'}).first().waitFor({timeout:3000});
   await page.getByText('Sparar…').waitFor({timeout:3000});
   assert.equal(await page.locator('.lang-rows button:disabled').count(),0,'the rows stay open while it saves');
   await page.getByRole('radio',{name:'Norsk (bokmål)'}).click();
   await page.locator('.tabbar .tab-label',{hasText:'I kveld'}).first().waitFor({timeout:3000});
   state.release();
   await page.getByText('Lagret. Alle telefoner du logger inn på bruker det.').waitFor({timeout:20000});
   assert.deepEqual(await stored(page),['nb',null]);
   assert.equal(state.patches.at(-1).language,'nb');
   if(real)assert.equal(await serverLang(),'nb');
   await shut(ctx);
  }
  // A slow answer about the person, asked for before Suomi was chosen: it says English,
  // and the screen stays Finnish.
  {
   const {ctx,page,state}=await phone({lang:'en',server:'en',slowMe:5000});
   await page.goto(base+'/settings#language');
   await page.getByRole('radio',{name:'Suomi'}).click();
   await page.getByText('Tallennettu. Kaikki puhelimesi käyttävät tätä kieltä.').waitFor({timeout:20000});
   await state.meAnswered;
   await page.waitForTimeout(800);
   assert.equal(await tab(page),'Tänä yönä','not switched back by the slow answer');
   assert.equal(await page.evaluate(()=>document.documentElement.lang),'fi');
   assert.deepEqual(await stored(page),['fi',null]);
   if(real)assert.equal(await serverLang(),'fi');
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
  // 21:00 in Madrid `back` nights ago: a camera last heard from then reads "Quiet since
  // Wednesday night", "Sin movimiento desde la noche del miércoles", whatever the hour now.
  const madrid=new Intl.DateTimeFormat('en-CA',{timeZone:'Europe/Madrid',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',hourCycle:'h23',weekday:'short'});
  const at21=back=>{
   const day=madrid.formatToParts(new Date(Date.now()-back*864e5)).reduce((o,p)=>({...o,[p.type]:p.value}),{});
   for(const off of ['+01:00','+02:00']){const t=new Date(`${day.year}-${day.month}-${day.day}T21:00:00${off}`);if(madrid.formatToParts(t).find(p=>p.type==='hour').value==='21')return {iso:t.toISOString(),weekday:day.weekday}}
  };
  const nights=[2,3,4,5,6].map(at21);
  const wednesday=nights.find(n=>n.weekday==='Wed')||nights[0];
  const quiet=[{status:'offline',...nights[1]},{status:'offline',...wednesday},{status:'quiet',...nights[4]}];
  for(const lang of ['en','fi','sv','nb','es']){
   const {ctx,page,state}=await phone({lang,server:lang,w:320,h:568});
   await ctx.route(u=>u.pathname==='/api/cameras',async route=>{
    const res=await route.fetch().catch(()=>null);
    if(!res)return;
    const body=await res.json().catch(()=>null);
    if(!Array.isArray(body))return route.fulfill({response:res});
    body.forEach((c,i)=>{const q=quiet[i];if(q){c.health={...(c.health||{}),status:q.status};c.last_report_at=q.iso}});
    return route.fulfill({response:res,json:body});
   });
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
  console.log('PASS: switching at once, saved to the phone and the server, the sign-in switch (sent before the first plan, asked again when late), a new phone following the person, a choice made with no signal and not handed to the next person, words that won\'t load, a save that hangs, a slow answer that doesn\'t switch back, and every page in five languages at 320 px');
 } finally {
  if(real)await Promise.all([setServer(token,'en'),setServer(memberToken,'en')]);
  await browser.close();
 }
})().catch(e=>{console.error(e);process.exit(1)});
