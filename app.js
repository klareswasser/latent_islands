const colors = ['#ff9800', '#4caf50', '#9e9e9e', '#1565c0', '#f44336', '#795548', '#7e57c2', '#0097a7'];
const nationalBounds = [[24.0, 122.0], [46.1, 146.2]];
const kantoBounds = [[34.75, 138.55], [37.20, 141.20]];

const map = L.map('map', { zoomControl: false, preferCanvas: true, minZoom: 5 });
L.control.zoom({ position: 'topright' }).addTo(map);
L.tileLayer('https://cyberjapandata.gsi.go.jp/xyz/pale/{z}/{x}/{y}.png', {
  maxZoom: 18,
  attribution: '<a href="https://maps.gsi.go.jp/development/ichiran.html" target="_blank">地理院タイル</a>'
}).addTo(map);
map.fitBounds(nationalBounds, { padding: [10, 10] });

let islandData;
let islandLayer;
let riverLayer;
let mainlandLayer;
let allBounds;
let minArea = 0.02;
let prefecture = '';

const fmt = new Intl.NumberFormat('ja-JP', { maximumFractionDigits: 2 });
const $ = id => document.getElementById(id);

function areaFromSlider(value) {
  return 0.02 * Math.pow(10, Number(value));
}

function popupHtml(p) {
  const place = [p.prefecture, p.municipality].filter(Boolean).join(' ');
  return `<div class="popup-id">${p.island_id}</div>
    <div class="popup-title">${place || '無名の島'}</div>
    <dl class="popup-grid">
      <dt>面積</dt><dd>${fmt.format(p.area_km2)} km²</dd>
      <dt>外周</dt><dd>${fmt.format(p.perimeter_km)} km</dd>
      <dt>水の境界</dt><dd>${p.rivers || '名称未収録の水域'}</dd>
    </dl>`;
}

function isVisible(feature) {
  const p = feature.properties;
  return p.area_km2 >= minArea && (!prefecture || p.prefecture === prefecture);
}

function renderIslands() {
  if (islandLayer) map.removeLayer(islandLayer);
  const filtered = { type: 'FeatureCollection', features: islandData.features.filter(isVisible) };
  islandLayer = L.geoJSON(filtered, {
    renderer: L.canvas({ padding: 0.5 }),
    style: f => ({
      color: '#fffdf6', weight: 1.15, opacity: 1,
      fillColor: colors[f.properties.color % colors.length], fillOpacity: 0.79
    }),
    onEachFeature: (feature, layer) => {
      layer.bindPopup(popupHtml(feature.properties));
      layer.on({
        mouseover: e => e.target.setStyle({ weight: 2.2, fillOpacity: .96 }),
        mouseout: e => islandLayer.resetStyle(e.target)
      });
      layer._islandId = feature.properties.island_id;
    }
  }).addTo(map);

  const features = filtered.features;
  $('visible-count').textContent = fmt.format(features.length);
  $('total-area').textContent = fmt.format(features.reduce((sum, f) => sum + f.properties.area_km2, 0));
  $('rank-note').textContent = `${features.length}件`;
  renderRanking(features.slice().sort((a, b) => b.properties.area_km2 - a.properties.area_km2).slice(0, 10));
}

function renderRanking(features) {
  $('island-list').innerHTML = features.map((f, i) => {
    const p = f.properties;
    return `<li><button data-island="${p.island_id}"><span class="rank-number">${String(i + 1).padStart(2, '0')}</span><span class="rank-name">${p.prefecture} ${p.municipality || p.island_id}</span><span class="rank-area">${fmt.format(p.area_km2)} km²</span></button></li>`;
  }).join('');
  $('island-list').querySelectorAll('button').forEach(button => button.addEventListener('click', () => {
    islandLayer.eachLayer(layer => {
      if (layer._islandId === button.dataset.island) {
        map.fitBounds(layer.getBounds(), { maxZoom: 12, padding: [45, 45] });
        layer.openPopup();
      }
    });
  }));
}

async function init() {
  const [islands, context, rivers] = await Promise.all([
    fetch('data/processed/islands.geojson').then(r => r.json()),
    fetch('data/processed/context.geojson').then(r => r.json()),
    fetch('data/processed/rivers.geojson').then(r => r.json())
  ]);
  islandData = islands;
  allBounds = L.geoJSON(islands).getBounds();

  mainlandLayer = L.geoJSON(context, {
    style: f => f.properties.kind === 'mainland'
      ? { color: '#708184', weight: .6, fillColor: '#d8d8cf', fillOpacity: .48 }
      : { color: '#a7d3dc', weight: 0, fillColor: '#b8dfe5', fillOpacity: .6 }
  }).addTo(map);
  riverLayer = L.geoJSON(rivers, {
    renderer: L.canvas({ tolerance: 3 }),
    style: { color: '#318da2', weight: .75, opacity: .62 },
    onEachFeature: (f, layer) => f.properties.name && layer.bindTooltip(f.properties.name, { sticky: true })
  }).addTo(map);

  const prefs = [...new Set(islands.features.map(f => f.properties.prefecture).filter(Boolean))].sort();
  $('prefecture').insertAdjacentHTML('beforeend', prefs.map(p => `<option value="${p}">${p}</option>`).join(''));
  $('swatches').innerHTML = colors.map(color => `<i style="background:${color}"></i>`).join('');
  renderIslands();
  islandLayer.bringToFront();
  $('loading').classList.add('done');
}

$('area-filter').addEventListener('input', e => {
  minArea = areaFromSlider(e.target.value);
  $('area-output').textContent = `${minArea < 1 ? minArea.toFixed(2) : fmt.format(minArea)} km²`;
  renderIslands();
});
$('prefecture').addEventListener('change', e => { prefecture = e.target.value; renderIslands(); });
$('rivers-toggle').addEventListener('change', e => e.target.checked ? riverLayer.addTo(map) : map.removeLayer(riverLayer));
$('mainland-toggle').addEventListener('change', e => e.target.checked ? mainlandLayer.addTo(map) : map.removeLayer(mainlandLayer));
$('mainland-view').addEventListener('click', () => {
  map.fitBounds(nationalBounds, { padding: [10, 10] });
  $('mainland-view').classList.add('active'); $('all-view').classList.remove('active');
});
$('all-view').addEventListener('click', () => {
  map.fitBounds(kantoBounds, { padding: [10, 10] });
  $('all-view').classList.add('active'); $('mainland-view').classList.remove('active');
});

init().catch(error => {
  console.error(error);
  $('loading').innerHTML = '読み込みに失敗しました。ローカルサーバーから開いてください。';
});
