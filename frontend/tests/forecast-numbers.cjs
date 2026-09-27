// Plan items 9-11 against fixtures: Tonight reads visits (photos behind the fold), the
// hour chart's green band is the headline's Best hours, the footnote counts the nights
// the cameras were watching, the track record is graded per verdict, a camera left
// out of the ranking says so; Insights states a weather finding only when it beat the
// shuffle test, reads the makeup in visits and pages a class's photos; an admin can
// retire a camera and a member can't.
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
 const win={start_hour:21,end_hour:0};
 let plan={
  verdict:'BEST_ODDS',changed:{kind:'none',camera:null,text:'Nothing changed. Much the same as the last few nights.'},
  wind:{status:'unknown',text:'No wind forecast tonight.',is_advice:false},
  calibration:{available:true,n_evaluated:40,statement:'x',lines:['When it said Best odds, animals came 7 of 9 nights.','When it said Quiet, animals came 1 of 12 nights.']},
  recommended:{camera:'Charca',camera_id:'c1',species:'Wild boar',runner_up:null,probability:0.7,best_window:win,expect:'Sow + piglets',
   classes:[{label:'Sow + piglets',visits:12,photos:120},{label:'Boar',visits:1,photos:3}],nights_present:21,active_nights:30,visits:13,photos:123,
   reason:'Wild boar seen 21 of 30 nights at this camera.',caveat:'The camera watches all night.'},
  conditions:{moon_phase:'New Moon',moon_illum:4,darkness_minutes:720,wind_dir_deg:null,wind_speed_kmh:null},
  factors:[{text:'Wild boar seen 5 of the last 7 nights here',impact:'+++'}],
  where:[{camera:'Charca',camera_id:'c1',verdict:'BEST_ODDS',probability:0.7,nights_present:21,active_nights:30,visits:13,photos:123,best_window:win,classes:[{label:'Sow + piglets',visits:12,photos:120},{label:'Roe deer',visits:30,photos:31}]}],
  alternates:[],
  alerts:[{camera:'PL07',camera_id:'c7',status:'offline',detail:'No check-in for 480h. No photos for 20 days, so it is left out of tonight’s ranking',ranked:false}],
  exposure:{excluded_nights:2,note:'2 nights at Charca left out: photos not checked yet.'},nights_of_data:30,freshness:null};
 // The busiest hours of the whole day are 03-06; the plan's are 21-00.
 const overview={totals:{sightings:100,empty:5,nights:30,cameras:1},by_hour:Array.from({length:24},(_,h)=>({hour:h,count:h>=3&&h<6?30:h>=21?10:1})),
  by_camera:[{id:'c1',name:'Charca',sightings:100}],by_species:[{species:'Wild Boar',count:100}],best_window:{start_hour:3,end_hour:6,share_pct:60}};
 const bars=(lo,mid,hi)=>[{label:'low',rate:lo,days:20,min:0,max:30},{label:'mid',rate:mid,days:20,min:31,max:70},{label:'high',rate:hi,days:20,min:71,max:100}];
 const patterns={nights:60,tested:true,shuffles:200,range:['2026-08-01','2026-09-26'],scopes:[{key:'all',label:'All animals',total_nights:60,sightings:180,status:{moon_illum:'ok',temp:'ok',wind:'unavailable'},
  drivers:[{factor:'Moonlight',key:'moon_illum',sample_nights:60,buckets:bars(4.1,2.9,1.2),beats_chance:true},{factor:'Temperature',key:'temp',sample_nights:60,buckets:bars(2.0,3.1,2.4),beats_chance:false}]}]};
 const insights={outlook:[],correlations:[{kind:'time',statement:'Your cameras are busiest between 21:00 and midnight.',strength:0.4,sample:120}],
  composition:[{label:'Sow + piglets',count:12,visits:12,photos:120,top_camera:'Charca'}]};
 const classPhotos=Array.from({length:130},(_,i)=>({image_id:`s${i}`,file_url:`/api/images/s${i}/file`,captured_at:ago(i+1),camera:'Charca',group_size:5}));
 let role='admin';const patches=[];
 const camera={id:'c1',name:'Charca',provider_name:null,name_is_custom:false,can_rename:true,battery_pct:80,battery_level:null,signal_pct:60,model:'FLEX',image_count:10,empty_count:2,last_capture:ago(1),last_report_at:ago(1),
  photo_count:null,photo_limit:null,plan_name:null,cycle_end:null,sd_used_mb:null,sd_total_mb:null,retired_at:null,health:{status:'ok',detail:'Reporting normally',producing:true,credits_left:null,hours_since_report:1}};
 const newPage=async()=>{
  const page=await browser.newPage({viewport:{width:390,height:844},serviceWorkers:'block',hasTouch:true,timezoneId:'Europe/Madrid',locale:'en-GB'});
  await page.addInitScript(()=>localStorage.setItem('gs_token','forecast-numbers-fixture'));
  page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/api/**',async route=>{
   const req=route.request(),u=new URL(req.url()),p=u.pathname,json=b=>route.fulfill({contentType:'application/json',body:JSON.stringify(b)});
   if(/\/thumb$|\/file$/.test(p))return route.fulfill({contentType:'image/png',body:tile});
   if(p==='/api/auth/me')return json({id:'u1',email:'owner@x.local',role});
   if(p==='/api/forecast/tonight')return json({...plan,generated_at:new Date().toISOString()});
   if(p==='/api/analytics/overview')return json(overview);
   if(p==='/api/alerts')return json([]);
   if(p==='/api/species')return json([{id:'wild_boar',common_name:'Wild boar',huntable:true,detections:100}]);
   if(p==='/api/sits/mine')return json({live:[],to_report:[]});
   if(p==='/api/insights')return json(insights);
   if(p==='/api/insights/patterns')return json(patterns);
   if(p==='/api/insights/class'){
    const before=u.searchParams.get('before'),from=before?classPhotos.findIndex(x=>x.captured_at===before)+1:0,page=classPhotos.slice(from,from+120),last=page.at(-1),more=from+120<classPhotos.length;
    return json({items:page,next_before:more?last.captured_at:null,next_before_id:more?last.image_id:null});
   }
   if(p==='/api/cameras')return json([camera]);
   if(/\/api\/cameras\/c1\/images/.test(p))return json([]);
   if(p==='/api/cameras/c1/retired'){const body=JSON.parse(req.postData());patches.push(body);camera.retired_at=body.retired?new Date().toISOString():null;
    camera.health=body.retired?{status:'retired',detail:'Retired',producing:false,credits_left:null,hours_since_report:1}:{status:'ok',detail:'Reporting normally',producing:true,credits_left:null,hours_since_report:1};
    return json({id:'c1',name:'Charca',retired_at:camera.retired_at})}
   return json({});
  });
  return page;
 };

 // ── Tonight
 let page=await newPage();
 await page.goto(base+'/');
 await page.locator('.tn-verdict-label').waitFor();
 const hero=await page.locator('.tn-verdict').innerText();
 assert.match(hero,/Sow \+ piglets\s*12 visits/);assert.match(hero,/Boar\s*1 visit\b/);assert.doesNotMatch(hero,/×/);
 assert.match(hero,/From 30 nights the cameras were watching\. 2 nights at Charca left out: photos not checked yet\./);
 const cams=await page.locator('#tn-cams-h').locator('..').innerText();
 assert.match(cams,/left out of tonight’s ranking/);assert.doesNotMatch(cams,/ranked on what they saw/);
 await page.getByText('Show the numbers').click();
 const fold=await page.locator('.tn-details').innerText();
 assert.match(fold,/Sow \+ piglets\s*12 visits \(120 photos\)/);assert.match(fold,/A visit is one arrival/);
 assert.match(fold,/When it said Best odds, animals came 7 of 9 nights\.\s*When it said Quiet, animals came 1 of 12 nights\./);
 const greens=await page.$$eval('.tn-bars-y .bar-y',b=>b.map(x=>getComputedStyle(x).backgroundColor));
 const green=greens.map((c,h)=>c===greens[21]?h:null).filter(h=>h!==null);
 assert.deepEqual(green,[21,22,23],'the green band is the headline best hours, not 03-06');
 await page.close();
 plan={...plan,verdict:'NO_DATA',reason:'No sightings yet.',recommended:undefined,where:[],factors:[],alerts:[],exposure:undefined,nights_of_data:0};
 page=await newPage();
 await page.goto(base+'/');
 await page.getByText('No nights of camera photos yet.').waitFor();
 assert.equal(await page.getByText(/From 1 nights/).count(),0);
 await page.close();

 // ── Insights
 page=await newPage();
 await page.goto(base+'/insights');
 await page.locator('.insights-findings li',{hasText:'More animals on a dark moon.'}).waitFor();
 const weather=await page.locator('.insights-weather').innerText();
 assert.doesNotMatch(weather,/More animals on (cool|mild|warm) nights/,'an untested difference is not a finding');
 assert.match(weather,/held up when the same nights were shuffled 200 times/);
 await page.locator('.insights-weather summary',{hasText:'Show the numbers'}).click();
 assert.match(await page.locator('.insights-weather').innerText(),/Could be chance[\s\S]*Weather history unavailable right now|Weather history unavailable right now[\s\S]*Could be chance/);
 assert.match(await page.locator('.insights-class').innerText(),/12 visits, mostly at Charca/);
 await page.locator('.insights-class').click();
 await page.locator('.insights-more').waitFor();
 assert.equal(await page.locator('.ov-panel img').count(),120);
 const more=await page.locator('.insights-more').boundingBox();assert.ok(more.height>=44,'Show older photos is glove-sized');
 await page.locator('.insights-more').click();
 await page.waitForFunction(()=>document.querySelectorAll('.ov-panel img').length===130);
 assert.equal(await page.locator('.insights-more').count(),0);
 await page.close();

 // ── Cameras: retire
 page=await newPage();
 await page.goto(base+'/cameras');
 await page.locator('.cam-card summary',{hasText:'Details'}).click();
 const sw=page.locator('.switch-row',{hasText:'Retire camera'});
 assert.ok((await sw.boundingBox()).height>=44);
 await sw.click();
 await page.locator('.cam-health',{hasText:'Retired'}).waitFor();
 assert.deepEqual(patches,[{retired:true}]);
 assert.equal(await sw.getAttribute('aria-checked'),'true');
 await page.close();
 role='member';camera.retired_at=null;
 page=await newPage();
 await page.goto(base+'/cameras');
 await page.locator('.cam-card summary',{hasText:'Details'}).click();
 await page.waitForTimeout(500);
 assert.equal(await page.locator('.switch-row',{hasText:'Retire camera'}).count(),0,'only an admin retires a camera');
 await page.close();

 assert.deepEqual(errors,[]);
 console.log('PASS: Tonight in visits with photos behind the fold, green band = best hours, watched nights and left-out note, no "1 nights", track record per verdict, a camera left out says so; Insights finding only when tested, makeup in visits, class photos paged; retire switch for admins only.');
 } finally { await browser.close() }
})().catch(e=>{console.error(e);process.exit(1)});
