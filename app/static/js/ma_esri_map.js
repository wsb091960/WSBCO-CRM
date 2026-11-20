// Esri basemaps with the same Leaflet setup used by the GIS Territory Map.
(() => {
  'use strict';
  const root = document.getElementById('ma-esri-map');
  if (!root) return;
  const status = document.getElementById('ma-map-status');
  const basemap = document.getElementById('ma-basemap');
  const fitState = document.getElementById('ma-fit-state');
  const fitCounty = document.getElementById('ma-fit-county');
  const config = JSON.parse(document.getElementById('ma-map-config').textContent);
  const unavailable = message => {
    status.textContent = message + ' Use the county selector or Browse all counties to show plans.';
  };
  if (!window.L) {
    root.textContent = 'Interactive map unavailable.';
    [basemap, fitState, fitCounty].forEach(control => { control.disabled = true; });
    unavailable('The map could not load.');
    return;
  }
  const map = L.map(root, {scrollWheelZoom: false}).setView([39, -98], 4);
  const base = 'https://server.arcgisonline.com/ArcGIS/rest/services/';
  const layers = {};
  let active, outlines, selectedLayer, tileFailed = false;
  const meta = new Map(config.counties.map(county => [county.id, county]));
  for (const [name, path, maxZoom] of [
    ['light', 'Canvas/World_Light_Gray_Base', 16],
    ['streets', 'World_Street_Map', 18], ['satellite', 'World_Imagery', 18]
  ]) {
    layers[name] = L.tileLayer(base + path + '/MapServer/tile/{z}/{y}/{x}', {
      maxZoom, attribution: 'Tiles &copy; Esri &mdash; Sources: Esri, HERE, Garmin, USGS, NOAA, contributors'
    });
    layers[name].on('tileerror', () => {
      tileFailed = true;
      unavailable('Some background map tiles are unavailable. County boundaries and plan links still work.');
    });
  }
  active = layers.light.addTo(map);
  const style = feature => {
    const county = meta.get(feature.properties.id);
    const selected = county.id === config.selected;
    const satellite = basemap.value === 'satellite';
    return {color: selected ? '#075b60' : satellite ? '#ffffff' : '#4a777f',
      weight: selected ? 3 : 1.2, fillColor: selected ? '#087b79' : county.count === 0 ? '#a4adb7' : '#66b6bc',
      fillOpacity: selected ? 0.5 : county.count === 0 ? 0.4 : 0.15};
  };
  basemap.addEventListener('change', () => {
    const next = layers[basemap.value];
    if (!next || next === active) return;
    map.removeLayer(active);
    tileFailed = false;
    active = next.addTo(map);
    if (outlines) outlines.setStyle(style);
    if (outlines) status.textContent = 'Click a county to show its ' + config.year + ' plans. Drag to pan; use + and − to zoom.';
  });
  fitState.addEventListener('click', () => {
    if (outlines) map.fitBounds(outlines.getBounds(), {padding: [16, 16]});
  });
  fitCounty.addEventListener('click', () => {
    if (selectedLayer) map.fitBounds(selectedLayer.getBounds(), {padding: [28, 28], maxZoom: 10});
  });
  fetch(config.features_url, {credentials: 'same-origin'})
    .then(response => {
      if (!response.ok) throw Error('County map unavailable');
      return response.json();
    })
    .then(data => {
      if (data.type !== 'FeatureCollection' || data.features.length !== meta.size ||
          new Set(data.features.map(f => f.properties.id)).size !== meta.size ||
          data.features.some(f => !meta.has(f.properties.id))) throw Error('County boundaries do not match');
      outlines = L.geoJSON(data, {style, onEachFeature(feature, layer) {
        const county = meta.get(feature.properties.id);
        const tooltip = document.createElement('div');
        const title = document.createElement('strong');
        title.textContent = county.name + ' County';
        const count = document.createElement('div');
        count.textContent = county.count === null ? 'Plan data unavailable' : county.count + ' plans listed · ' + config.year;
        tooltip.append(title, count);
        layer.bindTooltip(tooltip, {sticky: true, direction: 'top'});
        layer.on('mouseover', () => layer.setStyle({weight: 3, fillOpacity: 0.4}));
        layer.on('mouseout', () => outlines.resetStyle(layer));
        layer.on('click', () => window.location.assign(county.url));
        layer.on('add', () => {
          const path = layer.getElement();
          if (!path) return;
          path.setAttribute('tabindex', '0');
          path.setAttribute('role', 'link');
          path.setAttribute('aria-label', county.name + ' County, ' +
            (county.count === null ? 'plan data unavailable' : county.count + ' plans'));
          path.addEventListener('keydown', event => {
            if (event.key === 'Enter') window.location.assign(county.url);
          });
          path.addEventListener('focus', () => layer.openTooltip());
          path.addEventListener('blur', () => layer.closeTooltip());
        });
        if (county.id === config.selected) selectedLayer = layer;
      }}).addTo(map);
      map.fitBounds(outlines.getBounds(), {padding: [16, 16]});
      if (selectedLayer) selectedLayer.bringToFront();
      if (!tileFailed) status.textContent = 'Click a county to show its ' + config.year + ' plans. Drag to pan; use + and − to zoom.';
    })
    .catch(() => {
      [fitState, fitCounty].forEach(control => { control.disabled = true; });
      unavailable('County boundaries could not load.');
    });
})();
