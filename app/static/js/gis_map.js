/* ZIP-only aggregate map: never send personal contact details to a third party. */
(() => {
  const map = L.map('gis-map').setView([43.5, -123.5], 7);
  L.tileLayer('https://tile.openstreetmap.fr/hot/{z}/{x}/{y}.png', {
    maxZoom: 18, attribution: '&copy; OpenStreetMap contributors, HOT'
  }).addTo(map);
  const layer = L.layerGroup().addTo(map);
  const cache = new Map();
  const $ = id => document.getElementById(id);
  const message = $('gis-message');
  async function locate(zip, state) {
    const key = zip + ':' + state;
    if (cache.has(key)) return cache.get(key);
    try {
      const response = await fetch('https://api.zippopotam.us/us/' + encodeURIComponent(zip));
      if (!response.ok) return null;
      const data = await response.json();
      const places = data.places || [];
      const place = places.find(p => (p['state abbreviation'] || '').toUpperCase() === state) || places[0];
      if (!place) return null;
      const coords = [Number(place.latitude), Number(place.longitude)];
      if (!coords.every(Number.isFinite)) return null;
      cache.set(key, coords);
      return coords;
    } catch (_) { return null; }
  }
  async function refresh(e) {
    if (e) e.preventDefault();
    layer.clearLayers();
    message.textContent = 'Loading ZIP-level contact counts…';
    const qs = new URLSearchParams();
    ['state','county','zip_code','mode','status'].forEach(id => {
      const val = $(id).value.trim();
      if (val) qs.set(id, val);
    });
    try {
      const response = await fetch('/gis/summary?' + qs.toString(), {credentials:'same-origin'});
      if (!response.ok) throw Error('Server returned ' + response.status);
      const data = await response.json();
      $('total').textContent = data.total.toLocaleString();
      $('zip-total').textContent = data.zip_count.toLocaleString();
      const max = Math.max(0, ...data.locations.map(x => x.count));
      const top = data.locations.find(x => x.count === max);
      $('largest').textContent = top ? top.zip + ' (' + top.count + ')' : '—';
      const bounds = [];
      let mapped = 0;
      // Avoid overloading the public ZIP lookup API.
      for (const item of data.locations.slice(0, 120)) {
        const coords = await locate(item.zip, item.state);
        if (!coords) continue;
        const marker = L.circleMarker(coords, {
          radius: Math.min(29, 6 + Math.sqrt(item.count) * 3),
          color:'#b78a2d', weight:2, fillColor:'#185b42', fillOpacity:.68
        }).addTo(layer);
        const popup = document.createElement('div');
        const heading = document.createElement('strong');
        heading.textContent = item.zip + ', ' + item.state;
        const info = document.createElement('p');
        info.textContent = item.count + ' contacts · ' + (item.counties.join(', ') || 'County not specified');
        popup.append(heading, info);
        marker.bindPopup(popup);
        bounds.push(coords); mapped++;
      }
      if (bounds.length) map.fitBounds(bounds, {padding:[35,35],maxZoom:10});
      message.textContent = data.total
        ? mapped + ' of ' + data.zip_count + ' ZIP areas plotted. ' + (data.zip_count > 120 ? 'Showing first 120 ZIP areas.' : '')
        : 'No contacts match these filters.';
    } catch (err) { message.textContent = 'Unable to load GIS data: ' + err.message; }
  }
  $('gis-form').addEventListener('submit', refresh);
  refresh();
})();
