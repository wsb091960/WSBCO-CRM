// Map-controller regression tests. Run: node --test tests/test_call_list_gis_js.cjs
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const script = fs.readFileSync(path.join(__dirname, '../app/static/js/call_list_gis.js'), 'utf8');

async function run(groups, provider, hasLeaflet = true) {
  const nodes = new Map(), markers = [], layers = [], lookups = [];
  function node(tag = 'div') {return {tag, textContent: '', children: [], events: {}, value: 'all',
    append(child) {this.children.push(child);}, addEventListener(name, callback) {this.events[name] = callback;}};}
  for (const id of ['geo-map-status', 'geo-tile-status', 'geo-layer', 'call-gis-data']) nodes.set(id, node());
  nodes.get('call-gis-data').textContent = JSON.stringify({groups});
  const container = node();
  const map = {setView() {return this;}, getContainer() {return container;},
    fitBounds() {}, removeLayer(layer) {layer.visible = false;}};
  const L = {map: () => map, tileLayer: () => ({on() {return this;}, addTo() {return this;}}),
    layerGroup: () => {const layer = {visible: false, addTo() {this.visible = true; return this;}}; layers.push(layer); return layer;},
    circleMarker: (point, options) => {
      const marker = {point, options, bindPopup(fn) {this.popup = fn;return this;}, bindTooltip() {return this;},
        addTo(layer) {this.layer = layer;return this;}};
      markers.push(marker); return marker;
    }, latLngBounds: points => ({pad: () => points})};
  const document = {getElementById: id => nodes.get(id), createElement: node};
  const context = {document, window: {L: hasLeaflet ? L : undefined}, L, AbortController, URLSearchParams,
    setTimeout: () => 1, clearTimeout() {}, fetch: async url => {
      lookups.push(url);
      const location = provider(url);
      return {ok: !!location, json: async () => location};
    }};
  vm.runInNewContext(script, context);
  for (let i = 0; i < 8; i++) await new Promise(resolve => setImmediate(resolve));
  return {nodes, markers, layers, lookups};
}

const g = (fields = {}) => ({state:'OR', zip:'97467', eligible:7, selected:3, pending:2, ...fields});
const location = {state:'OR', place:'Reedsport', lat:43.7104, lon:-123.9565};

test('draws search and saved circles, safe popup, ZIP selection and layer controls', async () => {
  const r = await run([g()], () => location);
  assert.equal(r.markers.length, 2);
  assert.match(r.nodes.get('geo-map-status').textContent, /1 of 1 ZIP\/state groups mapped/);
  const popup = r.markers[0].popup();
  assert.equal(popup.children[0].textContent, '97467 · Reedsport, OR');
  assert.match(popup.children.at(-1).href, /states=OR&counties=&cities=&zips=97467/);
  const select = r.nodes.get('geo-layer');
  select.value = 'selected'; select.events.change();
  assert.equal(r.layers[0].visible, false);
  assert.equal(r.layers[1].visible, true);
});

test('reports failed ZIPs and state conflicts without drawing misleading circles', async () => {
  const r = await run([g({state:'WA'}), g({zip:'00000'})], url => url.endsWith('00000') ? null : location);
  assert.equal(r.markers.length, 0);
  assert.match(r.nodes.get('geo-map-status').textContent, /1 lookup failures; 1 ZIP\/state conflicts/);
});

test('deduplicates ZIP requests and treats external place names as text', async () => {
  const r = await run([g(), g({state:''})], () => ({...location, place:'<script>alert(1)</script>'}));
  assert.equal(r.lookups.length, 1);
  assert.equal(r.markers[0].popup().children[0].textContent, '97467 · <script>alert(1)</script>, OR');
});

test('handles empty results and map-library outages', async () => {
  const empty = await run([], () => location);
  assert.match(empty.nodes.get('geo-map-status').textContent, /No ZIP groups/);
  const unavailable = await run([g()], () => location, false);
  assert.equal(unavailable.lookups.length, 0);
  assert.match(unavailable.nodes.get('geo-map-status').textContent, /Map library unavailable/);
});
