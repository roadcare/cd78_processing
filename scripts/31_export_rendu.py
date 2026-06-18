"""Task 3.1 / 3.2 — export the rendu layers to GeoJSON and a Leaflet viewer.

3.1 — writes one ``<layer>.geojson`` (EPSG:4326) per layer into ``--out``
(default ``D:\\Tmp\\cd78_exports``):

  client.troncon_client, client.itineraires_v2, client.pas_50, client.pas_100,
  public.session, public.image, public.road_data (classe in
  'Dégradation chaussée' / 'Largeur').

  Some columns are dropped for ``image`` and ``session`` (see ``LAYERS``). Every
  geometry is transformed to 4326 (SRID 0 is assumed 2154).

3.2 — writes ``index.html`` (a Leaflet + Chart.js dashboard) + one ``<layer>.js``
sidecar per *viewer* layer (each assigns a global ``LAYER_<name>``; loaded via
``<script>`` so the viewer also works straight from ``file://``). The dashboard
shows only ``pas_100``, ``troncon_client`` and ``road_data``, with the Roadcare
logo, KPIs (segments / linéaire / budget), cross-filters (priorité, type de
chaussée, importance trafic, état global, technique, free text) and charts that
analyse the filtered ``pas_100`` by note état (surface / structure / global),
type de travaux and budget. ``pas_100`` is coloured by priorité.

Usage
-----
    python scripts/31_export_rendu.py
    python scripts/31_export_rendu.py --out D:\\Tmp\\cd78_exports --geojson-only
    python scripts/31_export_rendu.py --html-only   # just rebuild the dashboard
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import psycopg2
from psycopg2 import sql
import yaml


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = r"D:\Tmp\cd78_exports"
SOURCE_SRID_FALLBACK = 2154
WEB_SRID = 4326

# Note globale columns dropped everywhere (geojson, .js, popup, Excel):
# the /1 average and the /20 note. Etat_global is kept.
PAS_EXCLUDE = ["avg_note_global", "Note_globale"]

# name | schema | table | exclude cols | where | default visible | popup image |
# style | viewer (included in the HTML dashboard).
#
# 3.1 still writes a .geojson for every layer; only ``viewer: True`` layers get a
# .js sidecar and appear in index.html (pas_100, troncon_client, road_data).
LAYERS = [
    {"name": "troncon_client", "schema": "client", "table": "troncon_client",
     "exclude": [], "where": None, "visible": True, "popup_img": False,
     "color": "#1f78b4", "viewer": True, "label": "ref_cd78"},
    {"name": "itineraires_v2", "schema": "client", "table": "itineraires_v2",
     "exclude": [], "where": None, "visible": False, "popup_img": False,
     "color": "#6a3d9a", "viewer": False},
    {"name": "pas_50", "schema": "client", "table": "pas_50",
     "exclude": PAS_EXCLUDE, "where": None, "visible": False, "popup_img": False,
     "color": "#33a02c", "viewer": False},
    {"name": "pas_100", "schema": "client", "table": "pas_100",
     "exclude": PAS_EXCLUDE, "where": None, "visible": True, "popup_img": True,
     "color": "#e31a1c", "viewer": True,
     # Representative image: the one on the same axe within [cumuld, cumulf]
     # whose Note_Global is closest to the pas' avg_note_global.
     "extra_select":
        "(SELECT im.url FROM public.image im "
        "WHERE im.axe = t0.axe AND im.cumuld BETWEEN t0.cumuld AND t0.cumulf "
        'AND im."Note_Global" IS NOT NULL AND im.url IS NOT NULL '
        'ORDER BY abs(im."Note_Global" - t0.avg_note_global) ASC LIMIT 1) AS image_url'},
    {"name": "session", "schema": "public", "table": "session",
     "exclude": ["geomCalibration", "surfaceGrade", "structuralGrade",
                 "calibrationId", "calibrationError", "calibrationErrorMailSent",
                 "calibrationDone", "videoToImagesDone", "metadataId", "state"],
     "where": None, "visible": False, "popup_img": False, "color": "#ff7f00",
     "viewer": False},
    {"name": "image", "schema": "public", "table": "image",
     "exclude": ["geomCalibration", "cumulEndSession", "prIdStart",
                 "prDistanceStart", "elapsedTime", "road_cumul", "road_id",
                 "geom_prj", "ln_prj", "seg_ss", "seg_prj", "d_angle_seg",
                 "geom_visible"],
     "where": None, "visible": False, "popup_img": True, "color": "#000000",
     "viewer": False},
    {"name": "road_data", "schema": "public", "table": "road_data",
     "exclude": ["pixels_coords"], "visible": False, "popup_img": True,
     "color": "#b15928", "viewer": True, "label": "degradations",
     "where": "classe IN ('Dégradation chaussée','Largeur')",
     # Full multipolygon geom (no centroid). Keep `filename` for the photo
     # popup; drop the bulky/irrelevant fields to trim the sidecar.
     "viewer_exclude": ["comment", "sessionName", "sessionId", "image_id", "id",
                        "reliability", "measure_width", "cumuld", "cumulf"]},
]

# Layers shown in the HTML dashboard.
VIEWER_LAYERS = [l for l in LAYERS if l.get("viewer")]


def load_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    if "source" not in raw:
        raise ValueError(f"Config {path} is missing the 'source' section")
    return raw


def connect(cfg: dict[str, Any]):
    s = cfg["source"]
    return psycopg2.connect(host=s["host"], port=s["port"], user=s["user"],
                            password=s["password"], dbname=s["database"])


def fetch_columns(cur, schema: str, table: str) -> list[str]:
    return [c for c, _ in fetch_columns_typed(cur, schema, table)]


def fetch_columns_typed(cur, schema: str, table: str) -> list[tuple[str, str]]:
    """Return [(column, pg typname), …] in column order."""
    cur.execute(
        """
        SELECT a.attname, t.typname FROM pg_attribute a
        JOIN pg_class c ON c.oid = a.attrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        JOIN pg_type t ON t.oid = a.atttypid
        WHERE n.nspname = %s AND c.relname = %s
          AND a.attnum > 0 AND NOT a.attisdropped
        ORDER BY a.attnum
        """, (schema, table))
    return [(r[0], r[1]) for r in cur.fetchall()]


# Floating-point column types rounded to 2 decimals in the GeoJSON / viewer.
FLOAT_TYPES = {"numeric", "float8", "float4"}
DECIMALS = 2


def export_geojson(cur, layer: dict, geom_col: str = "geom",
                   maxdigits: int = 6, simplify: float = 0.0,
                   centroid: bool = False, extra_exclude: list[str] | None = None) -> str:
    """Return the FeatureCollection text (4326) for one layer.

    ``maxdigits`` caps coordinate precision; ``simplify`` (metres, source CRS)
    thins geometry; ``centroid`` replaces each geometry by an interior point.
    The last two are used only for the lighter viewer copies, never for the
    canonical ``.geojson``.
    """
    cols_typed = fetch_columns_typed(cur, layer["schema"], layer["table"])
    types = dict(cols_typed)
    drop = set(layer["exclude"]) | {geom_col} | set(extra_exclude or [])
    keep = [c for c, _ in cols_typed if c not in drop]
    g = sql.SQL("CASE WHEN ST_SRID({g})=0 THEN ST_SetSRID({g}, {fb}) ELSE {g} END"
                ).format(g=sql.Identifier(geom_col),
                         fb=sql.Literal(SOURCE_SRID_FALLBACK))
    if centroid:
        g = sql.SQL("ST_PointOnSurface({g})").format(g=g)
    elif simplify:
        g = sql.SQL("ST_SimplifyPreserveTopology({g}, {t})").format(
            g=g, t=sql.Literal(simplify))
    geom_t = sql.SQL("ST_Transform({g}, {web}) AS {col}").format(
        g=g, web=sql.Literal(WEB_SRID), col=sql.Identifier(geom_col))
    def col_expr(c: str):
        # round floating-point values to DECIMALS places (note, width, …)
        if types.get(c) in FLOAT_TYPES:
            return sql.SQL("round({col}::numeric, {d}) AS {col}").format(
                col=sql.Identifier(c), d=sql.Literal(DECIMALS))
        return sql.Identifier(c)
    # Optional per-layer computed columns (trusted SQL, referencing the source
    # table alias ``t0``) — e.g. pas_100's representative image_url.
    extra = [sql.SQL(layer["extra_select"])] if layer.get("extra_select") else []
    select_cols = sql.SQL(", ").join(
        [col_expr(c) for c in keep] + extra + [geom_t])
    # Always drop rows with no usable geometry (e.g. road_data 'Largeur' rows
    # have a null geom) — otherwise the GeoJSON carries null/empty features that
    # break Leaflet ("Invalid LatLng (undefined, undefined)").
    gid = sql.Identifier(geom_col)
    valid = sql.SQL("{g} IS NOT NULL AND NOT ST_IsEmpty({g})").format(g=gid)
    if layer["where"]:
        where = (sql.SQL(" WHERE (") + sql.SQL(layer["where"])
                 + sql.SQL(") AND ") + valid)
    else:
        where = sql.SQL(" WHERE ") + valid
    query = sql.SQL(
        """
        SELECT json_build_object(
                 'type', 'FeatureCollection',
                 'features', COALESCE(
                     json_agg(ST_AsGeoJSON(t.*, {gcol}, {md})::json), '[]'::json)
               )::text
        FROM (SELECT {cols} FROM {sch}.{tbl} t0{where}) t
        """
    ).format(gcol=sql.Literal(geom_col), md=sql.Literal(maxdigits),
             cols=select_cols,
             sch=sql.Identifier(layer["schema"]),
             tbl=sql.Identifier(layer["table"]), where=where)
    cur.execute(query)
    return cur.fetchone()[0]


def feature_count(text: str) -> int:
    # cheap: count '"type":"Feature"' occurrences without parsing the whole blob
    return text.count('"type": "Feature"') + text.count('"type":"Feature"')


# Dashboard template. Tokens (%%NAME%%) are substituted in write_html so the
# JS/CSS braces don't need escaping.
HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>CD78 — plan de travaux</title>
%%LEAFLET_CSS%%
%%LEAFLET_JS%%
%%CHART_JS%%
<style>
  :root{ --bg:#f5f6f8; --card:#fff; --ink:#1f2733; --muted:#6b7785; --line:#e3e7ee;
         --p1:#d7191c; --p2:#fdae61; --p3:#a6d96a; --p0:#1a9641; }
  *{box-sizing:border-box}
  html,body{margin:0;height:100%;font:13px/1.4 "Segoe UI",system-ui,sans-serif;color:var(--ink)}
  #app{display:flex;height:100%}
  #side{width:380px;min-width:380px;height:100%;overflow-y:auto;background:var(--bg);
        border-right:1px solid var(--line);padding:14px}
  #map{flex:1;height:100%}
  .brand{display:flex;align-items:center;gap:10px;margin-bottom:12px}
  .brand img{height:38px;width:auto}
  .brand h1{font-size:15px;margin:0;font-weight:600}
  .brand small{color:var(--muted);display:block;font-weight:400}
  .card{background:var(--card);border:1px solid var(--line);border-radius:8px;
        padding:10px 12px;margin-bottom:12px}
  .card h2{font-size:12px;text-transform:uppercase;letter-spacing:.04em;
           color:var(--muted);margin:0 0 8px}
  .kpis{display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px}
  .kpi{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:8px 10px}
  .kpi .v{font-size:18px;font-weight:700}
  .kpi .l{font-size:11px;color:var(--muted)}
  .filters{display:grid;grid-template-columns:1fr 1fr;gap:8px}
  .filters label{display:flex;flex-direction:column;font-size:11px;color:var(--muted);gap:3px}
  .filters select,.filters input{font:13px inherit;padding:4px 6px;border:1px solid var(--line);
        border-radius:5px;background:#fff;color:var(--ink)}
  .filters .full{grid-column:1 / -1}
  #reset{margin-top:8px;width:100%;padding:6px;border:1px solid var(--line);background:#fff;
         border-radius:5px;cursor:pointer}
  #reset:hover{background:#eef1f6}
  .chartbox{position:relative;height:170px}
  .legend{display:flex;flex-wrap:wrap;gap:8px;margin-top:6px;font-size:11px;color:var(--muted)}
  .legend i{display:inline-block;width:11px;height:11px;border-radius:2px;margin-right:4px;vertical-align:-1px}
  .leaflet-popup-content{max-height:240px;overflow:auto}
  .leaflet-popup-content table{border-collapse:collapse;font-size:12px}
  .leaflet-popup-content td{padding:1px 6px;border-bottom:1px solid #eee;vertical-align:top}
  .leaflet-popup-content td.k{color:var(--muted);white-space:nowrap}
  .leaflet-popup-content img{max-width:260px;height:auto;display:block;margin-top:4px}
  .pas-label{background:rgba(255,255,255,.88);border:1px solid #c9ced6;box-shadow:none;
             font:11px/1.2 sans-serif;color:#1f2733;padding:1px 4px;border-radius:3px;white-space:nowrap}
  .pas-label:before{display:none!important}
  #map.hide-labels .pas-label{display:none}
  .deg-legend{background:rgba(255,255,255,.93);padding:6px 9px;border-radius:6px;
              font:11px/1.35 sans-serif;max-height:46vh;overflow:auto;
              box-shadow:0 1px 4px rgba(0,0,0,.3)}
  .deg-legend b{display:block;margin-bottom:4px}
  .deg-legend i{display:inline-block;width:11px;height:11px;margin-right:5px;
                vertical-align:-1px;border-radius:2px}
  #err{display:none;position:fixed;z-index:3000;top:0;left:0;right:0;background:#b00020;
       color:#fff;padding:10px 14px;font:13px sans-serif}
</style>
</head>
<body>
<div id="err"></div>
<div id="app">
  <aside id="side">
    <div class="brand">
      <img src="%%LOGO%%" alt="Roadcare" onerror="this.style.display='none'"/>
      <div><h1>CD78 — plan de travaux<small>pas de 100 m · analyse &amp; budget</small></h1></div>
    </div>

    <div class="kpis">
      <div class="kpi"><div class="v" id="k_n">–</div><div class="l">segments</div></div>
      <div class="kpi"><div class="v" id="k_km">–</div><div class="l">linéaire (km)</div></div>
      <div class="kpi"><div class="v" id="k_eur">–</div><div class="l">budget (€)</div></div>
    </div>

    <div class="card">
      <h2>Filtres</h2>
      <div class="filters">
        <label class="full">Axe<select id="f_axe"></select></label>
        <label>Priorité<select id="f_prio"></select></label>
        <label>Type de chaussée<select id="f_type"></select></label>
        <label>Importance trafic<select id="f_imp"></select></label>
        <label>État global<select id="f_etat"></select></label>
        <label class="full">Technique d'entretien<select id="f_tech"></select></label>
        <label class="full">Recherche libre (axe, code…)<input id="q" type="text" placeholder="texte puis Entrée"/></label>
      </div>
      <button id="reset">Réinitialiser les filtres</button>
    </div>

    <div class="card">
      <h2>État global (longueur m)</h2>
      <div class="chartbox"><canvas id="c_etats"></canvas></div>
    </div>
    <div class="card">
      <h2>Budget par priorité (€)</h2>
      <div class="chartbox"><canvas id="c_prio"></canvas></div>
    </div>
    <div class="card">
      <h2>Type de travaux — surface (m²)</h2>
      <div class="chartbox" style="height:200px"><canvas id="c_tech"></canvas></div>
    </div>
    <div class="card">
      <h2>Budget par technique (€)</h2>
      <div class="chartbox" style="height:200px"><canvas id="c_budtech"></canvas></div>
    </div>
  </aside>
  <div id="map"></div>
</div>

%%SCRIPTS%%
<script>
function showErr(m){var d=document.getElementById('err');if(d){d.style.display='block';d.innerHTML=m;}}
window.addEventListener('error',function(e){showErr('Erreur JS : '+e.message);});
try{
if(typeof L==='undefined') throw new Error("Leaflet (leaflet.js) non chargé — pas d'accès au CDN ? Le dossier devrait contenir lib/leaflet.js.");
if(typeof Chart==='undefined') throw new Error("Chart.js non chargé — pas d'accès au CDN ? Le dossier devrait contenir lib/chart.umd.min.js.");

var LAYERS = %%LAYERS_CFG%%;
var PRIO_COLORS = {'P1':'#d7191c','P2':'#fdae61','P3':'#a6d96a','-':'#1a9641'};
var ETATS = ['A-Bon','B-Moyen','C-Mauvais'];
// pas colour by état surface: Bon = green, Moyen = yellow, Mauvais = red
var SURF_COLORS = {'A-Bon':'#1a9641','B-Moyen':'#f4d03f','C-Mauvais':'#d7191c'};
var LABEL_ZOOM = %%LABEL_ZOOM%%;
function prioColor(p){ return PRIO_COLORS[p] || '#3388ff'; }
function surfColor(e){ return SURF_COLORS[e] || '#3388ff'; }
function eur(n){ return (n||0).toLocaleString('fr-FR'); }
// label = "priorité : technique d'entretien" (each pas shows its own data)
function pasLabel(p){
  return (p.Priorite || '-') + ' : ' + (p.Technique_entretien || '-');
}
function updateLabels(){
  var el=document.getElementById('map');
  if(el) el.classList.toggle('hide-labels', map.getZoom() < LABEL_ZOOM);
}
// distinct colour per degradations sous_classe (built from the data)
var SOUS_PALETTE = ['#e6194b','#3cb44b','#ffe119','#4363d8','#f58231','#911eb4',
  '#42d4f4','#f032e6','#bfef45','#fabed4','#469990','#dcbeff','#9a6324','#800000',
  '#aaffc3','#808000','#000075','#a9a9a9','#ff7f00'];
var sousColorMap = {};
(function(){
  var d = window['LAYER_road_data']; if(!d) return;
  var vals = {};
  d.features.forEach(function(f){ var v=f.properties.sous_classe; if(v) vals[v]=1; });
  Object.keys(vals).sort().forEach(function(v,i){
    sousColorMap[v] = SOUS_PALETTE[i % SOUS_PALETTE.length]; });
})();
function sousColor(v){ return sousColorMap[v] || '#888'; }
// Skip features without usable geometry (guards against "Invalid LatLng").
function hasGeom(f){ var g=f&&f.geometry; return !!(g && g.coordinates && g.coordinates.length); }

var map = L.map('map', {preferCanvas:true});
L.tileLayer("%%TILE_URL%%", {maxZoom:20, subdomains:"%%SUBS%%",
  attribution:"%%ATTR%%"}).addTo(map);
var ctrl = L.control.layers(null, null, {collapsed:false}).addTo(map);
map.on('zoomend', updateLabels);

function popupHtml(props, withImg){
  var url = props.filename || props.image_url;  // road_data uses filename, pas_100 image_url
  var rows = Object.keys(props).filter(function(k){
      return props[k]!==null && props[k]!=='' && k!=='image_url' && k!=='filename' && k!=='Etat_global';})
    .map(function(k){return '<tr><td class="k">'+k+'</td><td>'+props[k]+'</td></tr>';}).join('');
  var html = '<table>'+rows+'</table>';
  if(withImg && url){
    html += '<a href="'+url+'" target="_blank"><img src="'+url+'"/></a>';
  }
  return html;
}

// ---- context layers (troncon_client, road_data): all features, toggleable ----
function buildContext(cfg){
  var data = window['LAYER_'+cfg.name];
  if(!data) return null;
  // degradations: distinct colour per sous_classe; others: fixed colour
  var styleFn = cfg.name==='road_data'
    ? function(f){ var col=sousColor(f.properties.sous_classe);
                   return {color:col, weight:1, fillColor:col, fillOpacity:.55}; }
    : {color:cfg.color, weight: cfg.name==='troncon_client'?2:1,
       fillColor:cfg.color, fillOpacity:.3};
  var lyr = L.geoJSON(data, {
    filter: hasGeom,
    style: styleFn,
    pointToLayer:function(f,ll){return L.circleMarker(ll,
        {radius:3,color:cfg.color,weight:1,fillOpacity:.7});},
    onEachFeature:function(f,l){l.bindPopup(popupHtml(f.properties,cfg.popup_img),{maxWidth:340});}
  });
  ctrl.addOverlay(lyr, cfg.label);
  if(cfg.visible) lyr.addTo(map);
  return lyr;
}
LAYERS.filter(function(c){return c.name!=='pas_100';}).forEach(buildContext);

// legend for the degradations layer (shown only when that layer is active)
var degLegend = L.control({position:'bottomright'});
degLegend.onAdd = function(){
  var div = L.DomUtil.create('div','deg-legend');
  div.innerHTML = '<b>Dégradations — sous_classe</b>' +
    Object.keys(sousColorMap).sort().map(function(v){
      return '<div><i style="background:'+sousColorMap[v]+'"></i>'+v+'</div>'; }).join('');
  return div;
};
map.on('overlayadd', function(e){ if(e.name==='degradations') degLegend.addTo(map); });
map.on('overlayremove', function(e){ if(e.name==='degradations') map.removeControl(degLegend); });

// ---- pas_100 analytic layer (filtered + coloured by priorité) ----
var pasData = window['LAYER_pas_100'] || {features:[]};
var pasLayer = null;

function val(id){ var e=document.getElementById(id); return e?e.value:''; }
function matchPas(p){
  if(val('f_axe')  && String(p.axe)!==val('f_axe')) return false;
  if(val('f_prio') && String(p.Priorite)!==val('f_prio')) return false;
  if(val('f_type') && String(p['Type_chaussée'])!==val('f_type')) return false;
  if(val('f_imp')  && String(p.Importance_trafic_PL)!==val('f_imp')) return false;
  if(val('f_etat') && String(p.Etat_global)!==val('f_etat')) return false;
  if(val('f_tech') && String(p.Technique_entretien)!==val('f_tech')) return false;
  var q=val('q').trim().toLowerCase();
  if(q && JSON.stringify(p).toLowerCase().indexOf(q)<0) return false;
  return true;
}
function filteredPas(){
  return pasData.features.filter(function(f){return matchPas(f.properties);});
}
function drawPas(feats){
  if(pasLayer){ map.removeLayer(pasLayer); ctrl.removeLayer(pasLayer); }
  pasLayer = L.geoJSON({type:'FeatureCollection',features:feats}, {
    filter: hasGeom,
    style:function(f){return {color:surfColor(f.properties.Etat_surface),weight:5,opacity:.9};},
    onEachFeature:function(f,l){
      l.bindPopup(popupHtml(f.properties,true),{maxWidth:340});
      var lab=pasLabel(f.properties);
      if(lab) l.bindTooltip(lab,{permanent:true,direction:'center',className:'pas-label',opacity:1});
    }
  });
  ctrl.addOverlay(pasLayer, 'Etat et travaux');
  pasLayer.addTo(map);
  updateLabels();
}

// ---- filters population ----
function fill(id, values, label){
  var s=document.getElementById(id);
  s.innerHTML = '<option value="">'+label+'</option>' +
    values.map(function(v){return '<option>'+v+'</option>';}).join('');
}
function distinct(key){
  var set={};
  pasData.features.forEach(function(f){var v=f.properties[key]; if(v!==null&&v!=='')set[v]=1;});
  return Object.keys(set).sort();
}
fill('f_axe',  distinct('axe'), 'Tous');
fill('f_prio', distinct('Priorite'), 'Toutes');
fill('f_type', distinct('Type_chaussée'), 'Tous');
fill('f_imp',  distinct('Importance_trafic_PL'), 'Toutes');
fill('f_etat', distinct('Etat_global'), 'Tous');
fill('f_tech', distinct('Technique_entretien'), 'Toutes');

// ---- charts ----
var ch = {};
function mkBar(id, opts){
  return new Chart(document.getElementById(id), {type: opts.type||'bar',
    data:{labels:[],datasets:[]},
    options:Object.assign({responsive:true,maintainAspectRatio:false,
      plugins:{legend:{display:opts.legend!==false,labels:{boxWidth:12,font:{size:10}}}}},
      opts.options||{})});
}
ch.etats = mkBar('c_etats', {legend:false});
ch.prio  = mkBar('c_prio', {legend:false});
ch.tech  = mkBar('c_tech', {legend:false, options:{indexAxis:'y'}});
ch.budtech = mkBar('c_budtech', {legend:false, options:{indexAxis:'y'}});

function countBy(feats, key){
  var m={}; feats.forEach(function(f){var v=f.properties[key]||'(n/a)'; m[v]=(m[v]||0)+1;}); return m;
}
function sumBy(feats, key, valKey){
  var m={}; feats.forEach(function(f){var v=f.properties[key]||'(n/a)';
    m[v]=(m[v]||0)+(Number(f.properties[valKey])||0);}); return m;
}

function updateCharts(feats){
  // état global only — y = total length (m), one colour per état
  function etatLen(k){return ETATS.map(function(e){
    return feats.filter(function(f){return f.properties[k]===e;})
      .reduce(function(s,f){return s+((Number(f.properties.cumulf)-Number(f.properties.cumuld))||0);},0);});}
  ch.etats.data = {labels:ETATS, datasets:[
    {label:'longueur (m)', data:etatLen('Etat_global'),
     backgroundColor:ETATS.map(surfColor)}]};
  ch.etats.update();

  // budget par priorité
  var bp = sumBy(feats,'Priorite','Cout_Total');
  var pk = ['P1','P2','P3','-'].filter(function(p){return p in bp;});
  ch.prio.data = {labels:pk, datasets:[{label:'€', data:pk.map(function(p){return bp[p];}),
    backgroundColor:pk.map(prioColor)}]};
  ch.prio.update();

  // type de travaux — total surface (m²) per technique (exclude no-work)
  var ts = sumBy(feats,'Technique_entretien','surface'); delete ts['-']; delete ts['RAS'];
  var tk = Object.keys(ts).sort(function(a,b){return ts[b]-ts[a];});
  ch.tech.data = {labels:tk, datasets:[{label:'surface (m²)',
    data:tk.map(function(t){return Math.round(ts[t]);}), backgroundColor:'#4e79a7'}]};
  ch.tech.update();

  // budget par technique
  var bt = sumBy(feats,'Technique_entretien','Cout_Total'); delete bt['-']; delete bt['RAS'];
  var bk = Object.keys(bt).sort(function(a,b){return bt[b]-bt[a];});
  ch.budtech.data = {labels:bk, datasets:[{label:'€', data:bk.map(function(t){return bt[t];}),
    backgroundColor:'#e15759'}]};
  ch.budtech.update();
}

function updateKPIs(feats){
  var m=0, eu=0;
  feats.forEach(function(f){var p=f.properties;
    m += (Number(p.cumulf)-Number(p.cumuld))||0; eu += Number(p.Cout_Total)||0;});
  document.getElementById('k_n').textContent = feats.length;
  document.getElementById('k_km').textContent = (m/1000).toFixed(1);
  document.getElementById('k_eur').textContent = eur(eu);
}

function zoomToPas(){
  if(!pasLayer) return;
  try{ var bb=pasLayer.getBounds(); if(bb.isValid()) map.fitBounds(bb,{padding:[30,30]}); }catch(e){}
}
function update(fit){
  var feats = filteredPas();
  drawPas(feats);
  updateKPIs(feats);
  updateCharts(feats);
  if(fit) zoomToPas();
}

// wire filters
['f_prio','f_type','f_imp','f_etat','f_tech'].forEach(function(id){
  document.getElementById(id).addEventListener('change', function(){update();});});
// choosing an axe re-centres / zooms the map on it
document.getElementById('f_axe').addEventListener('change', function(){update(true);});
document.getElementById('q').addEventListener('keydown', function(e){
  if(e.key==='Enter') update();});
document.getElementById('reset').addEventListener('click', function(){
  ['f_axe','f_prio','f_type','f_imp','f_etat','f_tech'].forEach(function(id){
    document.getElementById(id).value='';});
  document.getElementById('q').value=''; update(true);});

update();

// fit to all pas_100 + troncon
var b = L.latLngBounds([]);
if(pasLayer){ try{ b.extend(pasLayer.getBounds()); }catch(e){} }
if(b.isValid()) map.fitBounds(b); else map.setView([48.8,1.9],10);

}catch(e){ showErr('Erreur : '+e.message); }
</script>
</body>
</html>
"""


def write_excel(conn, out_dir: Path) -> Path:
    """Write client.pas_50 and client.pas_100 as two sheets of one .xlsx.

    The ``geom`` column is **not** exported — the sheets are attribute tables.
    """
    import pandas as pd

    path = out_dir / "pas.xlsx"
    with conn.cursor() as cur, pd.ExcelWriter(path, engine="openpyxl") as writer:
        drop = {"geom", *PAS_EXCLUDE}
        for table in ("pas_50", "pas_100"):
            cols = [c for c in fetch_columns(cur, "client", table) if c not in drop]
            sel = ", ".join(f'"{c}"' for c in cols)
            df = pd.read_sql(f"SELECT {sel} FROM client.{table} ORDER BY id", conn)
            df.to_excel(writer, sheet_name=table, index=False)
    return path


# JS/CSS libraries vendored next to index.html so the page needs no CDN.
LIB_ASSETS = {
    "leaflet.css": "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css",
    "leaflet.js": "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js",
    "chart.umd.min.js": "https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js",
}


def vendor_assets(out_dir: Path) -> dict[str, str]:
    """Download Leaflet + Chart.js into ``out_dir/lib`` and return local refs.

    If a file is already present it is reused; if the download fails the CDN URL
    is returned so the page still works when online.
    """
    import urllib.request

    refs: dict[str, str] = {}
    lib = out_dir / "lib"
    for name, url in LIB_ASSETS.items():
        local = lib / name
        if local.exists() and local.stat().st_size > 0:
            refs[name] = f"lib/{name}"
            continue
        try:
            lib.mkdir(parents=True, exist_ok=True)
            with urllib.request.urlopen(url, timeout=30) as r:
                local.write_bytes(r.read())
            refs[name] = f"lib/{name}"
        except Exception as exc:  # offline at export time → fall back to CDN
            print(f"  warning: could not vendor {name} ({exc}); using CDN",
                  file=sys.stderr)
            refs[name] = url
    return refs


def write_html(out_dir: Path, html_cfg: dict[str, Any]) -> None:
    scripts = "\n".join(
        f'<script src="{lyr["name"]}.js"></script>' for lyr in VIEWER_LAYERS)
    layers_cfg = json.dumps([
        {"name": l["name"], "label": l.get("label", f'{l["schema"]}.{l["table"]}'),
         "color": l["color"], "visible": l["visible"], "popup_img": l["popup_img"]}
        for l in VIEWER_LAYERS])

    # Copy the logo next to index.html so the page is self-contained.
    logo_ref = ""
    logo_path = html_cfg.get("logo_path")
    if logo_path:
        src = (PROJECT_ROOT / logo_path)
        if src.exists():
            dst = out_dir / f"logo{src.suffix}"
            dst.write_bytes(src.read_bytes())
            logo_ref = dst.name

    libs = vendor_assets(out_dir)
    repl = {
        "%%LEAFLET_CSS%%": f'<link rel="stylesheet" href="{libs["leaflet.css"]}"/>',
        "%%LEAFLET_JS%%": f'<script src="{libs["leaflet.js"]}"></script>',
        "%%CHART_JS%%": f'<script src="{libs["chart.umd.min.js"]}"></script>',
        "%%SCRIPTS%%": scripts,
        "%%LAYERS_CFG%%": layers_cfg,
        "%%LOGO%%": logo_ref,
        "%%TILE_URL%%": html_cfg.get(
            "tile_url", "https://{s}.tile.openstreetmap.de/{z}/{x}/{y}.png"),
        "%%SUBS%%": html_cfg.get("tile_subdomains", "abc"),
        "%%ATTR%%": html_cfg.get("tile_attribution", "&copy; OpenStreetMap"),
        "%%LABEL_ZOOM%%": str(html_cfg.get("pas_label_zoom_min", 17)),
    }
    html = HTML_TEMPLATE
    for k, v in repl.items():
        html = html.replace(k, v)
    (out_dir / "index.html").write_text(html, encoding="utf-8")

    # Drop orphan sidecars from non-viewer layers (e.g. left by older runs).
    viewer_names = {l["name"] for l in VIEWER_LAYERS}
    for layer in LAYERS:
        if layer["name"] not in viewer_names:
            (out_dir / f"{layer['name']}.js").unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path,
                        default=PROJECT_ROOT / "config" / "config.yaml")
    parser.add_argument("--out", type=Path, default=Path(DEFAULT_OUT))
    parser.add_argument("--geojson-only", action="store_true",
                        help="Only write the .geojson files (skip viewer + Excel).")
    parser.add_argument("--excel-only", action="store_true",
                        help="Only write the pas_50/pas_100 Excel workbook.")
    parser.add_argument("--html-only", action="store_true",
                        help="Only (re)write the viewer: index.html + viewer .js "
                             "sidecars + logo/libs (skip .geojson files + Excel).")
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    out_dir = args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"Export -> {out_dir}", file=sys.stderr)

    conn = connect(cfg)
    try:
        if args.excel_only:
            path = write_excel(conn, out_dir)
            print(f"  {path.name} (pas_50, pas_100)", file=sys.stderr)
            print("Done.", file=sys.stderr)
            return 0

        with conn.cursor() as cur:
            for layer in LAYERS:
                is_viewer = layer.get("viewer")
                # --html-only only needs the viewer layers.
                if args.html_only and not is_viewer:
                    continue
                # Canonical .geojson (skipped for --html-only).
                full = None
                if not args.html_only:
                    full = export_geojson(cur, layer)
                    (out_dir / f"{layer['name']}.geojson").write_text(full, encoding="utf-8")
                # Viewer .js sidecar (optionally lightened to stay responsive).
                if not args.geojson_only and is_viewer:
                    if layer.get("viewer_centroid"):
                        js_text = export_geojson(
                            cur, layer, centroid=True,
                            extra_exclude=layer.get("viewer_exclude"))
                    elif layer.get("viewer_simplify"):
                        js_text = export_geojson(
                            cur, layer, simplify=layer["viewer_simplify"],
                            extra_exclude=layer.get("viewer_exclude"))
                    elif layer.get("viewer_exclude"):
                        # full geom, but trim heavy properties from the sidecar
                        js_text = export_geojson(
                            cur, layer, extra_exclude=layer["viewer_exclude"])
                    else:
                        js_text = full if full is not None else export_geojson(cur, layer)
                    (out_dir / f"{layer['name']}.js").write_text(
                        f"var LAYER_{layer['name']} = {js_text};\n", encoding="utf-8")
                    n = feature_count(js_text)
                else:
                    n = feature_count(full) if full is not None else 0
                print(f"  {layer['name']:16s} {n:>7d} features", file=sys.stderr)

        if not args.geojson_only:
            write_html(out_dir, cfg.get("html") or {})
            print(f"  index.html written", file=sys.stderr)
            if not args.html_only:
                path = write_excel(conn, out_dir)
                print(f"  {path.name} (pas_50, pas_100)", file=sys.stderr)
    finally:
        conn.close()

    print("Done.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
