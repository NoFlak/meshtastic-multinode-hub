// Simple Leaflet map that polls /api/nodes/positions and displays markers
(function(){
  const map = L.map('map').setView([0,0], 2);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; OpenStreetMap contributors'
  }).addTo(map);

  const markers = L.markerClusterGroup();
  map.addLayer(markers);

  const nodeMarkers = {};
  let pollInterval = 15000;
  let pollTimer = null;
  let paused = false;

  function batteryColor(battery){
    if(battery == null) return '#95a5a6';
    if(battery > 75) return '#2ecc71';
    if(battery > 40) return '#f1c40f';
    return '#e74c3c';
  }

  function ageColor(ts){
    if(!ts) return 'black';
    const age = (Date.now() - new Date(ts).getTime())/1000;
    if(age < 60) return 'black';
    if(age < 300) return 'orange';
    return 'red';
  }

  async function fetchPositions(){
    try{
      const resp = await fetch('/api/nodes/positions');
      const data = await resp.json();
      if(!data.ok) return;
      markers.clearLayers();
      data.positions.forEach(p => {
        const lat = p.gps_lat;
        const lon = p.gps_lon;
        if(lat == null || lon == null) return;
        const title = p.long_name || p.node_id;
        // color icon by battery/age
      const color = batteryColor(p.battery) || ageColor(p.last_updated);
        const icon = L.divIcon({className: 'custom-marker', html: `<svg width="24" height="24" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9" fill="${color}" /></svg>`, iconSize: [24,24]});
        const marker = L.marker([lat, lon], {icon: icon});
        const popup = `<b>${title}</b><br/>${p.node_id}<br/>Battery: ${p.battery || 'N/A'}<br/>Updated: ${p.last_updated}<br/><a href="/node/${p.node_id}">Details</a>`;
        marker.bindPopup(popup);
        marker.on('click', ()=> onMarkerClick(p.node_id, marker));
        markers.addLayer(marker);
        nodeMarkers[p.node_id] = marker;
      });
      if(data.positions.length>0){
        const first = data.positions[0];
        if(first.gps_lat && first.gps_lon) map.setView([first.gps_lat, first.gps_lon], 10);
      }
    }catch(e){
      console.error('Failed to fetch positions', e);
    }
  }

  // handle marker click: fetch telemetry history and draw polyline
  let currentTrail = null;
  async function onMarkerClick(nodeId, marker){
    try{
      const resp = await fetch(`/api/node/${encodeURIComponent(nodeId)}/telemetry/history?limit=200`);
      const data = await resp.json();
      if(!data.ok) return;
      const points = data.history.filter(h => h.gps_lat != null && h.gps_lon != null).map(h => [h.gps_lat, h.gps_lon]);
      if(currentTrail){
        map.removeLayer(currentTrail);
        currentTrail = null;
      }
      if(points.length>1){
        currentTrail = L.polyline(points, {color: 'blue'}).addTo(map);
        map.fitBounds(currentTrail.getBounds());
      }
      // playback simple: step through and place a temporary marker
      // create a small control area if not exists
      const playBtn = document.getElementById('playTrail');
      if(playBtn){
        playBtn.disabled = false;
        playBtn.onclick = ()=> playTrail(points);
      }
    }catch(e){
      console.error('Failed to fetch telemetry history', e);
    }
  }

  let playMarker = null;
  function playTrail(points){
    if(!points || points.length==0) return;
    let i = 0;
    if(playMarker) map.removeLayer(playMarker);
    playMarker = L.marker(points[0]).addTo(map);
    const iv = setInterval(()=>{
      i++;
      if(i>=points.length){
        clearInterval(iv);
        return;
      }
      playMarker.setLatLng(points[i]);
    }, 600);
  }

  // poll control
  const pollInput = document.getElementById('pollInterval');
  const pauseBtn = document.getElementById('pauseBtn');
  const resumeBtn = document.getElementById('resumeBtn');
  const playBtn = document.createElement('button');
  playBtn.id = 'playTrail';
  playBtn.disabled = true;
  playBtn.textContent = 'Play Trail';
  document.querySelector('.map-controls').appendChild(playBtn);

  function startPolling(){
    if(pollTimer) clearInterval(pollTimer);
    const val = parseInt(pollInput.value, 10) || 15;
    pollInterval = Math.max(5, Math.min(300, val)) * 1000;
    pollTimer = setInterval(()=>{ if(!paused) fetchPositions(); }, pollInterval);
  }

  pauseBtn.onclick = ()=>{ paused = true; pauseBtn.disabled = true; resumeBtn.disabled = false; };
  resumeBtn.onclick = ()=>{ paused = false; pauseBtn.disabled = false; resumeBtn.disabled = true; };
  pollInput.onchange = startPolling;

  // initial fetch and then poll
  fetchPositions();
  startPolling();
})();
