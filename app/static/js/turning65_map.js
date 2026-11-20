// County totals and private birthday locations. No Census/provider lookup at runtime.
(() => {
  'use strict';
  const root = document.getElementById('t65-esri-map');
  if (!root) return;
  const status = document.getElementById('t65-map-status');
  const basemap = document.getElementById('t65-basemap');
  const fitState = document.getElementById('t65-fit-state');
  const fitCounty = document.getElementById('t65-fit-county');
  const config = JSON.parse(document.getElementById('t65-map-config').textContent);
  const message = text => { status.textContent = text + ' The county selector, outline view and ranked county table remain available.'; };
  if (!window.L) {
    root.textContent = 'Interactive map unavailable.';
    [basemap, fitState, fitCounty].forEach(control => { control.disabled = true; });
    message('Map resources could not load.');
    return;
  }
  const map = L.map(root, {scrollWheelZoom: false}).setView([39, -98], 4);
  const palette = ['#f4e7d5', '#edc393', '#e69b5d', '#cf6342', '#9b342d'];
  const meta = new Map(config.counties.map(c => [c.id, c]));
  const format = new Intl.NumberFormat('en-US');
  let outlines, selectedLayer, active, tileFailed = false;
  const background = 'https://server.arcgisonline.com/ArcGIS/rest/services/';
  const layers = {};
  for (const [name, path, maxZoom] of [['light', 'Canvas/World_Light_Gray_Base', 16],
    ['streets', 'World_Street_Map', 18], ['satellite', 'World_Imagery', 18]]) {
    layers[name] = L.tileLayer(background + path + '/MapServer/tile/{z}/{y}/{x}', {
      maxZoom, attribution: 'Tiles &copy; Esri &mdash; Esri, HERE, Garmin, USGS, NOAA, contributors'
    });
    layers[name].on('tileerror', () => {
      tileFailed = true;
      message('Some map tiles are unavailable. County boundaries still work.');
    });
  }
  active = layers.light.addTo(map);
  const style = feature => {
    const c = meta.get(feature.properties.id);
    const value = config.measure === 'share' ? c.share : c.value;
    const bucket = config.thresholds.filter(threshold => value >= threshold).length;
    return {color: c.id === config.selected ? '#153d50' : basemap.value === 'satellite' ? '#ffffff' : '#647b86',
      weight: c.id === config.selected ? 3 : .8,
      fillColor: !c.in_scope ? '#d3dce1' : c.value === null ? '#a5b3bc' : palette[bucket],
      fillOpacity: !c.in_scope ? .4 : .82};
  };
  basemap.addEventListener('change', () => {
    const next = layers[basemap.value];
    if (!next || next === active) return;
    map.removeLayer(active);
    active = next.addTo(map);
    if (outlines) outlines.setStyle(style);
  });
  fitState.addEventListener('click', () => { if (outlines) map.fitBounds(outlines.getBounds(), {padding: [15, 15]}); });
  fitCounty.addEventListener('click', () => { if (selectedLayer) map.fitBounds(selectedLayer.getBounds(), {padding: [25, 25], maxZoom: 11}); });
  fetch(config.features_url, {credentials: 'same-origin'})
    .then(response => { if (!response.ok) throw Error('County map unavailable'); return response.json(); })
    .then(data => {
      if (data.type !== 'FeatureCollection' || data.features.length !== meta.size ||
          new Set(data.features.map(f => f.properties.id)).size !== meta.size ||
          data.features.some(f => !meta.has(f.properties.id))) throw Error('County boundary mismatch');
      outlines = L.geoJSON(data, {style, onEachFeature(feature, layer) {
        const c = meta.get(feature.properties.id);
        const box = document.createElement('div');
        const title = document.createElement('strong'); title.textContent = c.name + ' County';
        const value = document.createElement('div');
        value.textContent = !c.in_scope ? 'Outside selected plan service area' :
          c.value === null ? 'Population data unavailable' :
            (config.measure === 'share' ? c.share.toFixed(2) + '% of residents' : format.format(c.value)) + ' · ' + config.metric_label;
        box.append(title, value);
        layer.bindTooltip(box, {sticky: true, direction: 'top'});
        layer.on('mouseover', () => layer.setStyle({weight: 3}));
        layer.on('mouseout', () => outlines.resetStyle(layer));
        if (c.in_scope) layer.on('click', () => window.location.assign(c.url));
        layer.on('add', () => {
          const path = layer.getElement();
          if (!path || !c.in_scope) return;
          path.setAttribute('tabindex', '0'); path.setAttribute('role', 'link');
          path.setAttribute('aria-label', c.name + ' County, ' + value.textContent);
          path.addEventListener('keydown', event => { if (event.key === 'Enter') window.location.assign(c.url); });
          path.addEventListener('focus', () => layer.openTooltip());
          path.addEventListener('blur', () => layer.closeTooltip());
        });
        if (c.id === config.selected) selectedLayer = layer;
      }}).addTo(map);
      map.fitBounds(outlines.getBounds(), {padding: [15, 15]});
      if (selectedLayer) selectedLayer.bringToFront();
      if (config.layer === 'contacts') {
        for (const point of config.points) {
          const popup = document.createElement('div');
          const title = document.createElement('strong'); title.textContent = point.name || 'CRM contact';
          const birthday = document.createElement('div'); birthday.textContent = '65th birthday: ' + point.turns65;
          const precision = document.createElement('div'); precision.textContent = 'Address-match location estimate';
          const link = document.createElement('a'); link.href = point.url; link.textContent = 'Open contact';
          popup.append(title, birthday, precision, link);
          L.circleMarker([point.lat, point.lon], {radius: 7, color: '#ffffff', weight: 2,
            fillColor: '#075f65', fillOpacity: .95}).bindPopup(popup).addTo(map);
        }
      }
      if (!tileFailed) status.textContent = 'Select a county to see its details. Drag to pan; use + and − to zoom.' +
        (config.layer === 'contacts' ? ' Showing ' + config.points.length + ' of ' + config.point_total + ' verified contact locations.' : '');
    })
    .catch(() => {
      [fitState, fitCounty].forEach(control => { control.disabled = true; });
      message('County boundaries could not load.');
    });
})();
