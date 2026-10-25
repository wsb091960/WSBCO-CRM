/* ZIP-level contact concentration. Coordinates stay cached in the CRM database. */
(() => {
  'use strict';
  const status = document.getElementById('geo-map-status');
  const data = JSON.parse(document.getElementById('call-gis-data').textContent);
  if (!window.L) {
    status.textContent = 'Map library unavailable. Check internet access. ZIP/county totals and call selection still work.';
    return;
  }
  const map = L.map('call-gis-map', {scrollWheelZoom: false}).setView([39.5, -98.35], 4);
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 18, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
  }).on('tileerror', () => {
    document.getElementById('geo-tile-status').textContent = 'Map background unavailable. Mapped ZIP circles and totals are still usable.';
  }).addTo(map);
  const matches = L.layerGroup().addTo(map), selected = L.layerGroup().addTo(map);
  const layerSelect = document.getElementById('geo-layer');
  let complete = 0, failed = 0, conflicts = 0, placed = 0, fitTimer, userMoved = false;
  map.getContainer().addEventListener('pointerdown', () => {userMoved = true;});
  map.getContainer().addEventListener('wheel', () => {userMoved = true;}, {passive: true});
  const resolved = [];
  function active(g) {
    return layerSelect.value === 'matches' ? g.eligible > 0 : layerSelect.value === 'selected' ? g.selected > 0 : g.eligible + g.selected > 0;
  }
  function fit() {
    const points = resolved.filter(r => active(r.group)).map(r => [r.location.lat, r.location.lon]);
    if (points.length) map.fitBounds(L.latLngBounds(points).pad(0.18), {maxZoom: 11});
  }
  layerSelect.addEventListener('change', () => {
    for (const [name, layer] of [['matches', matches], ['selected', selected]]) {
      if (layerSelect.value === 'all' || layerSelect.value === name) layer.addTo(map);
      else map.removeLayer(layer);
    }
    fit();
  });
  function popup(g, loc) {
    // Use DOM text nodes for every CRM value; never interpret contact data as HTML.
    const box = document.createElement('div');
    const title = document.createElement('strong');
    title.textContent = `${g.zip} · ${loc.place}, ${loc.state}`;
    box.append(title);
    for (const text of [`Eligible search matches: ${g.eligible}`, `Saved calls: ${g.selected} (${g.pending} pending)`, 'Approximate ZIP center']) {
      const line = document.createElement('div'); line.textContent = text; box.append(line);
    }
    const link = document.createElement('a');
    link.href = '/call-list?' + new URLSearchParams({states: loc.state, counties: '', cities: '', zips: g.zip});
    link.textContent = 'Select this ZIP for the next list';
    box.append(link);
    return box;
  }
  function draw(g, loc) {
    const point = [loc.lat, loc.lon];
    if (g.eligible) L.circleMarker(point, {radius: 7 + Math.min(23, 3 * Math.sqrt(g.eligible)), color: '#146342', fillColor: '#237d51', fillOpacity: 0.48, weight: 2})
      .bindPopup(() => popup(g, loc)).bindTooltip(`${g.zip}: ${g.eligible} eligible`, {className: 'geo-zip-label'}).addTo(matches);
    if (g.selected) L.circleMarker(point, {radius: 6 + Math.min(12, 2 * Math.sqrt(g.selected)), color: '#715000', fillColor: '#e4b443', fillOpacity: 0.92, weight: 2})
      .bindPopup(() => popup(g, loc)).bindTooltip(`${g.zip}: ${g.selected} saved calls`, {className: 'geo-zip-label'}).addTo(selected);
  }
  const requests = new Map();
  function locate(zip) {
    if (!requests.has(zip)) requests.set(zip, (async () => {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 10000);
      try {
        const response = await fetch('/call-list/gis/zip/' + encodeURIComponent(zip), {signal: controller.signal, headers: {'Accept': 'application/json'}});
        if (!response.ok) throw new Error('ZIP lookup failed');
        const loc = await response.json();
        if (!Number.isFinite(loc.lat) || !Number.isFinite(loc.lon)) throw new Error('Invalid coordinates');
        return loc;
      } finally {clearTimeout(timeout);}
    })());
    return requests.get(zip);
  }
  function updateStatus() {
    status.textContent = `${placed} of ${data.groups.length} ZIP/state groups mapped. ${failed} lookup failures; ${conflicts} ZIP/state conflicts omitted.` +
      (complete < data.groups.length ? ` Locating ZIPs… ${complete}/${data.groups.length}.` : ' Use the filters to narrow the area; reload to retry failed lookups.');
  }
  let cursor = 0;
  async function worker() {
    while (cursor < data.groups.length) {
      const g = data.groups[cursor++];
      try {
        const loc = await locate(g.zip);
        if (g.state && loc.state !== g.state) conflicts++;
        else {draw(g, loc); resolved.push({group: g, location: loc}); placed++;}
      } catch (_) {failed++;}
      complete++; updateStatus();
      // Fit after a short pause without constantly moving the map as ZIPs resolve.
      clearTimeout(fitTimer); fitTimer = setTimeout(() => {if (!userMoved) fit();}, 600);
    }
  }
  if (!data.groups.length) {
    status.textContent = 'No ZIP groups to map. Adjust the search or add valid ZIP codes to your contacts.';
  } else {
    updateStatus(); Promise.all([worker(), worker()]);
  }
})();
