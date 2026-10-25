// Territory search, map-to-call-list transfer, Clear, stale responses and offline maps.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const script = fs.readFileSync(path.join(__dirname, '../app/static/js/gis_map.js'), 'utf8');
const tick = async () => {for (let i=0;i<12;i++) await new Promise(r=>setImmediate(r));};
function run(provider, {leaflet=true}={}) {
  const nodes = new Map(), requests=[], markers=[], history=[];
  function node() {return {value:'',textContent:'',children:[],events:{},disabled:false,
    append(...items){this.children.push(...items);},addEventListener(name,fn){this.events[name]=fn;}};}
  for(const id of ['state','county','city','zip_code','gis-message','gis-map','gis-form','gis-clear',
    'gis-call-list','total','zip-total','largest','geocode-next','basemap-style']) nodes.set(id,node());
  const map={setView(){return this;},fitBounds(){},removeLayer(){}};
  const L={map:()=>map,tileLayer:()=>({addTo(){return this;}}),
    layerGroup:()=>({addTo(){return this;},clearLayers(){markers.length=0;}}),
    marker:point=>({point,bindPopup(popup){this.popup=popup;return this;},addTo(){markers.push(this);return this;}})};
  const context={document:{getElementById:id=>nodes.get(id),createElement:node},window:{L:leaflet?L:undefined,
    history:{replaceState(_a,_b,url){history.push(url);}}},L,URLSearchParams,AbortController,
    fetch:async (url,options={})=>{requests.push({url,options});return provider(url,options);}};
  vm.runInNewContext(script,context);
  return {nodes,requests,markers,history,submit:()=>nodes.get('gis-form').events.submit({preventDefault(){}})};
}
const response=data=>({ok:true,json:async()=>data});
const dataset=()=>({total:2,zip_count:1,locations:[{zip:'97467',count:2}]});
const pins=()=>({points:[{id:1,name:'<script>Synthetic</script>',address:'123 Example St',status:'New',lat:43.7,lon:-124.1}],pending:1,unmapped:1});
const provider=url=>response(url.startsWith('/gis/summary')?dataset():pins());

test('four-field query reaches both APIs and the call list, with safe contact popups',async()=>{
  const r=run(provider);await tick();
  for(const [id,value] of Object.entries({state:'OR',county:'Douglas',city:'Reedsport',zip_code:'97467'})) r.nodes.get(id).value=value;
  await r.submit();await tick();
  const last=r.requests.slice(-2).map(x=>new URL(x.url,'https://crm.test'));
  for(const u of last) assert.equal(u.searchParams.get('city'),'Reedsport');
  const link=new URL(r.nodes.get('gis-call-list').href,'https://crm.test');
  assert.equal(link.searchParams.get('cities'),'Reedsport');
  assert.equal(link.searchParams.get('states'),'OR');
  assert.equal(r.nodes.get('total').textContent,'2');
  assert.equal(r.markers[0].popup.children[0].textContent,'<script>Synthetic</script>');
  assert.equal(r.markers[0].popup.children.at(-1).href,'/leads/1');
});

test('Clear resets all four fields and sends explicit blank call filters',async()=>{
  const r=run(provider);await tick();
  r.nodes.get('city').value='Reedsport';await r.submit();
  r.nodes.get('gis-clear').events.click();await tick();
  for(const id of ['state','county','city','zip_code']) assert.equal(r.nodes.get(id).value,'');
  const link=new URL(r.nodes.get('gis-call-list').href,'https://crm.test');
  assert.equal(link.searchParams.get('cities'),'');
  assert.equal(link.searchParams.get('states'),'');
  assert.equal(r.requests.at(-1).url,'/gis/points?state=&county=&city=&zip_code=');
});

test('search and call links remain usable without Leaflet',async()=>{
  const r=run(provider,{leaflet:false});await tick();
  assert.equal(r.nodes.get('total').textContent,'2');
  assert.match(r.nodes.get('gis-message').textContent,/Map unavailable/);
  assert.equal(r.nodes.get('geocode-next').disabled,true);
  r.nodes.get('city').value='Boston';r.nodes.get('city').events.input();
  assert.match(r.nodes.get('gis-call-list').href,/cities=Boston/);
});

test('a slower previous search cannot replace the newest result',async()=>{
  let resolvers=[];
  const r=run(()=>new Promise(resolve=>resolvers.push(resolve)));
  r.nodes.get('city').value='Reedsport';const latest=r.submit();
  resolvers[2](response({total:0,zip_count:0,locations:[]}));resolvers[3](response({points:[],pending:0,unmapped:0}));
  await latest;await tick();
  resolvers[0](response(dataset()));resolvers[1](response(pins()));await tick();
  assert.equal(r.nodes.get('total').textContent,'0');
  assert.match(r.nodes.get('gis-message').textContent,/No contacts match/);
});

test('geocoding is scoped to the displayed search',async()=>{
  const r=run(url=>response(url.startsWith('/gis/geocode-batch')?{processed:1,matched:1}:url.startsWith('/gis/summary')?dataset():pins()));
  await tick();r.nodes.get('city').value='Reedsport';await r.submit();
  await r.nodes.get('geocode-next').events.click();await tick();
  const request=r.requests.find(x=>x.url.startsWith('/gis/geocode-batch'));
  assert.equal(request.options.method,'POST');assert.match(request.url,/city=Reedsport/);
});
