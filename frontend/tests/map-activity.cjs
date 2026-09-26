// Activity and Replay on the map, against fixtures: the View choice, circles and their
// filters, the card a tap opens, a night played back with a likely path, and the
// normal map coming back. Run like map-and-stands.cjs (BASE_URL, PW_CHANNEL).
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert=require('node:assert/strict');
(async()=>{
 const channel=process.env.PW_CHANNEL??'msedge',base=process.env.BASE_URL||'http://127.0.0.1:5173';
 const browser=await chromium.launch({headless:true,...(channel?{channel}:{}),args:['--enable-unsafe-swiftshader']});
 try {
 const page=await browser.newPage({viewport:{width:390,height:844},serviceWorkers:'block',hasTouch:true,timezoneId:'Europe/Madrid',locale:'en-GB'});
 await page.addInitScript(()=>localStorage.setItem('gs_token','map-activity-fixture'));
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 const tile=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==','base64');
 await page.route(/ign\.es|catastro\.meh\.es|arcgisonline/,r=>r.fulfill({contentType:'image/png',body:tile}));
 // Two cameras 420 m apart (a sounder went from one to the other last night) and one far off.
 const ok={status:'ok',detail:'Reporting normally',producing:true,hours_since_report:1};
 const cam=(id,name,lat,lon)=>({id,name,lat,lon,battery_pct:80,signal_pct:60,last_report_at:new Date().toISOString(),health:ok,can_rename:true,latest:{image_id:'i-'+id,captured_at:new Date(Date.now()-3600e3).toISOString(),species_id:'wild_boar',label:'Wild boar'},new_count:0,last_night:[],last_night_status:'watched'});
 const cameras=[cam('c1','Charca',39.0951,-1.3622),cam('c2','Encinar',39.0921,-1.3651),cam('c3','Pinar',39.1010,-1.3700)];
 const data={conditions:{wind_dir_deg:315,wind_speed_kmh:12},airflow:{source:'synoptic',wind_dir_deg:315,wind_speed_kmh:12},zones:[],stands:[],safe_ground:{status:'ok',cells:[]},routes:[],scent_range_m:320,terrain_loaded:true};
 const row=(c,visits,watched,read,extra={})=>({camera_id:c.id,name:c.name,lat:c.lat,lon:c.lon,visits,watched_nights:watched,blind_nights:7-watched,checking_nights:0,nights_with:Math.min(visits,watched),per_night:watched?+(visits/watched).toFixed(2):null,peak:visits>1?'21–23':null,by_species:visits?[{species_id:'wild_boar',label:'Wild boar',visits}]:[],read,...extra});
 const activity=q=>({nights:+q.get('nights'),part:q.get('part'),hours:[18,8],species:q.get('species'),species_label:q.get('species')==='all'?null:'Wild boar',first_night:'2026-09-19',last_night:'2026-09-25',
  species_options:[{species_id:'wild_boar',label:'Wild boar',visits:9},{species_id:'red_deer',label:'Red deer',visits:2}],
  cameras:q.get('species')==='red_deer'?[row(cameras[0],0,7,'No red deer on the 7 nights.'),row(cameras[1],0,7,'No red deer on the 7 nights.'),row(cameras[2],0,0,'Not counted: the camera wasn’t working on these nights.')]
   :[row(cameras[0],6,7,'Wild boar on 5 of 7 nights, mostly 21–23 h'),row(cameras[1],3,6,'Wild boar on 3 of 6 nights it was working, at 20:50, 21:30 and 22:10'),row(cameras[2],0,0,'Not counted: the camera wasn’t working on these nights.')]});
 const start='2026-09-25T18:00:00+02:00',at=(h,m)=>new Date(Date.parse(start)+((h-18+24)%24*60+m)*60e3).toISOString();
 const replay={night:'2026-09-25',start,end:'2026-09-26T08:00:00+02:00',
  visits:[{at:at(20,50),last_at:at(20,51),camera_id:'c2',species_id:'wild_boar',label:'Wild boar',group_size:4,frames:3,image_id:'v1'},{at:at(21,40),last_at:at(21,40),camera_id:'c1',species_id:'wild_boar',label:'Wild boar',group_size:4,frames:3,image_id:'v2'},{at:at(2,15),last_at:at(2,15),camera_id:'c1',species_id:'red_deer',label:'Red deer',group_size:2,frames:3,image_id:'v3'}],
  links:[{from_camera_id:'c2',to_camera_id:'c1',species_id:'wild_boar',label:'Wild boar',from_at:at(20,51),to_at:at(21,40)}]};
 const asked=[];
 await page.route('**/api/**',route=>{
  const u=new URL(route.request().url());
  if(/\/api\/images\/[^/]+\/(thumb|file)$/.test(u.pathname))return route.fulfill({contentType:'image/png',body:tile});
  if(route.request().method()!=='GET')return route.fulfill({json:{}});
  if(u.pathname.startsWith('/api/map/'))asked.push(u.pathname.slice(4)+u.search);
  const result=u.pathname==='/api/map/tonight'?data:u.pathname==='/api/map/cameras'?cameras:u.pathname==='/api/auth/me'?{id:'me',role:'member'}
   :u.pathname==='/api/map/activity'?activity(u.searchParams):u.pathname==='/api/map/replay/nights'?[{night:'2026-09-25',visits:3},{night:'2026-09-24',visits:0}]
   :u.pathname==='/api/map/replay'?(u.searchParams.get('night')==='2026-09-25'?replay:{...replay,night:u.searchParams.get('night'),visits:[],links:[]}):undefined;
  return result===undefined?route.fulfill({status:404,json:{detail:'Not Found'}}):route.fulfill({json:result});
 });
 const features=src=>page.evaluate(async s=>(await window.__gsMap.getSource(s).getData()).features.length,src);
 await page.goto(base+'/map');
 await page.waitForFunction(()=>window.__gsMap&&window.__gsMap.loaded()&&document.querySelectorAll('.map-pin').length===3,null,{timeout:20000});

 // The View choice lives in the Map sheet; Activity draws a circle per camera it can vouch for.
 await page.getByRole('button',{name:'Map type, layers and tools'}).click();
 await page.getByRole('radiogroup',{name:'View'}).getByRole('radio',{name:'Activity'}).click();
 await page.locator('.mode-bar--activity').waitFor();
 await page.waitForTimeout(500);
 assert.equal(await features('activity'),2,'no circle for a camera that was not working');
 assert.ok(page.url().includes('view=activity'));
 assert.ok(asked.includes('/map/activity?species=all&part=all&nights=7'),'7 nights, all night, every animal by default');
 await page.getByRole('radio',{name:'Last night'}).click();await page.getByRole('radio',{name:/^Night/}).click();
 await page.getByRole('radiogroup',{name:'Which animal'}).getByRole('radio',{name:'Red deer'}).click();
 await page.getByText('No visits in this period.').waitFor();
 assert.equal(asked.at(-1),'/map/activity?species=red_deer&part=night&nights=1');
 await page.getByRole('radiogroup',{name:'Which animal'}).getByRole('radio',{name:'All animals'}).click();
 await page.waitForTimeout(400);
 // A tap on a circle reads it; Open camera is that camera's own sheet.
 const p=await page.evaluate(()=>{const m=window.__gsMap,pt=m.project([-1.3622,39.0951]),r=m.getCanvas().getBoundingClientRect();return{x:r.left+pt.x+10,y:r.top+pt.y+4}});
 await page.touchscreen.tap(p.x,p.y);
 await page.locator('.act-card').waitFor();
 assert.equal(await page.locator('.act-card-read').innerText(),'Wild boar on 5 of 7 nights, mostly 21–23 h');
 await page.getByRole('button',{name:'Open camera'}).click();
 await page.locator('.bsheet[aria-label="Camera: Charca"]').waitFor();
 assert.equal(await page.locator('.mode-bar').count(),0,'the bar steps aside for the sheet');
 await page.keyboard.press('Escape');await page.locator('.mode-bar--activity').waitFor();

 // Replay: last night by default, a tick per visit, and the path drawn once the second visit happens.
 await page.getByRole('button',{name:'Map type, layers and tools'}).click();
 await page.getByRole('radiogroup',{name:'View'}).getByRole('radio',{name:'Replay'}).click();
 await page.waitForFunction(()=>document.querySelectorAll('.replay-ticks i').length===3);
 assert.equal(await features('activity'),0,'the circles go with Activity');
 assert.equal(await page.locator('.replay-now strong').innerText(),'18:00');
 const range=page.locator('.replay-track input[type=range]');
 await range.focus();for(let i=0;i<170;i++)await page.keyboard.press('ArrowRight');// 20:50
 await page.waitForTimeout(200);
 assert.equal(await page.locator('.map-pop').count(),1);assert.equal(await features('replay-links'),0,'no path before the second visit');
 for(let i=0;i<55;i++)await page.keyboard.press('ArrowRight');// 21:45
 await page.waitForTimeout(200);
 assert.equal(await page.locator('.replay-now strong').innerText(),'21:45');
 assert.equal(await features('replay-links'),2,'shaft and head of the likely path');
 assert.match(await page.locator('.replay-note').innerText(),/Likely went this way: a guess/);
 await page.getByRole('button',{name:'Back 5 minutes'}).click();
 assert.equal(await page.locator('.replay-now strong').innerText(),'21:40');
 await page.getByRole('radio',{name:/^60×/}).click();await page.getByRole('button',{name:'Play',exact:true}).click();
 await page.waitForTimeout(1200);await page.getByRole('button',{name:'Pause',exact:true}).click();
 assert.ok(await page.locator('.replay-now strong').innerText()>'22:', 'the clock runs at an hour a second');
 await page.locator('.replay-night select').selectOption('2026-09-24');
 await page.getByText('Nothing came past a camera that night.').waitFor();
 // Leaving Replay restores the normal map.
 await page.getByRole('button',{name:'Close replay, back to the camera photos'}).click();
 await page.waitForTimeout(300);
 assert.ok(!page.url().includes('view='));
 assert.equal(await page.locator('.map-pop').count(),0);assert.equal(await features('replay-links'),0);
 assert.ok(await page.locator('.map-callout').first().isVisible(),'camera photos are back');
 assert.deepEqual(errors,[]);console.log('PASS: View choice, activity circles only where the camera was watching, filters in the request, empty period, tap a circle, open camera and back, replay ticks, pops, likely path after the second visit, −5 min, play at 60×, empty night, leaving restores the map.');
 } finally { await browser.close() }
})().catch(e=>{console.error(e);process.exit(1)});
