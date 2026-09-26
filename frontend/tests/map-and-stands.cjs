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
 const stands=[{id:'s1',name:'Ridge overlook',lat:39.094,lon:-1.362,claimed_tonight:false,claimed_by:null},{id:'s2',name:'Oak hollow',lat:39.098,lon:-1.357,claimed_tonight:true,claimed_by:'me'},{id:'s3',name:'South track',lat:39.091,lon:-1.355,claimed_tonight:true,claimed_by:'other'}];
 const sits=[{id:'cancelled',stand_id:'s1',user_id:'me',outcome:'cancelled'},{id:'mine',stand_id:'s2',user_id:'me',outcome:'unreported',started_at:null,wind_text:'Saved wind check.'},{id:'other',stand_id:'s3',user_id:'other',outcome:'unreported',started_at:null}];
 const cameras=[{id:'c1',name:'Valley camera',lat:39.095,lng:-1.358,sightings:24,battery_pct:72}];
 const writes=[];
 const data=()=>({conditions:{wind_dir_deg:315,wind_speed_kmh:12},airflow:{source:'synoptic',wind_dir_deg:315,wind_speed_kmh:12},zones:[{id:'z1',name:'Pine cover',kind:'bedding',polygon:{type:'Polygon',coordinates:[[[-1.354,39.097],[-1.351,39.098],[-1.349,39.096],[-1.354,39.097]]]}}],stands:stands.map(s=>({...s,wind:{status:s.id==='s3'?'unknown':'clean',source:s.id==='s3'?'unknown':'synoptic',scent_bearing:135,speed_kmh:12,range_m:320,half_deg:22.5,text:'Estimated scent travels southeast, away from mapped bedding.'},approaches:[]})),safe_ground:{status:'ok',cells:[]},routes:[],scent_range_m:320,terrain_loaded:true});
 await page.route('**/api/**',async route=>{
 const request=route.request(),u=new URL(request.url()),method=request.method();
 if(method!=='GET'){
 const body=request.postDataJSON();writes.push({path:u.pathname,method,body});
 if(u.pathname==='/api/stands'){stands.push({id:'s4',...body,claimed_tonight:false,claimed_by:null});return route.fulfill({json:{id:'s4'}})}
 if(u.pathname==='/api/sits'){stands.find(s=>s.id===body.stand_id).claimed_tonight=true;stands.find(s=>s.id===body.stand_id).claimed_by='me';sits.push({id:'new',stand_id:body.stand_id,user_id:'me',outcome:'unreported',started_at:null});return route.fulfill({json:{id:'new'}})}
 if(u.pathname==='/api/sits/new'){sits.find(s=>s.id==='new').outcome=body.outcome;stands[0].claimed_tonight=false;stands[0].claimed_by=null;return route.fulfill({json:{}})}
 return route.fulfill({json:{}})
 }
 let result=u.pathname==='/api/map/tonight'?data():u.pathname==='/api/cameras'?cameras:u.pathname==='/api/auth/me'?{id:'me',role:'admin'}:u.pathname==='/api/stands'?stands:u.pathname==='/api/sits'?sits:undefined;
 if(result===undefined)return route.fulfill({status:404,json:{detail:'Not Found'}});
 await route.fulfill({json:result});
 });
 // Base-map tiles are stubbed: this checks the app's map, not whether IGN or Esri answer today.
 const tile=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==','base64');
 let tiles=0;await page.route(/ign\.es|catastro\.meh\.es|arcgisonline/,r=>{tiles++;return r.fulfill({contentType:'image/png',body:tile})});
 await page.goto(base+'/map');
 await page.getByRole('button',{name:'Stand: Ridge overlook',exact:true}).waitFor({timeout:20000});
 await page.waitForLoadState('networkidle');assert.ok(tiles>0,'MapLibre asked for base tiles');
 await page.getByText('From the north-west',{exact:true}).waitFor();
 await page.getByRole('button',{name:'Stand: Ridge overlook',exact:true}).click();await page.locator('.bsheet').getByRole('heading',{name:'Ridge overlook'}).waitFor();
 assert.equal(writes.length,0,'Selecting markers must not write');
 await page.getByRole('button',{name:'Map type, layers and tools',exact:true}).click();const safe=page.getByRole('switch',{name:'Scent-safe ground'});await safe.click();assert.equal(await safe.getAttribute('aria-checked'),'true');await safe.click();await page.keyboard.press('Escape');
 if(process.env.UX_SCREENSHOTS){fs.mkdirSync(process.env.UX_SCREENSHOTS,{recursive:true});await page.screenshot({path:process.env.UX_SCREENSHOTS+'/map-desktop.png',fullPage:true})}
 await page.setViewportSize({width:390,height:844});await page.reload();await page.getByRole('button',{name:'Stand: Ridge overlook',exact:true}).waitFor();await page.waitForLoadState('networkidle');await page.getByRole('button',{name:'Stand: Ridge overlook',exact:true}).click();await page.waitForTimeout(1000);
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
 if(process.env.UX_SCREENSHOTS)await page.screenshot({path:process.env.UX_SCREENSHOTS+'/map-mobile.png',fullPage:true});
 await page.keyboard.press('Escape');await page.getByRole('button',{name:'Map type, layers and tools',exact:true}).click();await page.getByRole('button',{name:/Add a stand/}).click();
 assert.equal(await page.getByRole('button',{name:'Save here',exact:true}).isDisabled(),true,'A new stand needs a name');
 await page.getByRole('textbox',{name:'Name',exact:true}).fill('Test position');
 await page.locator('.map-canvas canvas').click({position:{x:150,y:150}});
 assert.equal(writes.length,0,'Draft positions are not saved automatically');
 await page.getByRole('button',{name:'Save here',exact:true}).click();await page.getByText('Saved.',{exact:true}).waitFor();assert.equal(writes[0].body.name,'Test position');assert.equal(typeof writes[0].body.lat,'number');
 await page.goto(base+'/stands');
 const other=page.locator('#stand-s3');await other.waitFor();assert.equal(await other.getByRole('button').count(),0,'Other hunter reservations have no write controls');
 const free=page.locator('#stand-s1');await free.getByRole('button',{name:'Reserve',exact:true}).click();await free.getByRole('button',{name:'Cancel',exact:true}).waitFor();await free.getByRole('button',{name:'Cancel',exact:true}).click();await free.getByRole('button',{name:'Reserve',exact:true}).waitFor();
 if(process.env.UX_SCREENSHOTS)await page.screenshot({path:process.env.UX_SCREENSHOTS+'/stands-mobile.png',fullPage:true});
 assert.deepEqual(errors,[]);console.log('PASS: real MapLibre render, map selection/sheet/layers, crosshair draft/save, mobile overflow, reservation ownership, cancelled reservations.');
 } finally { await browser.close() }
})().catch(e=>{console.error(e);process.exit(1)});
