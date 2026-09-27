// Feature 24 and audit B-06: the map works with no signal.
// Runs the BUILT app (npm run build first) with its real service worker, from a small
// server in this file that serves dist/ the way Db01 does and passes /api to a live
// backend (API_URL, e.g. a devstack), or drops the connection (no signal). The base
// map's pictures are stubbed (IGN is not reachable from here) with a 256 px PNG.
// Proves: "Download the estate for offline" saves only the estate's box at zooms
// 11 to 18 and says so ("Estate map saved on this phone · N MB · just now"); Esri's
// world imagery can't be saved; with no signal at all the map reopens with its
// pictures, every placed stand and camera, a camera's sheet with its photos, and an
// honest line about how old it is; a copy from an earlier night drops its wind; an
// admin sets the estate's box and a member can't; Remove takes it off the phone.
// Env: API_URL (required), EMAIL / MEMBER_EMAIL / PASSWORD (devstack logins),
// PLAYWRIGHT_MODULE, PW_CHANNEL (as the other tests), DIST (default ../dist),
// UX_SCREENSHOTS (a folder for screenshots).
// The worker's own requests are taken offline like the page's only with this set
// (Chromium, Playwright 1.4x-1.5x). A route on the page's requests goes round the
// worker, so the stubbed pictures are routed only while there is signal: with none,
// the worker alone answers, as on a phone in the valley.
process.env.PW_EXPERIMENTAL_SERVICE_WORKER_NETWORK_EVENTS='1';
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),http=require('node:http'),path=require('node:path'),zlib=require('node:zlib');
const dist=process.env.DIST||path.join(__dirname,'..','dist');
const API=process.env.API_URL;
const shots=process.env.UX_SCREENSHOTS;

// A 256x256 PNG of one colour, so a screenshot shows where the map has pictures.
function png(r,g,b){
 const crcTable=Array.from({length:256},(_,n)=>{let c=n;for(let k=0;k<8;k++)c=c&1?0xedb88320^(c>>>1):c>>>1;return c>>>0});
 const crc=buf=>{let c=0xffffffff;for(const x of buf)c=crcTable[(c^x)&0xff]^(c>>>8);return (c^0xffffffff)>>>0};
 const chunk=(type,data)=>{const len=Buffer.alloc(4);len.writeUInt32BE(data.length);const td=Buffer.concat([Buffer.from(type),data]);const c=Buffer.alloc(4);c.writeUInt32BE(crc(td));return Buffer.concat([len,td,c])};
 const ihdr=Buffer.alloc(13);ihdr.writeUInt32BE(256,0);ihdr.writeUInt32BE(256,4);ihdr[8]=8;ihdr[9]=2;
 const row=Buffer.concat([Buffer.from([0]),Buffer.alloc(256*3).map((_,i)=>[r,g,b][i%3])]);
 return Buffer.concat([Buffer.from([137,80,78,71,13,10,26,10]),chunk('IHDR',ihdr),chunk('IDAT',zlib.deflateSync(Buffer.concat(Array(256).fill(row)))),chunk('IEND',Buffer.alloc(0))]);
}
const TILE=png(40,170,80);

// Which ground an IGN WMTS tile covers.
const tileOf=u=>{const q=new URL(u).searchParams;return {z:+q.get('tilematrix'),x:+q.get('tilecol'),y:+q.get('tilerow'),layer:q.get('layer')}};
const lonOf=(x,z)=>x/2**z*360-180;
const latOf=(y,z)=>{const n=Math.PI-2*Math.PI*y/2**z;return 180/Math.PI*Math.atan(Math.sinh(n))};
const touches=(t,b)=>lonOf(t.x,t.z)<=b.east&&lonOf(t.x+1,t.z)>=b.west&&latOf(t.y,t.z)>=b.south&&latOf(t.y+1,t.z)<=b.north;

const net={mode:'pass'};
const types={'.js':'text/javascript','.css':'text/css','.html':'text/html','.json':'application/json','.webmanifest':'application/manifest+json','.png':'image/png','.woff2':'font/woff2','.svg':'image/svg+xml'};
const server=http.createServer((req,res)=>{
 const u=new URL(req.url,'http://x');
 if(net.mode==='drop')return req.socket.destroy();
 if(u.pathname.startsWith('/api/')){
  const up=http.request(API+u.pathname+u.search,{method:req.method,headers:{...req.headers,host:new URL(API).host}},r=>{res.writeHead(r.statusCode,r.headers);r.pipe(res)});
  up.on('error',()=>{res.writeHead(502);res.end()});
  return req.pipe(up);
 }
 let file=path.join(dist,path.normalize(u.pathname).replace(/^(\.\.[/\\])+/,''));
 if(!fs.existsSync(file)||fs.statSync(file).isDirectory())file=path.join(dist,'index.html');
 res.writeHead(200,{'Content-Type':types[path.extname(file)]||'application/octet-stream','Cache-Control':file.includes(`${path.sep}assets${path.sep}`)?'public, max-age=31536000, immutable':'no-cache'});
 res.end(fs.readFileSync(file));
});
const login=async(email)=>(await (await fetch(API+'/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email,password:process.env.PASSWORD||'changeme'})})).json()).access_token;
const call=async(tok,p,o={})=>{const r=await fetch(API+'/api'+p,{...o,headers:{'Content-Type':'application/json',Authorization:'Bearer '+tok}});return {status:r.status,body:await r.json().catch(()=>null)}};

(async()=>{
 assert.ok(API,'set API_URL to a running backend (a devstack)');
 assert.ok(fs.existsSync(path.join(dist,'sw.js'))&&!fs.readFileSync(path.join(dist,'sw.js'),'utf8').includes('__GS_BUILD__'),'run npm run build first: dist/sw.js must be stamped');
 await new Promise(r=>server.listen(0,'127.0.0.1',r));
 const base=`http://127.0.0.1:${server.address().port}`;
 const channel=process.env.PW_CHANNEL??'msedge';
 const browser=await chromium.launch({headless:true,...(channel?{channel}:{}),args:['--enable-unsafe-swiftshader','--use-gl=swiftshader']});
 const admin=await login(process.env.EMAIL||'admin@gamesense.local');
 const member=await login(process.env.MEMBER_EMAIL||'member@gamesense.local');
 await call(admin,'/estate/box',{method:'DELETE'});
 const estate=(await call(admin,'/estate')).body;
 const placed=(await call(admin,'/map/tonight')).body.stands.filter(s=>s.lat!=null).length+(await call(admin,'/map/cameras')).body.filter(c=>c.lat!=null).length;
 const errors=[];
 const tiles=[];
 const stubTiles=ctx=>ctx.route(/ign\.es|arcgisonline|catastro/,r=>{tiles.push(r.request().url());return r.fulfill({status:200,contentType:'image/png',headers:{'Access-Control-Allow-Origin':'*'},body:TILE})});
 // No signal: the backend and the tile servers unreachable, for the page and its worker.
 const signal=async(ctx,on)=>{net.mode=on?'pass':'drop';if(on){await ctx.setOffline(false);await stubTiles(ctx)}else{await ctx.unrouteAll({behavior:'ignoreErrors'});await ctx.setOffline(true)}};
 const context=async(tok)=>{
  const ctx=await browser.newContext({viewport:{width:390,height:844},serviceWorkers:'allow',hasTouch:true,isMobile:true,timezoneId:'Europe/Madrid',locale:'en-GB'});
  await ctx.addInitScript(t=>{if(!localStorage.getItem('gs_token'))localStorage.setItem('gs_token',t)},tok);
  await stubTiles(ctx);
  return ctx;
 };
 const open=async(ctx)=>{const page=await ctx.newPage();page.on('pageerror',e=>errors.push(e.message));return page};
 const sheet=async page=>{await page.getByRole('button',{name:'Map type, layers and tools'}).click();await page.locator('.msheet-offline').waitFor()};
 const status=page=>page.locator('.msheet-offline .msheet-status').innerText();
 // Share of the map painted by the stubbed picture (green), not the dark page, with
 // the pins, buttons and lines over it hidden for the measure.
 const painted=async page=>{
  const hide=await page.addStyleTag({content:'.map-notices,.map-pin,.map-fabs,.map-scale,.maplibregl-ctrl,.map-windbar{visibility:hidden!important}'});
  const shot=(await page.locator('.map-canvas').screenshot()).toString('base64');
  await hide.evaluate(e=>e.remove());
  return page.evaluate(async b64=>{const img=new Image();img.src='data:image/png;base64,'+b64;await img.decode();const c=document.createElement('canvas');c.width=img.width;c.height=img.height;const g=c.getContext('2d');g.drawImage(img,0,0);
   const d=g.getImageData(0,0,c.width,c.height).data;let green=0,n=0;for(let i=0;i<d.length;i+=16){n++;if(d[i+1]>d[i]+30&&d[i+1]>d[i+2]+30)green++}return green/n},shot);
 };
 try {
 // ── 1. With signal: the whole app stored by its worker; the estate saved on demand ──
 const ctx=await context(admin),page=await open(ctx);
 await page.goto(base+'/map');
 await page.evaluate(()=>navigator.serviceWorker.ready);
 await page.waitForFunction(async()=>{const k=(await caches.keys()).find(n=>n.startsWith('gamesense-shell-'));if(!k||!navigator.serviceWorker.controller)return false;return (await (await caches.open(k)).keys()).some(r=>/\/assets\/Map-.*\.js$/.test(r.url))},null,{timeout:30000,polling:500});
 await page.reload();await page.locator('.map-pin').first().waitFor({timeout:20000});
 assert.equal(await page.locator('.map-pin').count(),placed,'every placed stand and camera');
 await sheet(page);
 await page.locator('.msheet-offline').scrollIntoViewIfNeeded();
 assert.match(await status(page),/^Not saved on this phone\./);
 assert.deepEqual(await page.locator('.msheet-offline [role=radio]').allInnerTexts(),['Aerial','Topo'],'Esri’s world imagery is never offered for saving');
 assert.match(await page.locator('.msheet-offline .msheet-box').innerText(),/drawn round the stands, cameras and bedding/,'an admin sees the box and where it comes from');
 assert.equal(await page.locator('.msheet-offline details summary').count(),1);
 assert.match(await page.locator('.msheet-offline details summary').innerText(),/^About \d+ MB\. Best on Wi-Fi\.$/);
 if(shots){fs.mkdirSync(shots,{recursive:true});await page.screenshot({path:shots+'/offline-sheet.png'})}
 tiles.length=0;
 const main=page.getByRole('button',{name:'Download the estate for offline'});
 assert.ok((await main.boundingBox()).height>=56,'the main action is glove-sized');
 await main.click();
 await page.waitForFunction(()=>/^Estate map saved on this phone · \d+ (MB|KB) · just now$/.test(document.querySelector('.msheet-offline .msheet-status')?.textContent||''),null,{timeout:120000,polling:250});
 assert.match(await page.locator('.msheet-offline').innerText(),/Saved\. The map works here with no signal\./);
 const saved=tiles.map(tileOf).filter(t=>t.layer==='OI.OrthoimageCoverage');
 assert.ok(saved.length>50,`the estate’s pictures were fetched (${saved.length})`);
 assert.ok(saved.every(t=>t.z>=11&&t.z<=18),'only the zooms a hunter uses, 11 to 18');
 assert.ok(saved.every(t=>touches(t,estate.box)),'nothing outside the estate’s box');
 const kept=await page.evaluate(async()=>{const c=await caches.open('gamesense-estate-v1');const k=(await c.keys()).map(r=>r.url);return {tiles:k.filter(u=>u.includes('ign.es')).length,thumbs:k.filter(u=>/\/thumb$/.test(u)).length,api:k.filter(u=>/\/api\/(photos|map\/paths|estate)/.test(u)).length}});
 assert.equal(kept.tiles,new Set(saved.map(t=>`${t.z}/${t.x}/${t.y}`)).size,'each picture kept once');
 assert.ok(kept.thumbs>0&&kept.api>=3,`the camera sheets and their photos too (${JSON.stringify(kept)})`);
 if(shots)await page.screenshot({path:shots+'/offline-saved.png'});
 // A second download fetches nothing it already has.
 tiles.length=0;await page.getByRole('button',{name:'Download again'}).click();
 await page.waitForFunction(()=>/Saved\./.test(document.querySelector('.msheet-offline')?.textContent||'')&&!document.querySelector('.msheet-progress'),null,{timeout:60000,polling:250});
 assert.ok(tiles.filter(u=>u.includes('ign.es')).length<saved.length/2,`a second download asks again only for what it lacks (${tiles.length})`);

 // ── 2. No signal at all: the map opens with its pictures, pins and camera sheets ──
 await signal(ctx,false);
 await page.goto(base+'/map').catch(()=>{});
 await page.locator('.map-pin').first().waitFor({timeout:20000});
 await page.waitForTimeout(2500);
 assert.equal(await page.locator('.map-pin').count(),placed,'with no signal: every placed stand and camera');
 await page.waitForFunction(()=>/^No signal\. Map from (just now|\d+ min ago)\./.test(document.querySelector('.map-pill--age')?.textContent||''),null,{timeout:20000});
 const green=await painted(page);
 assert.ok(green>.95,`with no signal the estate’s pictures show (${Math.round(green*100)}% of the map)`);
 assert.equal(await page.getByText('Part of the map picture didn’t load').count(),0,'the saved estate covers the view');
 if(shots)await page.screenshot({path:shots+'/offline-map.png'});
 // A camera's sheet: its latest photos from the phone.
 await page.locator('.map-pin--camera').first().click({force:true});
 // At estate zoom a camera's pin sits on its stand's: "Which one?" asks.
 await page.waitForTimeout(400);const pickRow=page.locator('.map-pick-row',{hasText:'Camera'}).first();if(await pickRow.count())await pickRow.click();
 await page.locator('.cam-strip-row img').first().waitFor({timeout:15000});
 await page.waitForFunction(()=>[...document.querySelectorAll('.cam-strip-row img')].slice(0,3).every(i=>i.complete&&i.naturalWidth>0),null,{timeout:15000});
 assert.equal(await page.locator('.cam-strip-msg').count(),0,'no "No signal, so the photos didn’t load"');
 if(shots)await page.screenshot({path:shots+'/offline-camera.png'});
 await page.keyboard.press('Escape');
 // The Map sheet says what the phone has.
 await page.goto(base+'/map').catch(()=>{});await page.locator('.map-pin').first().waitFor({timeout:20000});
 await sheet(page);
 assert.match(await status(page),/^Estate map saved on this phone · \d+ (MB|KB) · just now$/);

 // ── 3. A saved copy from an earlier night keeps its ground and drops its wind ──
 const later=await open(ctx);await later.clock.install({time:new Date(Date.now()+30*3600e3)});
 await later.goto(base+'/map').catch(()=>{});await later.locator('.map-pin').first().waitFor({timeout:20000});
 await later.waitForFunction(()=>/Its wind was for that night, so it isn’t shown\./.test(document.querySelector('.map-pill--age')?.textContent||''),null,{timeout:20000});
 assert.doesNotMatch(await later.locator('.map-windbar').innerText(),/From the /,'no wind direction from an earlier night');
 await later.locator('.map-pin--stand').first().click({force:true});
 await later.waitForTimeout(400);const pick2=later.locator('.map-pick-row',{hasText:'Stand'}).first();if(await pick2.count())await pick2.click();
 await later.locator('.bsheet-verdict').waitFor();
 assert.doesNotMatch(await later.locator('.bsheet').innerText(),/Wind is (right|wrong)/,'no verdict from last night’s wind');
 assert.match(await later.locator('.bsheet').innerText(),/earlier night/);
 await later.close();

 // ── 4. Back with signal: an admin sets the box, a member downloads what it covers ──
 await signal(ctx,true);
 await page.goto(base+'/map');await page.locator('.map-pin').first().waitFor({timeout:20000});
 await page.waitForFunction(()=>!document.querySelector('.map-pill--age'),null,{timeout:20000});
 await sheet(page);
 await page.getByRole('button',{name:'Use this view as the estate'}).click();
 await page.waitForFunction(()=>/set by an admin/.test(document.querySelector('.msheet-box')?.textContent||''),null,{timeout:15000});
 assert.match(await page.locator('.msheet-offline').innerText(),/The estate’s box has changed since\. Download again to match it\./);
 const set=(await call(member,'/estate')).body;
 assert.equal(set.box_set,true);
 assert.ok(set.box.north-set.box.south<estate.box.north-estate.box.south+1,'the view above the sheet, not the whole screen');
 assert.equal((await call(member,'/estate/box',{method:'PUT',body:JSON.stringify(estate.box)})).status,403,'members can’t set it');
 // Remove.
 await page.getByRole('button',{name:'Remove from this phone'}).click();
 await page.locator('.msheet-offline .map-confirm').getByRole('button',{name:'Remove'}).click();
 await page.waitForFunction(()=>/^Not saved on this phone\./.test(document.querySelector('.msheet-offline .msheet-status')?.textContent||''));
 assert.ok(!(await page.evaluate(()=>caches.keys())).includes('gamesense-estate-v1'),'nothing left on the phone');
 await ctx.close();
 {
  const mctx=await context(member),mpage=await open(mctx);
  await mpage.goto(base+'/map');await mpage.locator('.map-pin').first().waitFor({timeout:20000});
  await sheet(mpage);
  assert.equal(await mpage.locator('.msheet-box').count(),0,'a member downloads, and doesn’t set the box');
  assert.ok(await mpage.getByRole('button',{name:'Download the estate for offline'}).isEnabled());
  await mctx.close();
 }
 await call(admin,'/estate/box',{method:'DELETE'});
 assert.deepEqual(errors,[]);
 console.log('PASS: the estate saved on a phone (box, zooms 11-18, IGN only, status line with size and age, no double downloads), the map with no signal (pictures, every pin, camera sheets with photos, an honest age line), an earlier night’s copy without its wind, the admin’s box, remove.');
 } finally { await browser.close(); server.close() }
})().catch(e=>{console.error(e);process.exit(1)});
