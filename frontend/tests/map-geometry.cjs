const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),ts=require('typescript');
const compiled=ts.transpileModule(fs.readFileSync('src/map/geometry.ts','utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText;
const context={exports:{}};vm.runInNewContext(compiled,context);const {windGeometry,downwind}=context.exports;
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
assert.equal(downwind(315),135);console.log('PASS: all eight compass directions, arrowhead/shaft alignment, uncertain wind suppressed.');
