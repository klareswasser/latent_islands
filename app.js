const colors = ['#ff9800', '#4caf50', '#9e9e9e', '#1565c0', '#f44336', '#795548', '#7e57c2', '#0097a7'];
const nationalBounds = [[24.0, 122.0], [46.1, 146.2]];

const map = L.map('map', { zoomControl: false, preferCanvas: true, minZoom: 5 });
L.control.zoom({ position: 'topright' }).addTo(map);
L.tileLayer('https://cyberjapandata.gsi.go.jp/xyz/pale/{z}/{x}/{y}.png', {
  maxZoom: 18,
  attribution: '<a href="https://maps.gsi.go.jp/development/ichiran.html" target="_blank">地理院タイル</a>'
}).addTo(map);
map.fitBounds(nationalBounds, { padding: [10, 10] });

let islandData;
let islandLayer;
let minArea = 0.02;

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

function renderIslands() {
  if (islandLayer) map.removeLayer(islandLayer);
  const features = islandData.features.filter(feature => feature.properties.area_km2 >= minArea);
  islandLayer = L.geoJSON({ type: 'FeatureCollection', features }, {
    renderer: L.canvas({ padding: 0.5 }),
    style: feature => ({
      color: '#fffdf6', weight: 1.15, opacity: 1,
      fillColor: colors[feature.properties.color % colors.length], fillOpacity: 0.79
    }),
    onEachFeature: (feature, layer) => {
      layer.bindPopup(popupHtml(feature.properties));
      layer.on({
        mouseover: event => event.target.setStyle({ weight: 2.2, fillOpacity: .96 }),
        mouseout: event => islandLayer.resetStyle(event.target)
      });
    }
  }).addTo(map);
  $('visible-count').textContent = fmt.format(features.length);
}

async function init() {
  const [islands, context, rivers] = await Promise.all([
    fetch('data/processed/islands.geojson').then(response => response.json()),
    fetch('data/processed/context.geojson').then(response => response.json()),
    fetch('data/processed/rivers.geojson').then(response => response.json())
  ]);
  islandData = islands;

  L.geoJSON(context, {
    style: { color: '#708184', weight: .6, fillColor: '#d8d8cf', fillOpacity: .48 }
  }).addTo(map);
  L.geoJSON(rivers, {
    renderer: L.canvas({ tolerance: 3 }),
    style: { color: '#318da2', weight: .75, opacity: .62 },
    onEachFeature: (feature, layer) => feature.properties.name && layer.bindTooltip(feature.properties.name, { sticky: true })
  }).addTo(map);

  renderIslands();
  islandLayer.bringToFront();
  $('loading').classList.add('done');
}

$('area-filter').addEventListener('input', event => {
  minArea = areaFromSlider(event.target.value);
  $('area-output').textContent = `${minArea < 1 ? minArea.toFixed(2) : fmt.format(minArea)} km²`;
  renderIslands();
});

init().catch(error => {
  console.error(error);
  $('loading').innerHTML = '読み込みに失敗しました。ページを再読み込みしてください。';
});
