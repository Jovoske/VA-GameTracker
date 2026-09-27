// The harvest book (feature 23) and people and vehicles on camera (feature 25), against
// fixtures: the morning card after a SHOT on Stands (glove-sized, "Nothing to log" with
// Undo), the one form (the animal is asked for in words; a save that loses its answer
// is the same line on the next try; what was typed survives closing it), Settings'
// book for an admin (the season's CSV) and a member (their own, no export), and Photos'
// admin-only "People & vehicles" (no notes or "Wrong?" on those frames, "Nobody in it?"
// with Undo; a member's phone never asks for them, even with an old choice saved).
// Run like map-and-stands.cjs (BASE_URL, PW_CHANNEL).
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert=require('node:assert/strict'),fs=require('node:fs');
(async()=>{
 const channel=process.env.PW_CHANNEL??'msedge',base=process.env.BASE_URL||'http://127.0.0.1:5173';
 const browser=await chromium.launch({headless:true,...(channel?{channel}:{}),args:['--enable-unsafe-swiftshader']});
 const errors=[];
 try {
 const tile=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==','base64');
 const photo='<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="900"><rect width="1600" height="900" fill="#394b3b"/></svg>';
 const ago=h=>new Date(Date.now()-h*3600e3).toISOString();
 const nightISO=days=>{const d=new Date(Date.now()-6*3600e3-days*86400e3);return d.toLocaleDateString('en-CA',{timeZone:'Europe/Madrid'})};
 const ask={sit_id:'sit1',stand_id:'s1',stand:'Puente',night:nightISO(1),shot_at:ago(12)};
 const choices=[['wild_boar','Wild boar',true],['red_deer','Red deer',true],['roe_deer','Roe deer',true],['fox','Fox',false]]
  .map(([id,name,big])=>({id,name,hidden:false,likely:big,big_game:big,seen:3}));
 const line=b=>({id:b.id??'h1',sit_id:b.sit_id??null,stand_id:'s1',stand:'Puente',hunter:'Pedro',yours:true,species_id:b.species_id,
  species:choices.find(c=>c.id===b.species_id).name,sex:b.sex,age_class:b.age_class,seal:b.seal,weight_kg:b.weight_kg,notes:b.notes,
  taken_at:b.taken_at??ask.shot_at,created_at:new Date().toISOString(),can_edit:true});
 const feed=[{image_id:'a1',file_url:'/api/images/a1/file',captured_at:ago(2),camera:'Charca',camera_id:'c1',label:'Wild boar',species_id:'wild_boar',group_size:1,notes_count:0}];
 const people=[{image_id:'p1',file_url:'/api/images/p1/file',captured_at:ago(3),camera:'Charca',camera_id:'c1',label:'Person',species_id:null,group_size:null,notes_count:0,has_person:true,has_vehicle:false},
  {image_id:'p2',file_url:'/api/images/p2/file',captured_at:ago(5),camera:'Charca',camera_id:'c1',label:'Vehicle',species_id:null,group_size:null,notes_count:0,has_person:false,has_vehicle:true}];
 let role='member',post='ok',asks=[ask],book=[];
 const posts=[],nothing=[],cleared=[],feedAsks=[];
 const newPage=async(viewport={width:390,height:844},init)=>{
  const page=await browser.newPage({viewport,serviceWorkers:'block',hasTouch:true,timezoneId:'Europe/Madrid',locale:'en-GB',acceptDownloads:true});
  await page.addInitScript(init??(()=>localStorage.setItem('gs_token','harvest-fixture')));
  page.on('pageerror',e=>errors.push(e.message));
  await page.route(/ign\.es|catastro\.meh\.es|arcgisonline/,r=>r.fulfill({contentType:'image/png',body:tile}));
  await page.route('**/api/**',async route=>{
   const req=route.request(),u=new URL(req.url()),method=req.method(),p=u.pathname;
   if(/\/api\/images\/[^/]+\/thumb$/.test(p))return route.fulfill({contentType:'image/png',body:tile});
   if(/\/api\/images\/[^/]+\/file$/.test(p))return route.fulfill({contentType:'image/svg+xml',body:photo});
   if(p==='/api/harvests'&&method==='POST'){
    const b=req.postDataJSON();posts.push(b);
    if(post==='drop')return route.abort('internetdisconnected');
    const l=line(b);book=[l,...book.filter(x=>x.id!==l.id)];asks=asks.filter(a=>a.sit_id!==b.sit_id);
    return route.fulfill({status:201,json:l});
   }
   let m=p.match(/^\/api\/sits\/([^/]+)\/no-harvest$/);
   if(m){const b=req.postDataJSON();nothing.push(b.nothing);asks=b.nothing?[]:[ask];return route.fulfill({json:{sit_id:m[1],nothing_to_log:b.nothing}})}
   m=p.match(/^\/api\/images\/([^/]+)\/people$/);
   if(m){const b=req.postDataJSON();cleared.push([m[1],b.cleared]);return route.fulfill({json:{id:m[1],people_cleared:b.cleared,has_person:!b.cleared,has_vehicle:false}})}
   if(p==='/api/harvests/export.csv'){
    if(role!=='admin')return route.fulfill({status:403,json:{detail:'Admin privileges required'}});
    return route.fulfill({status:200,headers:{'Content-Type':'text/csv; charset=utf-8','Content-Disposition':'attachment; filename="harvest-2026-27.csv"'},
     body:'﻿Date,Time,Species\n2026-09-26,21:40,Wild boar\n'});
   }
   if(method!=='GET')return route.fulfill({json:{}});
   if(p==='/api/photos'){
    feedAsks.push(u.search);
    const who=u.searchParams.get('people')==='true';
    if(who&&role!=='admin')return route.fulfill({status:403,json:{detail:'Only an admin sees the photos with people or vehicles in them.'}});
    return route.fulfill({json:{items:who?people:feed,next_before:null}});
   }
   const result=p==='/api/auth/me'?{id:'me',email:'pedro@x.es',role}
    :p==='/api/harvests/asks'?(role==='viewer'?[]:asks)
    :p==='/api/harvests'?{season:2026,label:'2026–27',from:'2026-04-01',to:'2027-03-31',seasons:[{season:2026,label:'2026–27'}],items:book,can_export:role==='admin'}
    :p==='/api/species/choices'?choices
    :p==='/api/stands'?[{id:'s1',name:'Puente',lat:39.09,lon:-1.36,claimed_tonight:false,claimed_by:null}]
    :p==='/api/sits'?[]:p==='/api/sits/mine'?{live:[],to_report:[]}
    :p==='/api/photos/filters'?{people:role==='admin'?people.length:null,species:[{id:'wild_boar',common_name:'Wild boar',count:1}],cameras:[{id:'c1',name:'Charca',count:1}]}
    :p==='/api/photos/highlights'?{items:[]}:undefined;
   return result===undefined?route.fulfill({status:404,json:{detail:'Not Found'}}):route.fulfill({json:result});
  });
  return page;
 };

 // ── The morning card on Stands, and the one form ──
 let page=await newPage();
 await page.goto(base+'/stands');
 const card=page.locator('.hv-ask');await card.waitFor();
 assert.equal(await card.locator('h2').innerText(),'You shot at Puente last night');
 const primary=await card.getByRole('button',{name:'Log the animal'}).boundingBox();
 assert.ok(primary.height>=56,`the main action is glove-sized (${primary.height})`);
 assert.ok((await card.getByRole('button',{name:/Nothing to log/}).boundingBox()).height>=44);
 await card.getByRole('button',{name:'Log the animal'}).click();
 const form=page.locator('.hv-form');await form.getByRole('button',{name:'Wild boar'}).waitFor();
 assert.equal(await form.getByRole('button',{name:'Fox'}).count(),0,'small game behind More animals');
 for(const b of await form.locator('.hv-choice').all())assert.ok((await b.boundingBox()).height>=56,'every choice is glove-sized');
 await form.getByRole('button',{name:'Log it'}).click();
 assert.equal(await form.locator('.hv-err').innerText(),'Pick the animal first.');
 await form.getByRole('button',{name:'Wild boar'}).click();
 await form.getByRole('button',{name:'Male',exact:true}).click();
 await form.getByRole('button',{name:'Adult',exact:true}).click();
 await form.getByLabel(/Weight/).fill('heavy');
 await form.getByRole('button',{name:'Log it'}).click();
 assert.match(await form.locator('.hv-err').innerText(),/^The weight is in kilos/);
 await form.getByLabel(/Weight/).fill('78,5');
 await form.getByLabel(/Seal number/).fill('CU-0412');
 // Closed under a glove: all of it is still there.
 await page.getByRole('button',{name:'← Back'}).click();await form.waitFor({state:'detached'});
 await card.getByRole('button',{name:'Log the animal'}).click();await form.waitFor();
 assert.equal(await form.getByLabel(/Seal number/).inputValue(),'CU-0412');
 assert.equal(await form.getByRole('button',{name:'Wild boar'}).getAttribute('aria-pressed'),'true');
 // No signal on the first try: said in words, nothing lost; the next try is the same line.
 post='drop';
 await form.getByRole('button',{name:'Log it'}).click();
 await form.locator('.hv-err').filter({hasText:'No signal, so it wasn’t saved'}).waitFor();
 assert.equal(await form.getByLabel(/Seal number/).inputValue(),'CU-0412');
 post='ok';
 await form.getByRole('button',{name:'Log it'}).click();
 await form.waitFor({state:'detached'});
 assert.equal(await card.locator('.hv-done').innerText(),'Logged: Wild boar, male, adult · seal CU-0412.');
 assert.equal(posts.length,2);
 assert.equal(posts[0].id,posts[1].id,'the second try is the same line');
 assert.deepEqual([posts[1].sit_id,posts[1].weight_kg,posts[1].sex,posts[1].age_class],['sit1',78.5,'male','mature_adult']);
 // Saved, the form's step is off the history: Back leaves Stands, not an empty panel.
 assert.equal(await page.locator('.ov[role="dialog"]').count(),0);
 await page.close();

 // "Nothing to log", and Undo.
 asks=[ask];
 page=await newPage();
 await page.goto(base+'/stands');
 await page.locator('.hv-ask').getByRole('button',{name:/Nothing to log/}).click();
 await page.locator('.hv-done').filter({hasText:'Nothing to log from Puente.'}).waitFor();
 await page.getByRole('button',{name:'Undo'}).click();
 await page.getByRole('button',{name:'Log the animal'}).waitFor();
 assert.deepEqual(nothing,[true,false]);
 await page.close();

 // ── Settings: the member's own lines, the admin's book and its CSV ──
 page=await newPage();
 await page.goto(base+'/settings#harvest');
 const sec=page.locator('#harvest');await sec.locator('.hv-line').first().waitFor();
 assert.equal(await sec.locator('.settings-section-name').innerText(),'Your harvest');
 assert.equal(await sec.getByRole('button',{name:/Download the season/}).count(),0);
 assert.match(await sec.locator('.hv-line').first().innerText(),/Wild boar, male, adult · seal CU-0412/);
 await page.close();
 role='admin';
 page=await newPage();
 await page.goto(base+'/settings#harvest');
 const adm=page.locator('#harvest');await adm.locator('.hv-line').first().waitFor();
 assert.equal(await adm.locator('.settings-section-name').innerText(),'Harvest book');
 const [dl]=await Promise.all([page.waitForEvent('download'),adm.getByRole('button',{name:'Download the season (CSV)'}).click()]);
 assert.equal(dl.suggestedFilename(),'harvest-2026-27.csv');
 assert.ok(fs.readFileSync(await dl.path(),'utf8').includes('Wild boar'));
 await page.close();
 role='viewer';
 page=await newPage();
 await page.goto(base+'/settings');await page.locator('#password').waitFor();
 assert.equal(await page.locator('#harvest').count(),0,'viewers have no harvest book');
 await page.close();

 // ── Photos: People & vehicles, an admin's alone ──
 role='admin';
 page=await newPage();
 await page.goto(base+'/photos');
 const chip=page.locator('.photos-chip--people');await chip.waitFor();
 await chip.click();
 await page.locator('.photos-people-note').waitFor();
 await page.waitForFunction(()=>document.querySelectorAll('.photos-tile').length===2);
 assert.ok(feedAsks.some(q=>q.includes('people=true')&&!q.includes('species=')));
 assert.deepEqual(await page.locator('.photos-tile-label').allInnerTexts(),['Person','Vehicle']);
 await page.locator('.photos-tile').first().click();
 await page.locator('.lb-people-note').waitFor();
 assert.equal(await page.getByRole('button',{name:/Wrong animal/}).count(),0,'no Wrong? on a frame of people');
 assert.equal(await page.locator('.lb-worth').count(),0,'no Worth a look either');
 await page.getByRole('button',{name:/Nobody in it/}).click();
 await page.locator('.lb-toast').filter({hasText:'Marked: nobody in it'}).waitFor();
 await page.locator('.lb-toast').getByRole('button',{name:'Undo'}).click();
 await page.locator('.lb-toast').filter({hasText:'Back with the people and vehicles'}).waitFor();
 assert.deepEqual(cleared,[['p1',true],['p1',false]]);
 await page.getByRole('button',{name:/← Back/}).click();await page.waitForTimeout(300);
 assert.equal(await page.locator('.photos-tile').count(),2,'taken back: it stays in the list');
 await page.close();

 // A member never sees the chip, and an old saved choice doesn't ask for them.
 role='member';feedAsks.length=0;
 page=await newPage(undefined,()=>{localStorage.setItem('gs_token','harvest-fixture');localStorage.setItem('gs.photos.pick',JSON.stringify({species:[],cameras:[],people:true}))});
 await page.goto(base+'/photos');
 await page.locator('.photos-tile').first().waitFor();await page.waitForTimeout(500);
 assert.equal(await page.locator('.photos-chip--people').count(),0);
 assert.equal(await page.locator('.photos-tile').count(),1);
 assert.ok(feedAsks.length>0&&feedAsks.every(q=>!q.includes('people=true')),`never asked for them (${feedAsks})`);
 await page.close();

 assert.deepEqual(errors,[]);
 console.log('harvest-and-people: ok');
 } finally { await browser.close() }
})().catch(e=>{console.error(e);process.exit(1)});
