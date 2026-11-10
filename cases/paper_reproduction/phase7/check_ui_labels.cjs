// Pure renderer unit test with an HTML-string sink; NOT a browser/screenshot.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert');
const js=fs.readFileSync('app/static/foundation.js','utf8'),code=js.slice(js.indexOf('  function renderGpu(t){'),js.indexOf('  function renderGrid(t){'));
const fixtures=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));let checks=[];
for(const [kind,t] of Object.entries(fixtures)){
 const box={};vm.runInNewContext(code+';renderGpu(t)',{$:()=>box,E:String,isGpu:m=>m?.model_kind==='opt_gpu',t});assert(!box.hidden);assert(box.innerHTML.includes(kind==='calibration'?'无独立验证字段：仅规划一致，不算留出通过':kind==='heldout'?'输入验证字段的静态投影通过':'验证投影未通过'));if(kind==='failed')assert(box.innerHTML.includes('部分结果未接受'));
 checks.push({kind,passed:true});
}
console.log(JSON.stringify({pure_renderer_NOT_browser:true,checks},null,2));
