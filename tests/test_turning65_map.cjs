const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const script=fs.readFileSync(path.join(__dirname,'../app/static/js/turning65_map.js'),'utf8');
const tick=async()=>{for(let i=0;i<8;i++)await new Promise(r=>setImmediate(r));};
function node(){return {textContent:'',value:'light',children:[],events:{},attrs:{},disabled:false,
 append(...children){this.children.push(...children);},addEventListener(k,f){this.events[k]=f;},setAttribute(k,v){this.attrs[k]=v;}};}
function run({layer='population',leaflet=true,mismatch=false,reject=false,territory=false,overlay,measure='count',missingIncome=false}={}){
 const nodes=new Map();for(const id of ['t65-esri-map','t65-map-status','t65-basemap','t65-fit-state','t65-fit-county','t65-map-config'])nodes.set(id,node());
 const counties=[{id:'48029',name:'Bexar',value:21564,share:1,in_scope:true,url:'/turning65?state=TX&county=48029'},
  {id:'48201',name:'Harris',value:40000,share:.9,in_scope:false,url:'/turning65?state=TX&county=48201'}];
 const config={state:'TX',selected:'48029',layer,metric_label:'Residents age 64',measure:'count',
  features_url:'/ma-map/counties.geojson?state=TX',thresholds:[500,2000,10000,20000],counties,
  points:[{name:'<img src=x onerror=alert(1)>',turns65:'2027-01-01',lat:29.4,lon:-98.5,url:'/leads/1'}],point_total:1};
 if(overlay){config.overlay=overlay;config.measure=measure;config.palette=['a','b','c','d','e'];config.thresholds=[50000,65000,80000,100000];config.bubble_scale=measure==='share'?5:100000;counties[0].income=missingIncome?null:72500;counties[0].shade_value=counties[0].income;}
 if(territory){config.outside_label='Outside selected territory filters';counties[0].details=['21,564 residents age 64','3 CRM contacts · 1 recently worked','<img src=x>'];}
 nodes.get('t65-map-config').textContent=JSON.stringify(config);
 const features=counties.map(c=>({properties:{id:c.id}}));if(mismatch)features.pop();
 const requests=[],navigation=[],outlines=[],markers=[],tiles=[];
 const map={setView(){return this;},fitBounds(){},removeLayer(){}};
 const L={map:()=>map,tileLayer:()=>{const t={on(k,f){this[k]=f;return this;},addTo(){return this;}};tiles.push(t);return t;},
  geoJSON(data,options){
   const group={addTo(){outlines.forEach(l=>l.events.add?.());return this;},getBounds(){return [];},
    setStyle(style){outlines.forEach(l=>l.style=style(l.feature));},resetStyle(l){l.style=options.style(l.feature);}};
   for(const f of data.features){const element=node();const l={feature:f,events:{},style:options.style(f),
    bindTooltip(t){this.tooltip=t;},on(k,fn){this.events[k]=fn;},getElement(){return element;},
    setStyle(s){this.style={...this.style,...s};},bringToFront(){},getBounds(){return {getCenter:()=>[29.4,-98.5]};},openTooltip(){},closeTooltip(){}};
    options.onEachFeature(f,l);outlines.push(l);}
   return group;
  },circleMarker(point,style){const m={point,style,bindPopup(p){this.popup=p;return this;},addTo(){markers.push(this);return this;}};return m;}};
 vm.runInNewContext(script,{document:{getElementById:id=>nodes.get(id),createElement:node},
  window:{L:leaflet?L:undefined,location:{assign:url=>navigation.push(url)}},L,
  fetch:async(url,options)=>{requests.push({url,options});return {ok:!reject,json:async()=>({type:'FeatureCollection',features})};}});
 return {nodes,navigation,outlines,markers,tiles,requests};
}
test('county heat colors match thresholds, selected area and keyboard navigation',async()=>{
 const r=run();await tick();
 assert.equal(r.requests[0].options.credentials,'same-origin');
 assert.equal(r.outlines[0].style.fillColor,'#9b342d');
 assert.equal(r.outlines[1].style.fillColor,'#d3dce1');
 assert.equal(r.outlines[0].style.weight,3);
 r.outlines[0].events.click();
 r.outlines[0].getElement().events.keydown({key:'Enter'});
 assert.equal(r.navigation.length,2);assert.match(r.navigation[0],/county=48029/);
 assert.equal(r.outlines[1].events.click,undefined);
 assert.equal(r.markers.length,0);
 assert.match(r.outlines[0].tooltip.children[1].textContent,/21,564/);
});
test('birthday locations use text-only popups and contact links',async()=>{
 const r=run({layer:'contacts'});await tick();
 assert.equal(r.markers.length,1);
 assert.equal(r.markers[0].popup.children[0].textContent,'<img src=x onerror=alert(1)>');
 assert.equal(r.markers[0].popup.children.at(-1).href,'/leads/1');
 assert.match(r.nodes.get('t65-map-status').textContent,/1 of 1 verified/);
});
test('territory tooltips expose aggregate counts and use territory filter labels safely',async()=>{
 const r=run({territory:true});await tick();
 assert.equal(r.outlines[0].tooltip.children[2].textContent,'21,564 residents age 64');
 assert.equal(r.outlines[0].tooltip.children[3].textContent,'3 CRM contacts · 1 recently worked');
 assert.equal(r.outlines[0].tooltip.children[4].textContent,'<img src=x>');
 assert.equal(r.outlines[1].tooltip.children[1].textContent,'Outside selected territory filters');
});
test('missing Leaflet preserves county selection and table fallback',async()=>{
 const r=run({leaflet:false});await tick();
 assert.equal(r.requests.length,0);
 assert.equal(r.nodes.get('t65-fit-state').disabled,true);
 assert.match(r.nodes.get('t65-map-status').textContent,/outline view/);
});
test('mismatched boundaries and denied requests cannot display misleading totals',async()=>{
 for(const options of [{mismatch:true},{reject:true}]){
  const r=run(options);await tick();assert.equal(r.outlines.length,0);
  assert.equal(r.nodes.get('t65-fit-county').disabled,true);
  assert.match(r.nodes.get('t65-map-status').textContent,/could not load/);
 }
});
test('tile outages leave county interactions intact',async()=>{
 const r=run();await tick();r.tiles[0].tileerror();
 assert.match(r.nodes.get('t65-map-status').textContent,/boundaries still work/);
 r.outlines[0].events.click();assert.equal(r.navigation.length,1);
 r.nodes.get('t65-basemap').value='satellite';r.nodes.get('t65-basemap').events.change();
 assert.equal(r.outlines[1].style.color,'#ffffff');
});
test('filter changes clear incompatible plans and custom dates stay explicit',()=>{
 const form=node(),plan=node(),county=node(),birthday=node(),dates=node(),insurer=node();
 plan.value='old-plan';county.value='48029';birthday.value='6';dates.hidden=true;
 form.querySelectorAll=()=>[insurer];
 const nodes={'t65-filters':form,'t65-plan':plan,'t65-county':county,'t65-window':birthday,'t65-custom-dates':dates};
 vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../app/static/js/turning65.js'),'utf8'),{
  document:{getElementById:id=>nodes[id]}});
 insurer.events.change();assert.equal(plan.value,'');assert.equal(county.value,'');
 birthday.value='custom';birthday.events.change();assert.equal(dates.hidden,false);
 birthday.value='12';birthday.events.change();assert.equal(dates.hidden,true);
});

test('income colors and missing data use income independently from the age count',async()=>{
 const r=run({overlay:'income'});await tick();
 assert.equal(r.outlines[0].style.fillColor,'c');
 assert.match(r.outlines[0].tooltip.children[1].textContent, /\$72,500/);
 assert.equal(r.markers.length,0);
 const missing=run({overlay:'income',missingIncome:true});await tick();
 assert.equal(missing.outlines[0].style.fillColor,'#a5b3bc');
 assert.match(missing.outlines[0].tooltip.children[1].textContent,/unavailable/);
});
test('both overlays shade income and size noninteractive county circles by chosen age measure',async()=>{
 for(const measure of ['count','share']){
  const r=run({overlay:'both',measure});await tick();
  assert.equal(r.outlines[0].style.fillColor,'c');
  assert.equal(r.markers.length,1); // excluded counties have no age bubble
  assert.equal(r.markers[0].style.interactive,false); // underlying county remains clickable
  const value=measure==='share'?1:21564,scale=measure==='share'?5:100000;
  assert.equal(r.markers[0].style.radius,32*Math.sqrt(value/scale));
  r.outlines[0].events.click();assert.equal(r.navigation.length,1);
 }
});
