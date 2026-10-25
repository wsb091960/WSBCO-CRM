/* ZIP-only aggregate map: never send personal contact details to a third party. */
(() => {
  const map = L.map('gis-map').setView([43.5, -123.5], 7);
  // Public Esri raster services. No credential is embedded in client-side code.
  // These provide a usable selector until authenticated Basemap Styles is configured.
  const esri = 'https://server.arcgisonline.com/ArcGIS/rest/services/';
  const layers = {
    streets: L.tileLayer(esri + 'World_Street_Map/MapServer/tile/{z}/{y}/{x}', {maxZoom: 18, attribution: 'Tiles &copy; Esri'}),
    navigation: L.tileLayer(esri + 'World_Transportation/MapServer/tile/{z}/{y}/{x}', {maxZoom: 18, attribution: 'Tiles &copy; Esri'}),
    light: L.tileLayer(esri + 'Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}', {maxZoom: 16, attribution: 'Tiles &copy; Esri'}),
    satellite: L.tileLayer(esri + 'World_Imagery/MapServer/tile/{z}/{y}/{x}', {maxZoom: 18, attribution: 'Imagery &copy; Esri'})
  };
  let activeBasemap = layers.streets.addTo(map);
  const layerSelect = document.getElementById('basemap-style');
  layerSelect.addEventListener('change', () => {
    const next = layers[layerSelect.value];
    if (!next || next === activeBasemap) return;
    map.removeLayer(activeBasemap);
    activeBasemap = next.addTo(map);
  });
  const layer = L.layerGroup().addTo(map);
  const addressLayer = L.layerGroup().addTo(map);
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
    addressLayer.clearLayers();
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
      const pointResponse = await fetch('/gis/points?' + qs.toString(), {credentials:'same-origin'});
      if (!pointResponse.ok) throw Error('Owner sign-in required for individual address pins (' + pointResponse.status + ')');
      const individual = await pointResponse.json();
      const byLocation = new Map();
      individual.points.forEach(point => {
        const key = point.lat.toFixed(7) + ',' + point.lon.toFixed(7);
        if (!byLocation.has(key)) byLocation.set(key, []);
        byLocation.get(key).push(point);
      });
      for (const entries of byLocation.values()) {
        const first = entries[0];
        const marker = L.marker([first.lat, first.lon]).addTo(addressLayer);
        const popup = document.createElement('div');
        entries.forEach((point, index) => {
          if (index) popup.append(document.createElement('hr'));
          const title = document.createElement('strong');
          title.textContent = point.name || 'Contact';
          const details = document.createElement('p');
          details.textContent = point.address + ' · ' + point.status;
          popup.append(title, details);
        });
        marker.bindPopup(popup);
        bounds.push([first.lat, first.lon]);
      }
      if (bounds.length) map.fitBounds(bounds, {padding:[35,35],maxZoom:16});
      message.textContent = individual.points.length + ' individual contact pins loaded; ' + individual.unmapped + ' not yet mapped. Use Geocode next 20 addresses to add more.';
      return;
      /* Legacy ZIP markers retained below for reference but no longer displayed. */
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
