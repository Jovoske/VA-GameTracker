// Photos paging and "Wrong?" in the photo viewer, against fixtures: every frame of a
// burst stamped one second is reached across a page break (the page ends at a photo,
// not a moment), a chip tapped while an older page is on its way never leaves "Show
// older photos" stuck on "Loading…", the viewer carries on past the last loaded photo
// ("Photo 3 of 3+"), and says so at once when that page can't come (no signal), with
// Try again; a member fixes a species (Undo puts back what the AI said) or marks a
// false alarm, which leaves the list when the viewer closes; the rest of a burst
// follows a fix and its Undo; viewers see no "Wrong?". Run like map-and-stands.cjs
// (BASE_URL, PW_CHANNEL).
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert=require('node:assert/strict');
(async()=>{
 const channel=process.env.PW_CHANNEL??'msedge',base=process.env.BASE_URL||'http://127.0.0.1:5173';
 const browser=await chromium.launch({headless:true,...(channel?{channel}:{}),args:['--enable-unsafe-swiftshader']});
 const errors=[];
 try {
 const tile=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==','base64');
 const photo='<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="900"><rect width="1600" height="900" fill="#394b3b"/></svg>';
 const ago=m=>new Date(Date.now()-m*60e3).toISOString().replace(/\.\d+Z$/,'Z');
 // Nine photos, newest first; p3..p5 are one burst stamped the same second, and the
 // first page of three ends inside it.
 const burst=ago(40);
 const all=Array.from({length:9},(_,i)=>({image_id:`p${i+1}`,file_url:`/api/images/p${i+1}/file`,
  captured_at:i>=2&&i<=4?burst:ago(10+i*10),camera:'Charca',camera_id:'c1',label:i%2?'Red deer':'Wild boar',
  species_id:i%2?'red_deer':'wild_boar',group_size:1,notes_count:0,fixed_by:null}));
 const choices=[['wild_boar','Wild boar',1],['red_deer','Red deer',1],['roe_deer','Roe deer',1],['fallow_deer','Fallow deer',1],
  ['mouflon','Mouflon',1],['ibex','Ibex',1],['fox','Fox',0],['lagomorph','Hare or rabbit',0],['badger','Badger',0],['genet','Genet',0],['micromammal','Mouse or rat',0]]
  .map(([id,name,big],i)=>({id,name,hidden:false,big_game:!!big,likely:i<9,seen:i<9?5:0}));
 let role='member',slowOlder=0,offlineOlder=false;const writes=[];
 const newPage=async()=>{
  const page=await browser.newPage({viewport:{width:390,height:844},serviceWorkers:'block',hasTouch:true,timezoneId:'Europe/Madrid',locale:'en-GB'});
  await page.addInitScript(()=>localStorage.setItem('gs_token','photo-fixes-fixture'));
  page.on('pageerror',e=>errors.push(e.message));
  await page.route(/ign\.es|catastro\.meh\.es|arcgisonline/,r=>r.fulfill({contentType:'image/png',body:tile}));
  await page.route('**/api/**',async route=>{
   const req=route.request(),u=new URL(req.url()),method=req.method(),path=u.pathname;
   if(/\/api\/images\/[^/]+\/thumb$/.test(path))return route.fulfill({contentType:'image/png',body:tile});
   if(/\/api\/images\/[^/]+\/file$/.test(path))return route.fulfill({contentType:'image/svg+xml',body:photo});
   const fix=path.match(/^\/api\/images\/([^/]+)\/(species|flag)$/);
   if(fix){
    const p=all.find(x=>x.image_id===fix[1]);writes.push({id:fix[1],what:fix[2],method,body:req.postDataJSON?.()??null});
    if(fix[2]==='flag'){const b=req.postDataJSON();p.empty=b.is_empty;return route.fulfill({json:{id:p.image_id,is_empty_frame:b.is_empty,reviewed:true}})}
    // As the server does: the frames of the burst that read as the fixed one did follow
    // the fix (`visit`), and go back with its Undo.
    const shown=x=>({...x,hidden:false,empty:false});let visit=[];
    if(method==='DELETE'){Object.assign(p,{label:p.ai_label??p.label,species_id:p.ai_species??p.species_id,fixed_by:null});
     visit=all.filter(x=>x.followed===p.image_id).map(x=>{Object.assign(x,{label:x.ai_label,species_id:x.ai_species,followed:null});return shown(x)})}
    else{const c=choices.find(x=>x.id===req.postDataJSON().species_id),was=p.species_id;p.ai_label??=p.label;p.ai_species??=p.species_id;Object.assign(p,{label:c.name,species_id:c.id,fixed_by:'Me'});
     visit=all.filter(x=>x!==p&&!x.empty&&x.captured_at===p.captured_at&&x.species_id===was).map(x=>{x.ai_label??=x.label;x.ai_species??=x.species_id;Object.assign(x,{label:c.name,species_id:c.id,followed:p.image_id});return shown(x)})}
    return route.fulfill({json:{...shown(p),visit}});
   }
   if(path==='/api/photos'){
    const species=u.searchParams.get('species'),limit=+u.searchParams.get('limit')||60;
    const before=u.searchParams.get('before'),bid=u.searchParams.get('before_id');
    let rows=all.filter(p=>!p.empty&&(!species||species.split(',').includes(p.species_id)));
    // Newest first by (time, id), as the server orders it; the cursor is the last photo.
    rows.sort((a,b)=>b.captured_at.localeCompare(a.captured_at)||b.image_id.localeCompare(a.image_id));
    if(before)rows=rows.filter(p=>p.captured_at<before||(p.captured_at===before&&(bid?p.image_id<bid:false)));
    if(before&&slowOlder)await new Promise(r=>setTimeout(r,slowOlder));
    if(before&&offlineOlder)return route.abort('internetdisconnected');
    const page=rows.slice(0,Math.min(limit,3)),more=rows.length>page.length,last=page.at(-1);
    return route.fulfill({json:{items:page,next_before:more?last.captured_at:null,next_before_id:more?last.image_id:null}});
   }
   const result=path==='/api/auth/me'?{id:'me',email:'me@x.es',role}
    :path==='/api/photos/filters'?{species:[{id:'wild_boar',common_name:'Wild boar',count:5},{id:'red_deer',common_name:'Red deer',count:4}],cameras:[]}
    :path==='/api/photos/highlights'?{items:[]}
    :path==='/api/species/choices'?choices:undefined;
   if(path.startsWith('/api/images/')&&path.endsWith('/notes'))return route.fulfill({json:{image_id:'x',can_add:role!=='viewer',notes:[]}});
   return result===undefined?route.fulfill({status:404,json:{detail:'Not Found'}}):route.fulfill({json:result});
  });
  return page;
 };
 const ids=async page=>(await page.locator('.photos-tile img').evaluateAll(els=>els.map(e=>/images\/([^/]+)\/thumb/.exec(e.getAttribute('src'))[1])));
 const label=page=>page.locator('.ov[role="dialog"]').first().getAttribute('aria-label');

 // ── Every frame of the burst, across the page break ──
 let page=await newPage();
 await page.goto(base+'/photos');
 await page.locator('.photos-tile').first().waitFor();
 // The list fills as it scrolls (a short page asks for the next by itself), or with the button.
 for(let i=0;i<20&&(await ids(page)).length<9;i++){await page.locator('.photos-more').click({timeout:500}).catch(()=>{});await page.waitForTimeout(150)}
 const order=[...all].sort((a,b)=>b.captured_at.localeCompare(a.captured_at)||b.image_id.localeCompare(a.image_id));
 assert.deepEqual(await ids(page),order.map(p=>p.image_id),'all nine, the burst whole, in order');

 // ── A chip tapped while an older page is on its way ──
 slowOlder=2500;
 await page.reload();await page.locator('.photos-tile').first().waitFor();
 // The short page asks for the next by itself (or the button does): it is on its way.
 await page.locator('.photos-more').click({timeout:500}).catch(()=>{});
 await page.waitForFunction(()=>document.querySelector('.photos-more')?.textContent==='Loading…');
 await page.locator('.photos-chip',{hasText:'Red deer'}).click();
 await page.waitForTimeout(3000);slowOlder=0;
 // The deer list pages on (by itself, or with the button), never stuck on "Loading…",
 // and the slow boar page never lands in it.
 for(let i=0;i<20&&(await page.locator('.photos-tile').count())<4;i++){await page.locator('.photos-more').click({timeout:500}).catch(()=>{});await page.waitForTimeout(150)}
 assert.equal(await page.locator('.photos-tile').count(),4,'all four deer photos');
 assert.ok((await page.locator('.photos-tile-label').allInnerTexts()).every(l=>l==='Red deer'),'the slow boar page never landed in the deer list');
 assert.equal(await page.locator('.photos-more').count(),0,'no "Loading…" left behind');
 await page.locator('.photos-chip',{hasText:'Everything'}).click();

 // ── The viewer carries on past the last loaded photo ──
 // The next page is slow to come: the viewer opened on the last loaded photo says
 // there are more, and Next waits for them rather than stopping at "3 of 3".
 slowOlder=1500;
 await page.reload();await page.locator('.photos-tile').nth(2).click();
 assert.match(await label(page),/Photo 3 of 3\+$/);
 await page.locator('.lb-nav--next').click();
 slowOlder=0;
 await page.waitForFunction(()=>/Photo 4 of \d+\+?$/.test(document.querySelector('.ov[role="dialog"]').getAttribute('aria-label')));
 assert.equal(await page.locator('.lb-caption [data-label]').innerText(),'Red deer');

 // ── Wrong? → Fox, Undo, then Nothing here ──
 await page.getByRole('button',{name:'Wrong animal? Fix it'}).click();
 const sheet=page.locator('.lb-fix');
 await sheet.locator('[data-species="red_deer"][aria-pressed="true"]').waitFor();
 assert.equal(await sheet.locator('[data-species="genet"]').count(),0,'the unlikely ones wait behind More animals');
 await sheet.getByRole('button',{name:/More animals \(2\)/}).click();
 assert.equal(await sheet.locator('[data-species="micromammal"]').innerText(),'Mouse or rat');
 await sheet.locator('[data-species="fox"]').click();
 await page.locator('.lb-toast').waitFor();
 assert.equal(await page.locator('.lb-caption [data-label]').innerText(),'Fox');
 assert.equal(await page.locator('.lb-fixed-by').innerText(),'fixed by Me');
 assert.deepEqual(writes.at(-1),{id:'p4',what:'species',method:'POST',body:{species_id:'fox'}});
 await page.locator('.lb-toast').getByRole('button',{name:'Undo'}).click();
 await page.waitForFunction(()=>!document.querySelector('.lb-toast'));
 assert.equal(await page.locator('.lb-caption [data-label]').innerText(),'Red deer');
 assert.equal(writes.at(-1).method,'DELETE','Undo puts back what the AI said');
 await page.getByRole('button',{name:'Wrong animal? Fix it'}).click();
 await sheet.locator('.lb-fix-nothing').click();
 await page.locator('.lb-toast').waitFor();
 assert.deepEqual(writes.at(-1),{id:'p4',what:'flag',method:'POST',body:{is_empty:true}});
 assert.equal((await ids(page)).includes('p4'),true,'nothing moves under the open viewer');
 await page.keyboard.press('Escape');
 await page.waitForFunction(()=>![...document.querySelectorAll('.photos-tile img')].some(i=>i.getAttribute('src').includes('/p4/')));

 // ── A burst is one animal: the rest of the visit follows a fix, and its Undo ──
 // p5 and p3 are the burst's two boar frames (p4 went as a false alarm).
 await page.locator('.photos-tile').nth(2).click();
 assert.equal(await page.locator('.lb-caption [data-label]').innerText(),'Wild boar');
 await page.getByRole('button',{name:'Wrong animal? Fix it'}).click();
 await sheet.locator('[data-species="fox"]').click();
 await page.locator('.lb-toast').waitFor();
 assert.equal(await page.locator('.lb-toast span').innerText(),'Changed to Fox, with the other photo of this visit.');
 assert.deepEqual((await page.locator('.photos-tile-label').allInnerTexts()).slice(2,4),['Fox','Fox'],'both tiles say Fox at once');
 await page.locator('.lb-nav--next').click();
 assert.equal(await page.locator('.lb-caption [data-label]').innerText(),'Fox','the next frame of the visit reads Fox too');
 assert.equal(await page.locator('.lb-fixed-by').count(),0,'it followed the fix; nobody fixed it');
 await page.locator('.lb-nav--prev').click();
 await page.locator('.lb-toast').getByRole('button',{name:'Undo'}).click();
 await page.waitForFunction(()=>!document.querySelector('.lb-toast'));
 await page.locator('.lb-nav--next').click();
 assert.equal(await page.locator('.lb-caption [data-label]').innerText(),'Wild boar','Undo put the rest of the visit back');
 await page.keyboard.press('Escape');
 await page.close();

 // ── No signal at the end of what is loaded: said at once, with Try again ──
 page=await newPage();offlineOlder=true;
 await page.goto(base+'/photos');await page.locator('.photos-tile').nth(2).click();
 assert.match(await label(page),/Photo 3 of 3\+$/);
 await page.locator('.lb-nav--next').click();
 const said=page.locator('.lb-more-err');
 await said.waitFor({timeout:3000});
 assert.match(await said.innerText(),/No signal, so older photos didn’t load\./);
 assert.equal(await page.locator('.lb-status--more').count(),0,'not "Loading older photos…" on a dead signal');
 assert.equal(await page.locator('.lb-nav--next').isEnabled(),true,'Next works again');
 offlineOlder=false;
 await said.getByRole('button',{name:'Try again'}).click();
 await page.waitForFunction(()=>/Photo 4 of \d+\+?$/.test(document.querySelector('.ov[role="dialog"]').getAttribute('aria-label')));
 assert.equal(await page.locator('.lb-more-err').count(),0);
 await page.close();

 // ── Viewers look ──
 role='viewer';page=await newPage();
 await page.goto(base+'/photos');await page.locator('.photos-tile').first().click();
 await page.locator('.lb-caption').waitFor();await page.waitForTimeout(500);
 assert.equal(await page.getByRole('button',{name:'Wrong animal? Fix it'}).count(),0);
 await page.close();
 assert.deepEqual(errors,[]);
 console.log('PASS: a burst across a page break, a chip during a slow older page, the viewer past the loaded end (and no signal there, said at once), Wrong? with Undo and Nothing here, a burst following a fix and its Undo, viewers only look.');
 } finally { await browser.close() }
})().catch(e=>{console.error(e);process.exit(1)});
