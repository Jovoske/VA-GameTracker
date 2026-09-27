// Camera logins that stop working are visible, against fixtures: Settings says per login
// what is wrong (the main .env login first), Re-enter password is offered only when a
// new password is the fix and is checked before it is kept, a camera whose own photos
// didn't come says so, camera cards say "Photos not coming in" instead of "check
// battery", and the Check button follows a fetch to its end: busy, the count while the
// detector looks, then the result naming the login that needs a look; with nothing
// new it ends at once. Run like map-and-stands.cjs (BASE_URL, PW_CHANNEL).
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert=require('node:assert/strict');
(async()=>{
 const channel=process.env.PW_CHANNEL??'msedge',base=process.env.BASE_URL||'http://127.0.0.1:5173';
 const browser=await chromium.launch({headless:true,...(channel?{channel}:{})});
 try {
 const page=await browser.newPage({viewport:{width:390,height:844},serviceWorkers:'block',hasTouch:true,timezoneId:'Europe/Madrid',locale:'en-GB'});
 await page.addInitScript(()=>localStorage.setItem('gs_token','camera-logins-fixture'));
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 const ago=m=>new Date(Date.now()-m*60e3).toISOString();
 const status=(state,error=null,okMin=6,extra={})=>({state,error,last_ok_at:okMin==null?null:ago(okMin),last_attempt_at:ago(6),password_problem:/Re-enter/.test(error??''),cameras_failing:0,camera_error:null,...extra});
 const unreachable="Couldn't reach SPYPOINT. It tries again on the next fetch.";
 const camError="SPYPOINT isn't answering properly right now. It tries again on the next fetch.";
 const login=(id,label,provider,st,extra={})=>({id,label,username:id+'@example.com',provider,owner:'member@estate.local',active:true,primary:false,cameras:1,importing:false,status:st,can_remove:true,can_edit:true,ubox_min_interval_seconds:60,ubox_max_images_per_day:500,last_import:null,...extra});
 let passwordOk=false;
 const accounts=()=>[
  login('primary','Main SPYPOINT login','spypoint',status('failing','SPYPOINT refused the password. Re-enter it.',1560),{primary:true,owner:null,cameras:3,can_remove:false,can_edit:false}),
  login('marco','Marco’s cameras','spypoint',status('ok')),
  login('ana','Ana’s UBox','ubox',passwordOk?status('ok',null,0):status('failing','UBox refused the password. Re-enter it.',2880)),
  login('pedro','Pedro’s cameras','spypoint',status('unknown',null,null),{importing:true,cameras:2}),
  login('leo','Leo’s cameras','spypoint',status('failing',unreachable,40)),
  login('sara','Sara’s cameras','spypoint',status('ok',null,6,{cameras_failing:1,camera_error:camError}),{cameras:2}),
  login('tom','Tom’s cameras','spypoint',status('stale',null,180)),
  login('eva','Eva’s cameras','spypoint',status('busy',null,150)),
 ];
 const health=(s,detail,login)=>({status:s,detail,producing:s==='ok',credits_left:null,hours_since_report:1,...(login?{login}:{})});
 const cam=(id,name,h)=>({id,name,provider_name:name,name_is_custom:false,can_rename:true,battery_pct:80,battery_level:null,signal_pct:60,model:'FLEX',image_count:0,empty_count:0,last_capture:null,last_report_at:ago(60*24*9),photo_count:null,photo_limit:null,plan_name:null,cycle_end:null,sd_used_mb:null,sd_total_mb:null,health:h});
 const cameras=[
  cam('c1','Charca',health('not_syncing','Photos not coming in. The camera login needs attention.',{label:'Main SPYPOINT login',error:'SPYPOINT refused the password. Re-enter it.'})),
  cam('c2','Suntek',health('quiet','No photos since 18 Sep')),
  cam('c3','Viejo Pino',health('disconnected','Not connected: no camera login here fetches it now')),
  cam('c4','Pinar',health('not_syncing',`Photos not coming in. ${camError}`,{label:'Sara’s cameras',error:camError,camera:true})),
 ];
 const problems=[{label:'Ana’s UBox',error:'UBox refused the password. Re-enter it.'}];
 const since=new Date(Date.now()-60e3).toISOString();
 let polls=0,nothingNew=false;const syncStatus=()=>{polls++;
  // Nothing came in and a login failed: the AI pass may run on, but that is the result.
  if(nothingNew)return{status:'identifying',result:'error',images_downloaded:0,started_at:new Date().toISOString(),problems:[{label:'Leo’s cameras',error:unreachable}]};
  if(polls<=2)return{status:'running',started_at:since};
  if(polls<=4)return{status:'identifying',result:'partial',images_downloaded:3,started_at:new Date().toISOString(),problems};
  return{status:'partial',images_downloaded:3,started_at:new Date().toISOString(),finished_at:new Date().toISOString(),problems};
 };
 await page.route('**/api/**',route=>{
  const u=new URL(route.request().url()),m=route.request().method(),p=u.pathname;
  if(p==='/api/camera-accounts/ana/password'&&m==='PUT'){
   const body=JSON.parse(route.request().postData()||'{}');
   if(body.password!=='right'){return route.fulfill({status:400,json:{detail:'Could not connect to UBox Pro: UBox rejected the account or password'}})}
   passwordOk=true;return route.fulfill({json:{id:'ana',cameras:1,note:'Password saved. Photos come in on the next fetch, within 15 minutes.'}});
  }
  if(p==='/api/cameras/sync'&&m==='POST')return route.fulfill({json:nothingNew?{status:'started',since:new Date(Date.now()-1000).toISOString()}:{status:'busy',since,note:'Already checking.'}});
  if(m!=='GET')return route.fulfill({json:{}});
  const result=p==='/api/auth/me'?{id:'me',email:'admin@estate.local',role:'admin'}:p==='/api/camera-accounts'?accounts()
   :p==='/api/cameras'?cameras:/^\/api\/cameras\/[^/]+\/images$/.test(p)?[]:p==='/api/cameras/sync/status'?syncStatus()
   :p==='/api/users'||p==='/api/species'?[]:p==='/api/admin/version'?{version:'0.23.0'}
   :p==='/api/admin/status'?{cameras:3,images:0,detections:0,empty:0,last_sync:{status:'partial',at:ago(3)},suntek:{ready:2,failed:1}}:undefined;
  return result===undefined?route.fulfill({status:404,json:{detail:'Not Found'}}):route.fulfill({json:result});
 });

 // Settings: every login with its state in words, the main one first and not removable.
 await page.goto(base+'/settings#accounts');
 const row=id=>page.locator(`[data-login="${id}"]`);
 await row('primary').waitFor();
 assert.match(await row('primary').locator('.login-status').innerText(),/^SPYPOINT refused the password\. Re-enter it\. It is set in the server’s \.env file/);
 assert.equal(await row('primary').getByRole('button').count(),0,'the .env login can be neither removed nor re-entered here');
 assert.match(await row('marco').locator('.login-status').innerText(),/^Working\. Last fetch 6 min ago\.$/);
 assert.equal(await row('pedro').locator('.login-status').innerText(),'Fetching its photos for the first time…');
 assert.match(await row('pedro').innerText(),/2 cameras/,'the cameras its provider listed, not 0, while it imports');
 assert.equal(await row('leo').locator('.login-status').innerText(),unreachable);
 assert.equal(await row('leo').getByRole('button',{name:/Re-enter/}).count(),0,'a new password would not help when SPYPOINT can’t be reached');
 assert.equal(await row('sara').locator('.login-status').innerText(),`One of its cameras didn’t come through on the last fetch. ${camError}`);
 assert.equal(await row('tom').locator('.login-status').innerText(),'No fetch has worked for 3 h. Photos have stopped coming in.');
 assert.equal(await row('eva').locator('.login-status').innerText(),'Busy going through new photos. Fetching carries on when that’s done.');
 for(const id of ['sara','tom','eva'])assert.equal(await row(id).getByRole('button',{name:/Re-enter/}).count(),0);
 const remove=await row('leo').getByRole('button',{name:'Remove Leo’s cameras'}).boundingBox();
 assert.ok(remove.height>=44,`Remove is glove-sized (${remove.height}px)`);
 await page.getByText('5 need attention',{exact:true}).waitFor();
 // A password the provider refuses is not kept; the right one clears the problem.
 await row('ana').getByRole('button',{name:'Re-enter the password for Ana’s UBox'}).click();
 await row('ana').getByLabel(/UBox Pro password for ana@example\.com/).fill('wrong');
 await row('ana').getByRole('button',{name:'Save password'}).click();
 await row('ana').getByText('Could not connect to UBox Pro: UBox rejected the account or password').waitFor();
 await row('ana').getByLabel(/UBox Pro password/).fill('right');
 await row('ana').getByRole('button',{name:'Save password'}).click();
 await row('ana').getByText('Password saved. Photos come in on the next fetch, within 15 minutes.').waitFor();
 assert.match(await row('ana').locator('.login-status').innerText(),/^Working\./);
 assert.equal(await row('ana').getByLabel(/UBox Pro password/).count(),0);
 await page.getByRole('button',{name:/System/}).click();
 await page.getByText('2 waiting. 1 failed: ask whoever runs the server to retry them.').waitFor();
 await page.getByText(/^Partly worked, \d+ min ago$/).waitFor();

 // Cameras: a login problem is not a flat battery; a removed login and a Suntek are neither.
 await page.goto(base+'/cameras');
 const card=name=>page.locator('.cam-card').filter({has:page.locator('.camera-name-title',{hasText:name})});
 await card('Charca').waitFor();
 assert.equal(await card('Charca').locator('.cam-health').innerText(),'Photos not coming in');
 assert.equal(await card('Charca').locator('.cam-health-note').innerText(),'Login needs attention (Main SPYPOINT login): SPYPOINT refused the password. Re-enter it. Camera logins');
 assert.match(await card('Suntek').locator('.cam-health').innerText(),/^No photos since /);
 assert.equal(await card('Viejo Pino').locator('.cam-health').innerText(),'Not connected');
 assert.equal(await card('Pinar').locator('.cam-health-note').innerText(),`The last fetch couldn’t get its photos. ${camError} Camera logins`);
 assert.doesNotMatch(await page.locator('.cam-list').innerText(),/check battery|battery and signal|Quiet since/i);

 // Check while a fetch is running: it waits, gives the count while the detector looks,
 // then ends on the count and the login that needs a look, never on a spinner.
 await page.getByRole('button',{name:'Check for new photos'}).click();
 await page.getByText('Already checking. Waiting for it to finish…').waitFor();
 await page.getByText(/^3 new photos came in\. Looking for animals in them…$/).waitFor({timeout:15000});
 await page.locator('.cam-sync-status--warn').waitFor({timeout:15000});
 assert.equal(await page.locator('.cam-sync-status').innerText(),'!\n3 new photos came in. Ana’s UBox: UBox refused the password. Re-enter it. Camera logins');
 assert.equal(await page.locator('.cam-sync-spinner').count(),0);
 assert.ok(await page.getByRole('button',{name:'Check for new photos'}).isEnabled());
 // Nothing new: the line is final straight away, never "… Looking for animals in them…".
 nothingNew=true;
 await page.getByRole('button',{name:'Check for new photos'}).click();
 await page.locator('.cam-sync-status--error').waitFor({timeout:15000});
 assert.equal(await page.locator('.cam-sync-status').innerText(),`!\nCouldn't fetch any photos. Leo’s cameras: ${unreachable} Camera logins`);
 assert.equal(await page.locator('.cam-sync-spinner').count(),0);
 for(let i=0;i<60&&!(await page.getByRole('button',{name:'Check for new photos'}).isEnabled());i++)await page.waitForTimeout(250);
 assert.ok(await page.getByRole('button',{name:'Check for new photos'}).isEnabled(),'the check is over');
 await page.locator('.cam-sync-link').click();
 await row('primary').waitFor();
 assert.ok(page.url().endsWith('/settings#accounts'));
 assert.deepEqual(errors,[]);
 console.log('PASS: login states in words (main login first, importing, busy, stopped for N h, a camera of a working login), re-enter password only for a password problem and checked before kept, Remove glove-sized, Suntek spool counts, camera cards say "Photos not coming in" not "check battery", busy check waits, counts while identifying, ends on the count and the login, nothing new ends at once, link to Settings.');
 } finally {await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});
