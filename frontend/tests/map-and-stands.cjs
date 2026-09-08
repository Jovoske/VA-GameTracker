const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert=require('node:assert/strict'),fs=require('node:fs');
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'msedge',args:['--enable-unsafe-swiftshader']});
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
 let result=u.pathname==='/api/map/tonight'?data():u.pathname==='/api/cameras'?cameras:u.pathname==='/api/users/me'?{id:'me',role:'admin'}:u.pathname==='/api/stands'?stands:u.pathname==='/api/sits'?sits:[];
 if(u.pathname==='/api/insights')result={outlook:[],composition:[],correlations:[]};
 if(u.pathname==='/api/insights/patterns')result={nights:30,scopes:[{key:'all',label:'All animals',total_nights:30,sightings:450,drivers:[{key:'moon_illum',factor:'Moon illumination',statement:'~67% more activity on bright moonlit nights.',confidence:.5,sample_nights:30,buckets:[{label:'low',rate:10,days:10,min:0,max:20},{label:'mid',rate:15,days:10,min:21,max:70},{label:'high',rate:20,days:10,min:71,max:100}]}]}]};
 await route.fulfill({json:result});
 });
 const tileReady = page.waitForResponse(r=>r.url().includes('/MapServer/tile/') && r.status()===200,{timeout:30000});
 await page.goto('http://127.0.0.1:5173/map');
 await tileReady; await page.waitForLoadState('networkidle');
 await page.getByRole('button',{name:'Stand: Ridge overlook',exact:true}).waitFor({timeout:20000});
 await page.getByText('From NW → SE',{exact:true}).waitFor();
 await page.getByRole('button',{name:'Stand: Ridge overlook',exact:true}).click();await page.locator('.map-selection-peek').waitFor();
 assert.equal(writes.length,0,'Selecting markers must not write');
 await page.getByRole('button',{name:'Layers',exact:true}).click();await page.getByLabel('Estimated scent exposure',{exact:true}).check();await page.getByLabel('Estimated scent exposure',{exact:true}).uncheck();await page.getByRole('button',{name:'Layers',exact:true}).click();
 if(process.env.UX_SCREENSHOTS){fs.mkdirSync(process.env.UX_SCREENSHOTS,{recursive:true});await page.screenshot({path:process.env.UX_SCREENSHOTS+'/map-desktop.png',fullPage:true})}
 await page.setViewportSize({width:390,height:844});await page.reload();await page.getByRole('button',{name:'Stand: Ridge overlook',exact:true}).waitFor();await page.waitForLoadState('networkidle');await page.getByRole('button',{name:'Stand: Ridge overlook',exact:true}).click();await page.waitForTimeout(1000);
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
 if(process.env.UX_SCREENSHOTS)await page.screenshot({path:process.env.UX_SCREENSHOTS+'/map-mobile.png',fullPage:true});
 await page.getByRole('button',{name:'Add stand',exact:true}).click();await page.getByRole('textbox',{name:'Name',exact:true}).fill('Test position');
 assert.equal(await page.getByRole('button',{name:'Save location',exact:true}).isDisabled(),true);
 await page.locator('.map-canvas canvas').click({position:{x:150,y:150}});
 assert.equal(writes.length,0,'Draft positions are not saved automatically');
 await page.getByRole('button',{name:'Save location',exact:true}).click();await page.getByText('Location saved.',{exact:false}).waitFor();assert.equal(writes[0].body.name,'Test position');assert.equal(typeof writes[0].body.lat,'number');
 await page.goto('http://127.0.0.1:5173/stands');
 const other=page.locator('#stand-s3');await other.waitFor();assert.equal(await other.getByRole('button').count(),0,'Other hunter reservations have no write controls');
 const free=page.locator('#stand-s1');await free.getByRole('button',{name:'Reserve for tonight'}).click();await free.getByRole('button',{name:'Cancel reservation'}).waitFor();await free.getByRole('button',{name:'Cancel reservation'}).click();await free.getByRole('button',{name:'Reserve for tonight'}).waitFor();
 if(process.env.UX_SCREENSHOTS)await page.screenshot({path:process.env.UX_SCREENSHOTS+'/stands-mobile.png',fullPage:true});
 await page.goto('http://127.0.0.1:5173/insights');await page.getByRole('table').waitFor();assert.equal(await page.getByText(/67% more activity/).count(),0);await page.getByText(/does not measure light at ground level/).waitFor();assert.equal(await page.getByText(/% confidence/).count(),0);
 assert.deepEqual(errors,[]);console.log('PASS: real MapLibre render, map selection/layers, explicit draft/save, mobile overflow, reservation ownership, cancelled reservations, clear raw-data comparisons.');
 } finally { await browser.close() }
})().catch(e=>{console.error(e);process.exit(1)});
