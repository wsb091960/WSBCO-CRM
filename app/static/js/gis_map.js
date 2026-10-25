/* Same geographic selection for the territory map and manual call list. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const fields = ['state', 'county', 'city', 'zip_code'];
  const message = $('gis-message');
  let map, addressLayer, activeBasemap, lastQuery = '', loadNumber = 0, controller;
  const layers = {};

  if (window.L) {
    map = L.map('gis-map').setView([43.5, -123.5], 7);
    const esri = 'https://server.arcgisonline.com/ArcGIS/rest/services/';
    for (const [name, path, maxZoom] of [
      ['streets', 'World_Street_Map', 18], ['navigation', 'World_Transportation', 18],
      ['light', 'Canvas/World_Light_Gray_Base', 16], ['satellite', 'World_Imagery', 18]
    ]) {
      layers[name] = L.tileLayer(esri + path + '/MapServer/tile/{z}/{y}/{x}', {
        maxZoom, attribution: 'Tiles &copy; Esri'
      });
    }
    activeBasemap = layers.streets.addTo(map);
    addressLayer = L.layerGroup().addTo(map);
    $('basemap-style').addEventListener('change', () => {
      const next = layers[$('basemap-style').value];
      if (!next || next === activeBasemap) return;
      map.removeLayer(activeBasemap);
      activeBasemap = next.addTo(map);
    });
  } else {
    $('gis-map').textContent = 'Map unavailable. Search and the 10-call list still work.';
    $('basemap-style').disabled = true;
  }

  function query() {
    return new URLSearchParams(fields.map(id => [id, $(id).value.trim()]));
  }

  function callListLink(qs) {
    $('gis-call-list').href = '/call-list?' + new URLSearchParams({
      states: qs.get('state'), counties: qs.get('county'),
      cities: qs.get('city'), zips: qs.get('zip_code')
    });
  }

  function draw(points) {
    if (!map) return;
    const groups = new Map();
    for (const point of points) {
      if (!Number.isFinite(point.lat) || !Number.isFinite(point.lon)) continue;
      const key = point.lat.toFixed(7) + ',' + point.lon.toFixed(7);
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(point);
    }
    const bounds = [];
    for (const entries of groups.values()) {
      const first = entries[0], popup = document.createElement('div');
      for (const [index, point] of entries.entries()) {
        if (index) popup.append(document.createElement('hr'));
        const title = document.createElement('strong');
        title.textContent = point.name || 'Contact ' + point.id;
        const address = document.createElement('p');
        address.textContent = point.address || 'Address unavailable';
        const status = document.createElement('p');
        status.textContent = point.status || 'Status not specified';
        const precision = document.createElement('small');
        precision.textContent = point.precision || '';
        const link = document.createElement('a');
        link.href = '/leads/' + encodeURIComponent(point.id);
        link.textContent = 'Open contact';
        popup.append(title, address, status);
        if (point.precision) popup.append(precision, document.createElement('br'));
        popup.append(link);
      }
      L.marker([first.lat, first.lon]).bindPopup(popup).addTo(addressLayer);
      bounds.push([first.lat, first.lon]);
    }
    if (bounds.length) map.fitBounds(bounds, {padding: [35, 35], maxZoom: 16});
  }

  async function refresh(event) {
    if (event) event.preventDefault();
    const current = ++loadNumber;
    if (controller) controller.abort();
    controller = new AbortController();
    const qs = query();
    lastQuery = qs.toString();
    callListLink(qs);
    window.history.replaceState(null, '', '/gis?' + lastQuery);
    if (addressLayer) addressLayer.clearLayers();
    for (const id of ['total', 'zip-total', 'largest']) $(id).textContent = '—';
    message.textContent = 'Loading matching contacts…';
    try {
      const responses = await Promise.all(['/gis/summary?', '/gis/points?'].map(path =>
        fetch(path + lastQuery, {credentials: 'same-origin', signal: controller.signal, cache: 'no-store'})));
      for (const response of responses) {
        if (!response.ok) {
          const error = await response.json().catch(() => ({}));
          throw Error(typeof error.detail === 'string' ? error.detail : 'Unable to load contacts (' + response.status + ')');
        }
      }
      const [data, individual] = await Promise.all(responses.map(response => response.json()));
      if (current !== loadNumber) return;
      $('total').textContent = data.total.toLocaleString();
      $('zip-total').textContent = data.zip_count.toLocaleString();
      const top = data.locations.reduce((best, item) => !best || item.count > best.count ? item : best, null);
      $('largest').textContent = top ? top.zip + ' (' + top.count + ')' : '—';
      draw(individual.points);
      message.textContent = !data.total ? 'No contacts match. Change a field or click Clear.' :
        data.total + ' matching contacts; ' + individual.points.length + ' mapped; ' + individual.unmapped + ' not yet mapped.' +
        (map ? '' : ' Map unavailable; search and calling still work.');
    } catch (error) {
      if (current !== loadNumber || error.name === 'AbortError') return;
      message.textContent = 'Unable to search: ' + error.message;
    }
  }

  $('gis-clear').addEventListener('click', () => {
    fields.forEach(id => {$(id).value = '';});
    refresh();
  });
  $('gis-form').addEventListener('submit', refresh);
  fields.forEach(id => $(id).addEventListener('input', () => callListLink(query())));
  refresh();
})();
