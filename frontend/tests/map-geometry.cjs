const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),ts=require('typescript');
const compiled=ts.transpileModule(fs.readFileSync('src/map/geometry.ts','utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText;
const context={exports:{}};vm.runInNewContext(compiled,context);const {windGeometry,downwind,distanceM,bearingDeg,areaM2,formatDistance,formatArea,measureLabel,validLngLat,direction,isNewCorner,nearFirstCorner,crossesItself}=context.exports;
for(const bearing of [0,45,90,135,180,225,270,315]) {
 const stand={lat:39,lon:-1.3,wind:{status:'clean',source:'synoptic',scent_bearing:bearing,range_m:300}};
 const g=windGeometry(stand,300);const shaft=g.arrow.coordinates[0],head=g.arrow.coordinates[1],tip=shaft[1];
 const angle=(Math.atan2((tip[0]+1.3)*Math.cos(39*Math.PI/180),tip[1]-39)*180/Math.PI+360)%360;
 assert.ok(Math.abs(angle-bearing)<.001,`Arrow shaft follows bearing ${bearing}`);
 assert.deepEqual(Array.from(head[1]),Array.from(tip));
 const center=[(head[0][0]+head[2][0])/2,(head[0][1]+head[2][1])/2];
 const facing=(Math.atan2((tip[0]-center[0])*Math.cos(tip[1]*Math.PI/180),tip[1]-center[1])*180/Math.PI+360)%360;
 assert.ok(Math.min(Math.abs(facing-bearing),360-Math.abs(facing-bearing))<.001,`Arrow head aligned at ${bearing}`);
 assert.equal(windGeometry({...stand,wind:{...stand.wind,source:'unknown'}},300),null);
}
assert.equal(downwind(315),135);
// Measure: one degree of latitude is about 111.2 km; a point due north-east reads "north-east".
assert.ok(Math.abs(distanceM([-1.36,39],[-1.36,40])-111195)<50,'a degree of latitude');
assert.ok(Math.abs(distanceM([-1.36,39.0947],[-1.3584,39.0947])-138)<1.5,'138 m along the parallel at the estate');
for(const [deg,word] of [[0,'north'],[45,'north-east'],[90,'east'],[180,'south'],[270,'west'],[315,'north-west']]){
 const r=deg*Math.PI/180,b=[-1.36+Math.sin(r)*.001/Math.cos(39.09*Math.PI/180),39.09+Math.cos(r)*.001];
 assert.ok(Math.abs(((bearingDeg([-1.36,39.09],b)-deg+540)%360)-180)<.5,`bearing ${deg}`);assert.equal(direction(bearingDeg([-1.36,39.09],b)),word);
}
assert.match(measureLabel([-1.36,39.09],[-1.3588,39.0909]),/^\d+ m · north-east$/);
// Area: a 100 m square is one hectare; order of corners does not matter.
const dLat=100/111195,dLon=100/(111195*Math.cos(39.09*Math.PI/180));
const sq=[[-1.36,39.09],[-1.36+dLon,39.09],[-1.36+dLon,39.09+dLat],[-1.36,39.09+dLat]];
assert.ok(Math.abs(areaM2(sq)-10000)<30,'one hectare');assert.ok(Math.abs(areaM2([...sq].reverse())-areaM2(sq))<1e-6);assert.equal(areaM2(sq.slice(0,2)),0);
assert.equal(formatArea(124000),'12.4 ha');assert.equal(formatArea(850),'850 m²');assert.equal(formatDistance(134.4),'134 m');assert.equal(formatDistance(1234),'1.2 km');
assert.equal(validLngLat(-1.3,39),true);assert.equal(validLngLat(-1.3,1000),false);assert.equal(validLngLat(null,39),false);assert.equal(validLngLat(NaN,39),false);
// Drawing: a double press lays one corner (B-12/B-13), and a bow-tie is not an area (B-10).
const m=1/111195;
assert.equal(isNewCorner([],[-1.36,39.09]),true);
assert.equal(isNewCorner([[-1.36,39.09]],[-1.36,39.09+.5*m]),false,'half a metre from the last corner is the same corner');
assert.equal(isNewCorner([[-1.36,39.09]],[-1.36,39.09+3*m]),true);
assert.equal(isNewCorner(sq.slice(0,3),[sq[0][0],sq[0][1]+.3*m]),false,'back on the first corner is Finish shape, not a corner');
assert.equal(nearFirstCorner(sq.slice(0,3),sq[0]),true);assert.equal(nearFirstCorner(sq.slice(0,2),sq[0]),false);assert.equal(nearFirstCorner(sq.slice(0,3),null),false);
assert.equal(crossesItself(sq),false,'a square');assert.equal(crossesItself([sq[0],sq[1],sq[3],sq[2]]),true,'a bow-tie');
assert.equal(crossesItself([sq[0],sq[1],sq[3],sq[2]],false),false,'open, it only crosses once closed');
assert.equal(crossesItself([sq[0],sq[1],sq[3],sq[2],[-1.36+dLon/2,39.09-dLat/2]],false),true,'the path itself crosses');
assert.equal(crossesItself(sq.slice(0,3)),false,'a triangle never crosses');
console.log('PASS: drawing guards (repeat corners, closing, self-crossing outlines).');
console.log('PASS: all eight compass directions, arrowhead/shaft alignment, uncertain wind suppressed, measuring distances, directions and areas.');
