const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert=require('node:assert/strict'),fs=require('node:fs');
(async()=>{
 // PW_CHANNEL= (empty) uses the bundled Chromium; BASE_URL points at another dev server.
 const channel=process.env.PW_CHANNEL??'msedge',base=process.env.BASE_URL||'http://127.0.0.1:5173';
 const browser=await chromium.launch({headless:true,...(channel?{channel}:{}),args:['--enable-unsafe-swiftshader']});
 try {
 const page=await browser.newPage({viewport:{width:1280,height:1000},serviceWorkers:'block'});
 await page.addInitScript(()=>localStorage.setItem('gs_token','map-ux-fixture'));
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 const dialogs=[];page.on('dialog',d=>{dialogs.push(d.message());d.dismiss()});
 const stands=[{id:'s1',name:'Ridge overlook',lat:39.094,lon:-1.362,claimed_tonight:false,claimed_by:null},{id:'s2',name:'Oak hollow',lat:39.098,lon:-1.357,claimed_tonight:true,claimed_by:'me'},{id:'s3',name:'South track',lat:39.091,lon:-1.355,claimed_tonight:true,claimed_by:'other'}];
 const sits=[{id:'cancelled',stand_id:'s1',user_id:'me',outcome:'cancelled'},{id:'mine',stand_id:'s2',user_id:'me',outcome:'unreported',started_at:null,wind_text:'Saved wind check.'},{id:'other',stand_id:'s3',user_id:'other',outcome:'unreported',started_at:null}];
 // The track camera sits a few metres from South track: at estate zoom their pins overlap.
 // The map's cameras (GET /map/cameras): Valley has a photo, three of them new to you, and
 // last night in visits; Track has no photo yet.
 const ok={status:'ok',detail:'Reporting normally',producing:true,hours_since_report:1};
 const shotAt=new Date(Date.now()-3*3600e3).toISOString();
 const cameras=[{id:'c1',name:'Valley camera',lat:39.095,lon:-1.358,battery_pct:72,signal_pct:65,last_report_at:shotAt,health:ok,can_rename:true,latest:{image_id:'i1',captured_at:shotAt,species_id:'wild_boar',label:'Sounder'},new_count:3,last_night:[{species_id:'wild_boar',label:'Wild boar',visits:2},{species_id:'red_deer',label:'Red deer',visits:1}],last_night_watched:true},
  {id:'c2',name:'Track camera',lat:39.0911,lon:-1.3551,battery_pct:15,signal_pct:null,last_report_at:shotAt,health:{...ok,status:'low_battery'},can_rename:true,latest:null,new_count:0,last_night:[],last_night_watched:true}];
 const strip=[0,1,2].map(i=>({image_id:'i'+(i+1),file_url:`/api/images/i${i+1}/file`,captured_at:new Date(Date.now()-(3+i)*3600e3).toISOString(),camera:'Valley camera',camera_id:'c1',label:'Sounder',species_id:'wild_boar',group_size:4}));
 const writes=[],seen=[];
 const data=()=>({conditions:{wind_dir_deg:315,wind_speed_kmh:12},airflow:{source:'synoptic',wind_dir_deg:315,wind_speed_kmh:12},zones:[{id:'z1',name:'Pine cover',kind:'bedding',polygon:{type:'Polygon',coordinates:[[[-1.354,39.097],[-1.351,39.098],[-1.349,39.096],[-1.354,39.097]]]}}],stands:stands.map(s=>({...s,wind:{status:s.id==='s3'?'unknown':'clean',source:s.id==='s3'?'unknown':'synoptic',scent_bearing:135,speed_kmh:12,range_m:320,half_deg:22.5,text:'Estimated scent travels southeast, away from mapped bedding.'},approaches:[]})),safe_ground:{status:'ok',cells:[]},routes:[],scent_range_m:320,terrain_loaded:true});
 let offline=false;const images=[];
 const tile=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==','base64');
 await page.route('**/api/**',async route=>{
 const request=route.request(),u=new URL(request.url()),method=request.method();
 if(offline&&/\/api\/map\/(tonight|cameras)$/.test(u.pathname))return route.abort('internetdisconnected');
 if(/\/api\/images\/[^/]+\/(thumb|file)$/.test(u.pathname)){images.push(u.pathname);return route.fulfill({contentType:'image/png',body:tile})}
 // Opening a camera marks it seen: not an edit, so kept apart from the writes.
 if(method==='POST'&&/\/api\/cameras\/[^/]+\/seen$/.test(u.pathname)){seen.push(u.pathname);const c=cameras.find(x=>u.pathname.includes(x.id));if(c)c.new_count=0;return route.fulfill({json:{}})}
 if(method!=='GET'){
 const body=request.postDataJSON();writes.push({path:u.pathname,method,body});
 if(u.pathname==='/api/stands'){stands.push({id:'s4',...body,claimed_tonight:false,claimed_by:null});return route.fulfill({json:{id:'s4'}})}
 if(u.pathname==='/api/sits'){stands.find(s=>s.id===body.stand_id).claimed_tonight=true;stands.find(s=>s.id===body.stand_id).claimed_by='me';sits.push({id:'new',stand_id:body.stand_id,user_id:'me',outcome:'unreported',started_at:null});return route.fulfill({json:{id:'new'}})}
 if(u.pathname==='/api/sits/new'){sits.find(s=>s.id==='new').outcome=body.outcome;stands[0].claimed_tonight=false;stands[0].claimed_by=null;return route.fulfill({json:{}})}
 return route.fulfill({json:{}})
 }
 let result=u.pathname==='/api/map/tonight'?data():u.pathname==='/api/map/cameras'?cameras:u.pathname==='/api/photos'?{items:u.searchParams.get('cameras')==='c1'?strip:[],next_before:null}:u.pathname==='/api/auth/me'?{id:'me',role:'admin'}:u.pathname==='/api/stands'?stands:u.pathname==='/api/sits'?sits:undefined;
 if(result===undefined)return route.fulfill({status:404,json:{detail:'Not Found'}});
 await route.fulfill({json:result});
 });
 // Base-map tiles are stubbed: this checks the app's map, not whether IGN or Esri answer today.
 // `failing` takes a base down; `failOdd` fails every other column of the aerial tiles.
 const failing=new Set();let failOdd=false,tiles=0;
 await page.route(/ign\.es|catastro\.meh\.es|arcgisonline/,r=>{
 tiles++;const u=r.request().url(),kind=/catastro/.test(u)?'catastro':/pnoa/.test(u)?'aerial':/mapa-raster/.test(u)?'topo':'world';
 if(failing.has(kind)||(failOdd&&kind==='aerial'&&+(u.match(/tilecol=(\d+)/)||[])[1]%2===1))return r.fulfill({status:500,body:'down'});
 return r.fulfill({contentType:'image/png',body:tile})});
 const ready=async()=>{await page.waitForFunction(()=>window.__gsMap&&window.__gsMap.loaded()&&document.querySelectorAll('.map-pin').length>0,null,{timeout:20000});await page.waitForTimeout(300)};
 const count=src=>page.evaluate(async s=>(await window.__gsMap.getSource(s).getData()).features.length,src);
 const vis=id=>page.evaluate(i=>window.__gsMap.getLayoutProperty(i,'visibility')??'visible',id);
 const pill=()=>page.locator('.map-notices .map-pill');
 await page.goto(base+'/map');
 await page.getByRole('button',{name:'Stand: Ridge overlook',exact:true}).waitFor({timeout:20000});
 await page.waitForLoadState('networkidle');assert.ok(tiles>0,'MapLibre asked for base tiles');
 await page.getByText('From the north-west',{exact:true}).waitFor();
 await page.getByRole('button',{name:'Stand: Ridge overlook',exact:true}).click();await page.locator('.bsheet').getByRole('heading',{name:'Ridge overlook'}).waitFor();
 assert.equal(writes.length,0,'Selecting markers must not write');
 await page.getByRole('button',{name:'Map type, layers and tools',exact:true}).click();const safe=page.getByRole('switch',{name:'Scent-safe ground'});await safe.click();assert.equal(await safe.getAttribute('aria-checked'),'true');await safe.click();await page.keyboard.press('Escape');
 if(process.env.UX_SCREENSHOTS){fs.mkdirSync(process.env.UX_SCREENSHOTS,{recursive:true});await page.screenshot({path:process.env.UX_SCREENSHOTS+'/map-desktop.png',fullPage:true})}

 // B-01/I-11: a base tile error raises the banner; Try again asks for tiles and nothing else.
 await ready();const layers={bedding:await count('bedding'),wind:await count('wind'),pins:await page.locator('.map-pin').count()};
 assert.deepEqual(layers,{bedding:1,wind:2,pins:5});
 failing.add('aerial');await page.evaluate(()=>window.__gsMap.panBy([1500,0],{duration:0}));
 await page.getByText('Part of the map picture didn’t load. Your stands and cameras are still on it.').waitFor({timeout:10000});
 assert.equal(await vis('base-aerial'),'visible','some aerial loaded before, so this is a gap, not a reason to switch');
 failing.delete('aerial');const before=tiles;await pill().getByRole('button',{name:'Try again'}).click();
 await page.waitForFunction(()=>!document.body.innerText.includes('Part of the map picture didn’t load'),null,{timeout:10000});
 for(let i=0;i<50&&tiles<=before;i++)await page.waitForTimeout(100);
 assert.ok(tiles>before,'Try again asked for the tiles again');await ready();await page.waitForTimeout(500);
 assert.equal(await pill().count(),0,'and the banner stays gone once they load');assert.equal(await page.locator('.map-loading').count(),0,'no stuck Loading map');
 assert.deepEqual({bedding:await count('bedding'),wind:await count('wind'),pins:await page.locator('.map-pin').count()},layers,'every layer is still there');
 // S1-m1: a base that half works stays; one where nothing gets through falls back to Esri, says so, and can be tried again.
 failOdd=true;await page.reload();await ready();await page.waitForTimeout(1200);
 assert.equal(await vis('base-aerial'),'visible','a partial failure does not switch the base');failOdd=false;
 failing.add('aerial');await page.reload();await ready();
 await page.getByText('Aerial isn’t loading, so this is Aerial (world).').waitFor({timeout:10000});
 assert.equal(await vis('base-world'),'visible');assert.equal(await vis('base-aerial'),'none');
 assert.equal(await count('bedding'),1,'the fallback keeps the drawn layers');
 failing.delete('aerial');await pill().getByRole('button',{name:'Try again'}).click();await page.waitForTimeout(800);
 assert.equal(await vis('base-aerial'),'visible');assert.equal(await pill().count(),0);

 await page.setViewportSize({width:390,height:844});await page.reload();await page.getByRole('button',{name:'Stand: Ridge overlook',exact:true}).waitFor();await page.waitForLoadState('networkidle');await page.getByRole('button',{name:'Stand: Ridge overlook',exact:true}).click();await page.waitForTimeout(1000);
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
 if(process.env.UX_SCREENSHOTS)await page.screenshot({path:process.env.UX_SCREENSHOTS+'/map-mobile.png',fullPage:true});
 // The sheet: half on open, dragged to full and down to the 112px peek, Escape closes.
 const wrap=await page.locator('.map-canvas-wrap').boundingBox(),sheetH=async()=>(await page.locator('.bsheet').boundingBox()).height;
 assert.ok(Math.abs(await sheetH()-wrap.height*.5)<4,'opens at half');
 const drag=async dy=>{const h=await page.locator('.bsheet-handle').boundingBox();await page.mouse.move(h.x+h.width/2,h.y+10);await page.mouse.down();await page.mouse.move(h.x+h.width/2,h.y+10+dy,{steps:10});await page.mouse.up();await page.waitForTimeout(450)};
 await drag(-300);assert.ok(Math.abs(await sheetH()-wrap.height*.9)<4,'full');
 await drag((await sheetH())-112);assert.ok(Math.abs(await sheetH()-112)<3,'peek');
 await page.keyboard.press('Escape');await page.waitForTimeout(400);assert.equal(await page.locator('.bsheet').count(),0);
 // S1-M1: a camera beside a stand is on top, and a tap on the pair asks which one.
 await page.getByRole('button',{name:'Fit the estate'}).click();await page.waitForTimeout(600);
 const cam=await page.locator('.map-pin[aria-label^="Camera: Track camera"] .map-pin-icon').boundingBox();
 await page.mouse.click(cam.x+cam.width/2,cam.y+cam.height/2);await page.locator('.bsheet[aria-label="Which one?"]').waitFor();
 assert.deepEqual((await page.locator('.map-pick-row').allInnerTexts()).map(t=>t.split('\n')[0]),['Track camera','South track']);
 await page.locator('.map-pick-row').first().click();await page.locator('.bsheet[aria-label="Camera: Track camera"]').waitFor();
 // S1-M2: the camera's header is when it last had an animal on it, never a photo count.
 assert.equal(await page.locator('.bsheet .bsheet-meta').innerText(),'No animal photos yet');
 assert.equal(await page.locator('.cam-sheet-numbers summary').innerText(),'Battery low');
 assert.equal(await page.locator('.cam-sheet-night').innerText(),'Nothing on camera last night');
 await page.keyboard.press('Escape');await page.waitForTimeout(400);
 // Stage 2: a camera with a photo is its photo on the map, with how many are new to you.
 const valley=page.locator('.map-pin[data-id="c1"]');
 assert.equal(await valley.locator('.map-badge--callout').innerText(),'3');
 assert.equal(await valley.getAttribute('aria-label'),'Camera: Valley camera, 3 new photos');
 await valley.locator('.map-callout').click();await page.locator('.bsheet[aria-label="Camera: Valley camera"]').waitFor();
 assert.match(await page.locator('.bsheet .bsheet-meta').innerText(),/^Last photo .+ \(3 h ago\)$/);
 assert.equal(await page.locator('.cam-sheet-night').innerText(),'Last night: Wild boar · 2 visits, Red deer · 1 visit');
 await page.waitForTimeout(300);assert.deepEqual(seen,['/api/cameras/c2/seen','/api/cameras/c1/seen'],'each camera opened is marked seen');assert.equal(await valley.locator('.map-badge--callout').isHidden(),true,'opening it clears the count');
 await page.locator('.cam-strip-tile').first().waitFor();assert.equal(await page.locator('.cam-strip-tile').count(),3);
 assert.ok(images.length>0&&images.every(p=>p.endsWith('/thumb')),'the map and the strip use small copies');
 await page.locator('.cam-strip-tile').nth(1).click();await page.locator('.ov[role="dialog"]').waitFor();
 assert.ok(images.some(p=>p==='/api/images/i2/file'),'the viewer opens the full photo');
 await page.keyboard.press('Escape');await page.waitForTimeout(300);assert.equal(await page.locator('.bsheet').count(),1,'back to the sheet');
 assert.equal(await page.getByRole('link',{name:'See all photos'}).getAttribute('href'),'/photos?camera=c1');
 await page.keyboard.press('Escape');await page.waitForTimeout(400);

 await page.getByRole('button',{name:'Map type, layers and tools',exact:true}).click();await page.getByRole('button',{name:/Add a stand/}).click();
 assert.equal(await page.getByRole('button',{name:'Save here',exact:true}).isDisabled(),true,'A new stand needs a name');
 await page.getByRole('textbox',{name:'Name',exact:true}).fill('Test position');
 await page.locator('.map-canvas canvas').click({position:{x:150,y:150}});
 assert.equal(writes.length,0,'Draft positions are not saved automatically');
 await page.getByRole('button',{name:'Save here',exact:true}).click();await page.getByText('Saved.',{exact:true}).waitFor();assert.equal(writes[0].body.name,'Test position');assert.equal(typeof writes[0].body.lat,'number');

 // B-12/S1-m2: an unsaved outline is guarded against Back as well as the tabs.
 await page.locator('.tabbar').getByRole('link',{name:'Stands'}).click();await page.waitForURL(/\/stands/);
 await page.locator('.tabbar').getByRole('link',{name:'Map'}).click();await ready();
 await page.getByRole('button',{name:'Map type, layers and tools',exact:true}).click();await page.getByRole('button',{name:/Draw bedding/}).click();
 const add=page.getByRole('button',{name:'Add corner'}),pan=async(dx,dy)=>{await page.evaluate(([dx,dy])=>window.__gsMap.panBy([dx,dy],{duration:0}),[dx,dy]);await page.waitForTimeout(150)};
 // S1-m3: a double press of the glove button lays one corner.
 await add.dblclick();assert.match(await page.locator('.map-editor-status').innerText(),/^1 corner/);
 await pan(90,0);await add.click();await pan(0,90);await add.click();
 dialogs.length=0;await page.goBack();await page.waitForTimeout(800);
 assert.equal(dialogs.length,1,'Back asks first');assert.equal(new URL(page.url()).pathname,'/map');
 assert.match(await page.locator('.map-editor-status').innerText(),/^3 corners/,'the outline is kept');
 await page.getByRole('button',{name:'Cancel'}).click();await page.getByRole('button',{name:'Throw away'}).click();

 // S1-M3: with no signal the wind bar says it has no wind, not that the air is calm.
 offline=true;await page.reload();await page.getByText('No signal, so the map didn’t load.').waitFor({timeout:15000});
 assert.match(await page.locator('.map-windbar').innerText(),/Wind not loaded/);offline=false;

 await page.goto(base+'/stands');
 const other=page.locator('#stand-s3');await other.waitFor();assert.equal(await other.getByRole('button').count(),0,'Other hunter reservations have no write controls');
 const free=page.locator('#stand-s1');await free.getByRole('button',{name:'Reserve',exact:true}).click();await free.getByRole('button',{name:'Cancel',exact:true}).waitFor();await free.getByRole('button',{name:'Cancel',exact:true}).click();await free.getByRole('button',{name:'Reserve',exact:true}).waitFor();
 if(process.env.UX_SCREENSHOTS)await page.screenshot({path:process.env.UX_SCREENSHOTS+'/stands-mobile.png',fullPage:true});
 assert.deepEqual(errors,[]);console.log('PASS: real MapLibre render, map selection/sheet snaps/layers, tile error and Try again keep every layer, Esri fallback and retry, overlapping pins ask which, camera header, camera photo and new count, seen clears it, strip thumbs open the viewer, crosshair draft/save, Back guards an outline, offline wind bar, mobile overflow, reservation ownership, cancelled reservations.');
 } finally { await browser.close() }
})().catch(e=>{console.error(e);process.exit(1)});
