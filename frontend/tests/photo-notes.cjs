// "Worth a look" and the per-camera alerts, against fixtures: the Photos strip (who said
// it and when), the note sheet holding the viewer still (no paging, swiping, Back or a
// stray tap throws a typed note away), a save that loses its answer on a weak signal
// (the same note id on the next try), a photo marked "nothing in it" kept by its note,
// viewers reading only, the notes beside the photo on a phone held sideways, and the
// camera sheet (a note on any frame of a burst marks its tile, a 44px Settings link).
// Run like map-and-stands.cjs (BASE_URL, PW_CHANNEL).
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert=require('node:assert/strict');
(async()=>{
 const channel=process.env.PW_CHANNEL??'msedge',base=process.env.BASE_URL||'http://127.0.0.1:5173';
 const browser=await chromium.launch({headless:true,...(channel?{channel}:{}),args:['--enable-unsafe-swiftshader']});
 const errors=[];
 try {
 const tile=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==','base64');
 const photo='<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="900"><rect width="1600" height="900" fill="#394b3b"/></svg>';
 const ago=h=>new Date(Date.now()-h*3600e3).toISOString();
 // Charca: five photos, the newest three a burst stamped the same second.
 const burst=ago(2);
 const feed=['p1','p2','p3','p4','p5'].map((id,i)=>({image_id:id,file_url:`/api/images/${id}/file`,captured_at:i<3?burst:ago(3+i),camera:'Charca',camera_id:'c1',label:'Wild boar',species_id:'wild_boar',group_size:1,notes_count:0}));
 const pedro=(id,image,text,h)=>({id,image_id:image,text,name:'Pedro',created_at:ago(h),mine:false,can_remove:false});
 // Pedro's note is on the burst's second frame, the one that shows the boar.
 const notes={p2:[pedro('n1','p2','Big boar, third night running',1)]};
 feed[1].notes_count=1;
 const highlight=id=>({...feed.find(p=>p.image_id===id),notes_count:notes[id].length,notes:notes[id],marked_at:notes[id].at(-1).created_at});
 let role='member',post='ok';const posts=[];
 const camera={id:'cam1',name:'Barranco Norte',battery_pct:72,signal_pct:60,model:'Trail camera',image_count:3,empty_count:1,last_capture:ago(1),last_report_at:ago(1),photo_limit:null,photo_count:null,health:null};
 const camImgs=[{id:'e1',captured_at:ago(1),file_url:'/api/images/e1/file',species:null,group_type:null,group_size:null,sex:null,is_empty_frame:true,reviewed:false,animal_conf:0.08,notes_count:0},
  {id:'k1',captured_at:ago(2),file_url:'/api/images/k1/file',species:'Red Deer',group_type:'solitary',group_size:1,sex:'unknown',is_empty_frame:false,reviewed:false,animal_conf:0.9,notes_count:0}];
 const ok={status:'ok',detail:'Reporting normally',producing:true,hours_since_report:1};
 const mapCams=[{id:'c1',name:'Charca',lat:39.0951,lon:-1.3622,battery_pct:80,signal_pct:60,last_report_at:ago(1),health:ok,can_rename:false,latest:{image_id:'p1',captured_at:burst,species_id:'wild_boar',label:'Wild boar'},new_count:0,last_night:[],last_night_status:'watched',alerts:true,alerts_enabled:false}];
 const tonight={conditions:{wind_dir_deg:315,wind_speed_kmh:12},airflow:{source:'synoptic',wind_dir_deg:315,wind_speed_kmh:12},zones:[],stands:[],safe_ground:{status:'ok',cells:[]},routes:[],scent_range_m:320,terrain_loaded:true};
 const newPage=async(viewport)=>{
  const page=await browser.newPage({viewport,serviceWorkers:'block',hasTouch:true,timezoneId:'Europe/Madrid',locale:'en-GB'});
  await page.addInitScript(()=>localStorage.setItem('gs_token','photo-notes-fixture'));
  page.on('pageerror',e=>errors.push(e.message));
  await page.route(/ign\.es|catastro\.meh\.es|arcgisonline/,r=>r.fulfill({contentType:'image/png',body:tile}));
  await page.route('**/api/**',async route=>{
   const req=route.request(),u=new URL(req.url()),method=req.method();
   if(/\/api\/images\/[^/]+\/thumb$/.test(u.pathname))return route.fulfill({contentType:'image/png',body:tile});
   if(/\/api\/images\/[^/]+\/file$/.test(u.pathname))return route.fulfill({contentType:'image/svg+xml',body:photo});
   const m=u.pathname.match(/^\/api\/images\/([^/]+)\/notes$/);
   if(m&&method==='POST'){
    const b=req.postDataJSON(),id=m[1];posts.push({image:id,...b});
    if(post==='empty409'&&!b.keep)return route.fulfill({status:409,json:{detail:'This photo is marked “nothing in it”. Keep it as an animal photo first.'}});
    const note={id:b.id,image_id:id,text:b.text,name:'Me',created_at:new Date().toISOString(),mine:true,can_remove:true};
    if(post==='drop')return route.abort('internetdisconnected');
    (notes[id]??=[]).push(note);
    if(post==='landedDrop')return route.abort('internetdisconnected');
    const c=camImgs.find(x=>x.id===id);if(c&&b.keep){c.is_empty_frame=false;c.reviewed=true}
    return route.fulfill({status:201,json:{note,image_id:id,can_add:true,notes:notes[id],told:b.tell_team?2:0,kept:!!b.keep,again:false}});
   }
   if(method==='POST')return route.fulfill({json:{}});
   if(m)return route.fulfill({json:{image_id:m[1],can_add:role!=='viewer',notes:notes[m[1]]??[]}});
   const result=u.pathname==='/api/auth/me'?{id:'me',email:'me@x.es',role}
    :u.pathname==='/api/photos/filters'?{species:[],cameras:[]}
    :u.pathname==='/api/photos/highlights'?{items:Object.keys(notes).filter(id=>feed.some(p=>p.image_id===id)).map(highlight)}
    :u.pathname==='/api/photos'?{items:feed.map(p=>({...p,notes_count:(notes[p.image_id]??[]).length})),next_before:null}
    :u.pathname==='/api/cameras'?[camera]
    :u.pathname==='/api/cameras/cam1/images'?(u.searchParams.get('include_empty')==='true'?camImgs:camImgs.filter(x=>!x.is_empty_frame))
    :u.pathname==='/api/map/cameras'?mapCams:u.pathname==='/api/map/tonight'?tonight:undefined;
   return result===undefined?route.fulfill({status:404,json:{detail:'Not Found'}}):route.fulfill({json:result});
  });
  return page;
 };
 const label=page=>page.locator('.ov[role="dialog"]').first().getAttribute('aria-label');
 const sheet=page=>page.locator('.lb-sheet');

 // ── Photos: the strip says what was said, who said it and when ──
 let page=await newPage({width:390,height:844});
 await page.goto(base+'/photos');
 const wal=page.locator('.wal-tile').first();await wal.waitFor();
 assert.equal(await wal.locator('.wal-note').innerText(),'Big boar, third night running');
 assert.match(await wal.locator('.wal-who').innerText(),/^Pedro · \d\d:\d\d$/,'the note’s author and time');
 assert.equal(await wal.locator('.wal-meta').innerText(),'Charca');
 assert.equal(await wal.locator('.wal-tag').innerText(),'Wild boar');
 const who=await wal.locator('.wal-who').evaluate(el=>el.scrollWidth<=el.clientWidth);
 assert.ok(who,'who and when fit the tile');

 // ── The sheet holds the viewer still ──
 await page.locator('.photos-tile').nth(3).click();
 await page.locator('.lb-worth').waitFor();
 assert.match(await label(page),/Photo 4 of 5$/);
 await page.locator('.lb-worth').click();
 const words='Big stag, left side, came in from the pines';
 await sheet(page).locator('textarea').fill(words);
 assert.equal(await page.getByRole('button',{name:'Next photo'}).isDisabled(),true,'no paging while writing');
 const asks=async why=>{await sheet(page).getByText('Throw away this note?').waitFor();assert.match(await label(page),/Photo 4 of 5$/,why);
  await sheet(page).getByRole('button',{name:'Keep writing'}).click();assert.equal(await sheet(page).locator('textarea').inputValue(),words,why)};
 // A tap where the › arrow is, a swipe across the photo, a tap on the dark band above it.
 const next=await page.getByRole('button',{name:'Next photo'}).boundingBox();
 await page.mouse.click(next.x+next.width/2,next.y+next.height/2);await asks('a tap on the arrow');
 const st=await page.locator('.lb-stage').boundingBox();
 await page.mouse.move(st.x+st.width-40,st.y+st.height/2);await page.mouse.down();for(let i=1;i<=8;i++)await page.mouse.move(st.x+st.width-40-i*30,st.y+st.height/2);await page.mouse.up();
 await asks('a swipe on the photo');
 await page.mouse.click(4,80);await asks('a tap above the photo');
 await page.goBack();await asks('the phone’s Back');
 await sheet(page).locator('textarea').press('ArrowRight');
 await page.keyboard.press('Escape');await asks('Escape');
 assert.equal(await page.locator('.ov[role="dialog"]').count(),1,'the viewer is still open');

 // ── A save that loses its answer ──
 post='drop';
 await sheet(page).getByRole('button',{name:'Save'}).click();
 await sheet(page).getByText('It didn’t save. Your note is still here; try again.').waitFor();
 assert.equal(await sheet(page).locator('textarea').inputValue(),words);
 post='ok';
 await sheet(page).getByRole('button',{name:'Save'}).click();
 await page.locator('.lb-notes-said').getByText('Marked worth a look.').waitFor();
 assert.equal(await sheet(page).count(),0);
 assert.equal(posts.length,2);
 assert.equal(posts[0].id,posts[1].id,'the second try is the same note');
 assert.match(posts[0].id,/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
 assert.match(await page.locator('.lb-note-text').first().innerText(),/^Me · \d\d:\d\d · Big stag/);
 // Saved, the sheet's step is off the history: Back now closes the photo.
 await page.goBack();await page.waitForTimeout(400);
 assert.equal(await page.locator('.ov[role="dialog"]').count(),0,'Back closes the viewer after a save');

 // It landed, only the answer was lost: found, not saved twice.
 await page.locator('.photos-tile').nth(4).click();await page.locator('.lb-worth').click();
 post='landedDrop';
 await sheet(page).getByRole('button',{name:'Save'}).click();
 await page.locator('.lb-notes-said').getByText(/The answer was slow, but it saved/).waitFor();
 assert.equal(posts.length,3);
 post='ok';
 await page.getByRole('button',{name:/Back to photos/}).click();await page.waitForTimeout(300);
 assert.equal(await page.locator('.ov[role="dialog"]').count(),0);

 // ── Nothing in it: a note keeps the photo ──
 await page.goto(base+'/cameras');
 await page.getByRole('button',{name:/Show 1 empty photo/}).click();
 await page.getByRole('button',{name:'Open photo from Barranco Norte: no animal'}).click();
 await page.locator('.lb-notes-quiet').getByText(/Marked “nothing in it”/).waitFor();
 await page.locator('.lb-worth').click();
 await sheet(page).getByText(/Saving keeps it as an animal photo/).waitFor();
 await sheet(page).locator('textarea').fill('Deer in the back, detector missed it');
 await sheet(page).getByRole('button',{name:'Keep it and save'}).click();
 await page.locator('.lb-notes-said').getByText('Kept as an animal photo and marked worth a look.').waitFor();
 assert.equal(posts.at(-1).keep,true);
 assert.equal(await page.locator('.lb-caption span').first().innerText(),'Animal');
 // A photo the page didn't know was empty: the server says so, and the sheet offers to keep it.
 await page.getByRole('button',{name:'Next photo'}).click();
 post='empty409';
 await page.locator('.lb-worth').click();
 await sheet(page).getByRole('button',{name:'Save'}).click();
 await sheet(page).getByText(/Save again to keep it as an animal photo/).waitFor();
 await sheet(page).getByRole('button',{name:'Keep it and save'}).click();
 await page.locator('.lb-notes-said').getByText(/^Kept as an animal photo/).waitFor();
 assert.equal(posts.at(-1).keep,true);
 post='ok';
 await page.getByRole('button',{name:/Back to cameras/}).click();await page.waitForTimeout(300);
 assert.equal(await page.locator('.cam-thumb[aria-label^="Open photo from Barranco Norte"]').first().evaluate(el=>getComputedStyle(el).opacity),'1','the kept photo is no longer dimmed');
 await page.close();

 // ── Viewers read the notes and get no button ──
 role='viewer';
 page=await newPage({width:390,height:844});
 await page.goto(base+'/photos');await page.locator('.photos-tile').nth(1).click();
 await page.locator('.lb-note').first().waitFor();
 assert.equal(await page.locator('.lb-worth').count(),0);
 await page.close();role='member';

 // ── A phone on its side: the notes go beside the photo ──
 page=await newPage({width:844,height:390});
 await page.goto(base+'/photos');await page.locator('.photos-tile').first().click();
 await page.locator('.lb-worth').waitFor();await page.waitForTimeout(400);
 const stage=await page.locator('.lb-stage').boundingBox(),band=await page.locator('.lb-notes').boundingBox(),arrow=await page.getByRole('button',{name:'Next photo'}).boundingBox();
 assert.ok(stage.height>=280,`the photo keeps the height (${stage.height})`);
 assert.ok(band.x>=stage.x+stage.width,'notes beside the photo');
 assert.ok(arrow.x+arrow.width<=band.x,'the arrow stays on the photo, off the notes');
 await page.close();
 // Upright nothing moved: the stage is the phone's width, the notes under it.
 page=await newPage({width:390,height:844});
 await page.goto(base+'/photos');await page.locator('.photos-tile').first().click();await page.locator('.lb-worth').waitFor();await page.waitForTimeout(400);
 const up=await page.locator('.lb-stage').boundingBox(),under=await page.locator('.lb-notes').boundingBox(),worth=await page.locator('.lb-worth').boundingBox();
 assert.ok(Math.abs(up.width-390*0.94)<2&&under.y>=up.y+up.height,`upright: full width, notes under (${JSON.stringify([up,under])})`);
 assert.ok(worth.y+worth.height<=844,'Worth a look is on screen');
 await page.close();

 // ── The camera's sheet ──
 page=await newPage({width:390,height:844});
 await page.goto(base+'/map?camera=c1');
 await page.locator('.bsheet[aria-label="Camera: Charca"]').waitFor();
 const burstTile=page.locator('.cam-strip-tile').first();await burstTile.waitFor();
 assert.match(await burstTile.getAttribute('aria-label'),/3 frames/);
 assert.equal(await burstTile.locator('.note-mark').count(),1,'a note on the burst’s second frame marks its tile');
 const link=await page.getByRole('link',{name:'Turn them on in Settings'}).boundingBox();
 assert.ok(link.height>=44,`the Settings link is glove-sized (${link.height})`);
 const sheetWal=page.locator('.cam-sheet-wal .wal-tile').first();await sheetWal.waitFor();
 assert.equal(await sheetWal.locator('.wal-meta').count(),0,'no camera name on the camera’s own strip');
 assert.match(await sheetWal.locator('.wal-who').innerText(),/^Pedro · /);
 await page.close();

 assert.deepEqual(errors,[]);
 console.log('photo-notes: ok');
 } finally { await browser.close() }
})().catch(e=>{console.error(e);process.exit(1)});
