// Camera logins that stop working are visible, against fixtures: Settings says per login
// what is wrong (the main .env login first), Re-enter password is checked before it is
// kept, camera cards say "Photos not coming in" instead of "check battery", and the
// Check button follows a fetch to its end: busy, the count while the detector looks,
// then the result naming the login that needs a look. Run like map-and-stands.cjs
// (BASE_URL, PW_CHANNEL).
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
 const status=(state,error=null,okMin=6)=>({state,error,last_ok_at:okMin==null?null:ago(okMin),last_attempt_at:ago(6)});
 const login=(id,label,provider,st,extra={})=>({id,label,username:id+'@example.com',provider,owner:'member@estate.local',active:true,primary:false,cameras:1,importing:false,status:st,can_remove:true,can_edit:true,ubox_min_interval_seconds:60,ubox_max_images_per_day:500,last_import:null,...extra});
 let passwordOk=false;
 const accounts=()=>[
  login('primary','Main SPYPOINT login','spypoint',status('failing','SPYPOINT refused the password. Re-enter it.',1560),{primary:true,owner:null,cameras:3,can_remove:false,can_edit:false}),
  login('marco','Marco’s cameras','spypoint',status('ok')),
  login('ana','Ana’s UBox','ubox',passwordOk?status('ok',null,0):status('failing','UBox refused the password. Re-enter it.',2880)),
  login('pedro','Pedro’s cameras','spypoint',status('unknown',null,null),{importing:true,cameras:2}),
 ];
 const health=(s,detail,login)=>({status:s,detail,producing:s==='ok',credits_left:null,hours_since_report:1,...(login?{login}:{})});
 const cam=(id,name,h)=>({id,name,provider_name:name,name_is_custom:false,can_rename:true,battery_pct:80,battery_level:null,signal_pct:60,model:'FLEX',image_count:0,empty_count:0,last_capture:null,last_report_at:ago(60*24*9),photo_count:null,photo_limit:null,plan_name:null,cycle_end:null,sd_used_mb:null,sd_total_mb:null,health:h});
 const cameras=[
  cam('c1','Charca',health('not_syncing','Photos not coming in. The camera login needs attention.',{label:'Main SPYPOINT login',error:'SPYPOINT refused the password. Re-enter it.'})),
  cam('c2','Suntek',health('quiet','No photos since 18 Sep')),
  cam('c3','Viejo Pino',health('disconnected','Not connected: no camera login here fetches it now')),
 ];
 const problems=[{label:'Ana’s UBox',error:'UBox refused the password. Re-enter it.'}];
 const since=new Date(Date.now()-60e3).toISOString();
 let polls=0;const syncStatus=()=>{polls++;
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
  if(p==='/api/cameras/sync'&&m==='POST')return route.fulfill({json:{status:'busy',since,note:'Already checking.'}});
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
 await page.getByText('2 need attention',{exact:true}).waitFor();
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
 await page.getByText('2 waiting, 1 failed (on the server: ftp_import retry)').waitFor();
 assert.match(await page.getByText(/^Some logins need attention, \d+ min ago$/).innerText(),/need attention/);

 // Cameras: a login problem is not a flat battery; a removed login and a Suntek are neither.
 await page.goto(base+'/cameras');
 const card=name=>page.locator('.cam-card').filter({has:page.locator('.camera-name-title',{hasText:name})});
 await card('Charca').waitFor();
 assert.equal(await card('Charca').locator('.cam-health').innerText(),'Photos not coming in');
 assert.equal(await card('Charca').locator('.cam-health-note').innerText(),'Login needs attention (Main SPYPOINT login): SPYPOINT refused the password. Re-enter it. Camera logins');
 assert.match(await card('Suntek').locator('.cam-health').innerText(),/^No photos since /);
 assert.equal(await card('Viejo Pino').locator('.cam-health').innerText(),'Not connected');
 assert.doesNotMatch(await page.locator('.cam-list').innerText(),/check battery|battery and signal|Quiet since/i);

 // Check while a fetch is running: it waits, gives the count while the detector looks,
 // then ends on the count and the login that needs a look, never on a spinner.
 await page.getByRole('button',{name:'Check for new photos'}).click();
 await page.getByText('Already checking. Waiting for it to finish…').waitFor();
 await page.getByText(/^3 new photos came in\. Ana’s UBox: UBox refused the password\. Re-enter it\. Looking for animals in them…$/).waitFor({timeout:15000});
 await page.locator('.cam-sync-status--warn').waitFor({timeout:15000});
 assert.equal(await page.locator('.cam-sync-status').innerText(),'!\n3 new photos came in. Ana’s UBox: UBox refused the password. Re-enter it. Camera logins');
 assert.equal(await page.locator('.cam-sync-spinner').count(),0);
 assert.ok(await page.getByRole('button',{name:'Check for new photos'}).isEnabled());
 await page.locator('.cam-sync-link').click();
 await row('primary').waitFor();
 assert.ok(page.url().endsWith('/settings#accounts'));
 assert.deepEqual(errors,[]);
 console.log('PASS: login states in words (main login first, importing shows its cameras), re-enter password checked before kept, Suntek spool counts, camera cards say "Photos not coming in" not "check battery", busy check waits, counts while identifying, ends on the count and the login, link to Settings.');
 } finally {await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});
