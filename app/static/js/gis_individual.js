(() => {
  const map = L.map('individual-map').setView([43.35,-124.1],9);
  L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}', {attribution:'Tiles &copy; Esri',maxZoom:18}).addTo(map);
  const markers=L.layerGroup().addTo(map);
  const countyLayer=L.layerGroup().addTo(map);
  const status=document.getElementById('status');
  async function load(){
    const r=await fetch('/gis/individual/data');
    if(!r.ok){status.textContent='Unable to retrieve private contacts ('+r.status+')';return;}
    const data=await r.json();markers.clearLayers();
    const bounds=[];
    data.pins.forEach(p=>{
      const pin=L.circleMarker([p.lat,p.lon],{radius:7,color:'#b78a2d',weight:2,fillColor:'#176b4b',fillOpacity:.9}).addTo(markers);
      const node=document.createElement('div');
      const label=document.createElement('strong');label.textContent=p.name||'Contact';node.append(label);
      const detail=document.createElement('p');detail.textContent='ZIP '+p.zip+' · '+(p.county||'County unspecified')+' · Match '+p.score;node.append(detail);
      const link=document.createElement('a');link.href='/leads/'+encodeURIComponent(p.id);link.textContent='Open CRM contact';node.append(link);
      pin.bindPopup(node);bounds.push([p.lat,p.lon]);
    });
    if(bounds.length)map.fitBounds(bounds,{padding:[30,30],maxZoom:13});
    status.textContent=data.pins.length+' contacts mapped at verified street locations; '+data.unmapped+' not mapped.';
  }
  document.getElementById('geocode').onclick=async()=>{
    status.textContent='Geocoding up to 10 addresses…';
    try{
      const r=await fetch('/gis/individual/geocode',{method:'POST'});
      const d=await r.json();
      if(!r.ok)throw Error(d.detail||'Request failed');
      await load();
      status.textContent+=' Last batch: '+d.processed+' checked, '+d.matched+' matched.';
    }catch(e){status.textContent='Geocoding error: '+e.message;}
  };
  document.getElementById('county-button').onclick=async()=>{
    const county=document.getElementById('county').value.trim().replace(/ county$/i,'');
    const state=document.getElementById('state').value.trim().toUpperCase();
    if(!county||!state){status.textContent='Enter a county and state';return;}
    status.textContent='Loading county boundary…';
    try{
      const states={OR:'41',WA:'53',CA:'06',TX:'48',WV:'54'};
      const fips=states[state];if(!fips)throw Error('State not yet supported for boundary lookup');
      const lookup=await fetch('https://api.census.gov/data/2020/dec/pl?get=NAME&for=county:*&in=state:'+fips);
      if(!lookup.ok)throw Error('County lookup unavailable');
      const rows=await lookup.json();
      const match=rows.slice(1).find(r=>r[0].split(' County')[0].toLowerCase()===county.toLowerCase());
      if(!match)throw Error('County not found');
      const geo=await fetch('https://raw.githubusercontent.com/plotly/datasets/master/geojson-counties-fips.json');
      if(!geo.ok)throw Error('Boundary data unavailable');
      const all=await geo.json();const id=fips+match[2];
      const feature=all.features.find(f=>f.id===id);
      if(!feature)throw Error('Boundary polygon not found');
      countyLayer.clearLayers();
      const polygon=L.geoJSON(feature,{style:{color:'#c49b35',weight:3,fillColor:'#16824d',fillOpacity:.16}}).addTo(countyLayer);
      map.fitBounds(polygon.getBounds(),{padding:[20,20]});
      status.textContent=county+' County boundary highlighted.';
    }catch(e){status.textContent='Boundary error: '+e.message;}
  };
  load();
})();