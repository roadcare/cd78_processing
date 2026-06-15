"""Task 3.1 / 3.2 — export the rendu layers to GeoJSON and a Leaflet viewer.

3.1 — writes one ``<layer>.geojson`` (EPSG:4326) per layer into ``--out``
(default ``D:\\Tmp\\cd78_exports``):

  client.troncon_client, client.itineraires_v2, client.pas_50, client.pas_100,
  public.session, public.image, public.road_data (classe in
  'Dégradation chaussée' / 'Largeur').

  Some columns are dropped for ``image`` and ``session`` (see ``LAYERS``). Every
  geometry is transformed to 4326 (SRID 0 is assumed 2154).

3.2 — writes ``index.html`` + one ``<layer>.js`` per layer (each assigns a
global ``LAYER_<name>``). The HTML is a Leaflet map; the ``.js`` sidecars load
via ``<script>`` so the viewer also works straight from ``file://`` (a plain
``fetch`` of local GeoJSON is blocked by browsers). Default-visible layers:
``pas_100``, ``troncon_client``, ``road_data``, ``image``; all layers can be
toggled and there is a text filter. Image / road_data popups show the picture
(column ``filename``).

Usage
-----
    python scripts/31_export_rendu.py
    python scripts/31_export_rendu.py --out D:\\Tmp\\cd78_exports --geojson-only
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

# name | schema | table | exclude cols | where | default visible | popup image | style
LAYERS = [
    {"name": "troncon_client", "schema": "client", "table": "troncon_client",
     "exclude": [], "where": None, "visible": True, "popup_img": False,
     "color": "#1f78b4"},
    {"name": "itineraires_v2", "schema": "client", "table": "itineraires_v2",
     "exclude": [], "where": None, "visible": False, "popup_img": False,
     "color": "#6a3d9a"},
    {"name": "pas_50", "schema": "client", "table": "pas_50",
     "exclude": [], "where": None, "visible": False, "popup_img": False,
     "color": "#33a02c"},
    {"name": "pas_100", "schema": "client", "table": "pas_100",
     "exclude": [], "where": None, "visible": True, "popup_img": False,
     "color": "#e31a1c"},
    {"name": "session", "schema": "public", "table": "session",
     "exclude": ["geomCalibration", "surfaceGrade", "structuralGrade",
                 "calibrationId", "calibrationError", "calibrationErrorMailSent",
                 "calibrationDone", "videoToImagesDone", "metadataId", "state"],
     "where": None, "visible": False, "popup_img": False, "color": "#ff7f00"},
    {"name": "image", "schema": "public", "table": "image",
     "exclude": ["geomCalibration", "cumulEndSession", "prIdStart",
                 "prDistanceStart", "elapsedTime", "road_cumul", "road_id",
                 "geom_prj", "ln_prj", "seg_ss", "seg_prj", "d_angle_seg",
                 "geom_visible"],
     "where": None, "visible": True, "popup_img": True, "color": "#000000"},
    {"name": "road_data", "schema": "public", "table": "road_data",
     "exclude": ["pixels_coords"], "visible": True, "popup_img": True,
     "color": "#b15928",
     "where": "classe IN ('Dégradation chaussée','Largeur')",
     "viewer_centroid": True,
     "viewer_exclude": ["comment", "sessionName", "sessionId", "image_id"]},
]


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
    cur.execute(
        """
        SELECT a.attname FROM pg_attribute a
        JOIN pg_class c ON c.oid = a.attrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = %s AND c.relname = %s
          AND a.attnum > 0 AND NOT a.attisdropped
        ORDER BY a.attnum
        """, (schema, table))
    return [r[0] for r in cur.fetchall()]


def export_geojson(cur, layer: dict, geom_col: str = "geom",
                   maxdigits: int = 6, simplify: float = 0.0,
                   centroid: bool = False, extra_exclude: list[str] | None = None) -> str:
    """Return the FeatureCollection text (4326) for one layer.

    ``maxdigits`` caps coordinate precision; ``simplify`` (metres, source CRS)
    thins geometry; ``centroid`` replaces each geometry by an interior point.
    The last two are used only for the lighter viewer copies, never for the
    canonical ``.geojson``.
    """
    cols = fetch_columns(cur, layer["schema"], layer["table"])
    drop = set(layer["exclude"]) | {geom_col} | set(extra_exclude or [])
    keep = [c for c in cols if c not in drop]
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
    select_cols = sql.SQL(", ").join(
        [sql.Identifier(c) for c in keep] + [geom_t])
    where = sql.SQL(" WHERE " + layer["where"]) if layer["where"] else sql.SQL("")
    query = sql.SQL(
        """
        SELECT json_build_object(
                 'type', 'FeatureCollection',
                 'features', COALESCE(
                     json_agg(ST_AsGeoJSON(t.*, {gcol}, {md})::json), '[]'::json)
               )::text
        FROM (SELECT {cols} FROM {sch}.{tbl}{where}) t
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


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>CD78 — rendu</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<style>
  html,body{{margin:0;height:100%}}
  #map{{position:absolute;top:0;bottom:0;left:0;right:0}}
  #filter{{position:absolute;z-index:1000;top:10px;left:60px;background:#fff;
           padding:6px 8px;border-radius:4px;box-shadow:0 1px 4px rgba(0,0,0,.3);
           font:13px sans-serif}}
  #filter input{{width:180px}}
  .leaflet-popup-content img{{max-width:260px;height:auto;display:block;margin-top:4px}}
</style>
</head>
<body>
<div id="map"></div>
<div id="filter">
  filtre&nbsp;: <input id="q" type="text" placeholder="texte (axe, classe…) puis Entrée"/>
  <button id="clear">×</button>
</div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
{scripts}
<script>
var LAYERS = {layers_cfg};
var map = L.map('map', {{preferCanvas:true}});
L.tileLayer("{tile_url}", {{maxZoom:20, subdomains:"{subdomains}",
  attribution:"{attribution}"}}).addTo(map);

function popupHtml(props, withImg){{
  var rows = Object.keys(props).filter(function(k){{return props[k]!==null;}})
    .map(function(k){{return '<b>'+k+'</b>: '+props[k];}}).join('<br/>');
  var html = '<div style="max-height:220px;overflow:auto">'+rows+'</div>';
  if(withImg && props.filename){{
    html += '<a href="'+props.filename+'" target="_blank"><img src="'+props.filename+'"/></a>';
  }}
  return html;
}}

var store = {{}};
function build(cfg, q){{
  var data = window['LAYER_'+cfg.name];
  if(!data) return null;
  var feats = data.features;
  if(q){{ q=q.toLowerCase();
    feats = feats.filter(function(f){{
      return JSON.stringify(f.properties).toLowerCase().indexOf(q)>=0; }});
  }}
  return L.geoJSON({{type:'FeatureCollection',features:feats}}, {{
    style: {{color:cfg.color, weight:2, fillColor:cfg.color, fillOpacity:.25}},
    pointToLayer: function(f,latlng){{
      return L.circleMarker(latlng,{{radius:4,color:cfg.color,fillOpacity:.8}});}},
    onEachFeature: function(f,lyr){{
      lyr.bindPopup(popupHtml(f.properties, cfg.popup_img), {{maxWidth:300}});}}
  }});
}}

function render(q){{
  LAYERS.forEach(function(cfg){{
    var prev = store[cfg.name];
    var wasOn = prev ? map.hasLayer(prev) : cfg.visible;
    if(prev){{ map.removeLayer(prev); ctrl.removeLayer(prev); }}
    var lyr = build(cfg, q);
    store[cfg.name] = lyr;
    if(lyr){{ ctrl.addOverlay(lyr, cfg.label); if(wasOn) lyr.addTo(map); }}
  }});
}}

var ctrl = L.control.layers(null, null, {{collapsed:false}}).addTo(map);
render('');

// fit to the default-visible data
var b = L.latLngBounds([]);
LAYERS.forEach(function(c){{ if(c.visible && store[c.name]){{
  try{{ b.extend(store[c.name].getBounds()); }}catch(e){{}} }} }});
if(b.isValid()) map.fitBounds(b); else map.setView([48.8,1.9],10);

document.getElementById('q').addEventListener('keydown', function(e){{
  if(e.key==='Enter') render(this.value.trim()); }});
document.getElementById('clear').addEventListener('click', function(){{
  document.getElementById('q').value=''; render(''); }});
</script>
</body>
</html>
"""


def write_excel(conn, out_dir: Path) -> Path:
    """Write client.pas_50 and client.pas_100 as two sheets of one .xlsx.

    The geometry is exported as WKT text (``geom`` column) so the table stays
    a flat spreadsheet.
    """
    import pandas as pd

    path = out_dir / "pas.xlsx"
    with conn.cursor() as cur, pd.ExcelWriter(path, engine="openpyxl") as writer:
        for table in ("pas_50", "pas_100"):
            cols = fetch_columns(cur, "client", table)
            sel = ", ".join(
                (f'ST_AsText("{c}") AS "{c}"' if c == "geom" else f'"{c}"')
                for c in cols)
            df = pd.read_sql(f"SELECT {sel} FROM client.{table} ORDER BY id", conn)
            df.to_excel(writer, sheet_name=table, index=False)
    return path


def write_html(out_dir: Path, html_cfg: dict[str, Any]) -> None:
    scripts = "\n".join(
        f'<script src="{lyr["name"]}.js"></script>' for lyr in LAYERS)
    layers_cfg = json.dumps([
        {"name": l["name"], "label": f'{l["schema"]}.{l["table"]}',
         "color": l["color"], "visible": l["visible"], "popup_img": l["popup_img"]}
        for l in LAYERS])
    html = HTML_TEMPLATE.format(
        scripts=scripts, layers_cfg=layers_cfg,
        tile_url=html_cfg.get("tile_url", "https://{s}.tile.openstreetmap.de/{z}/{x}/{y}.png"),
        subdomains=html_cfg.get("tile_subdomains", "abc"),
        attribution=html_cfg.get("tile_attribution", "&copy; OpenStreetMap"))
    (out_dir / "index.html").write_text(html, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path,
                        default=PROJECT_ROOT / "config" / "config.yaml")
    parser.add_argument("--out", type=Path, default=Path(DEFAULT_OUT))
    parser.add_argument("--geojson-only", action="store_true",
                        help="Only write the .geojson files (skip viewer + Excel).")
    parser.add_argument("--excel-only", action="store_true",
                        help="Only write the pas_50/pas_100 Excel workbook.")
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
                text = export_geojson(cur, layer)
                (out_dir / f"{layer['name']}.geojson").write_text(text, encoding="utf-8")
                if not args.geojson_only:
                    # Viewer copy: optionally lightened to stay responsive.
                    js_text = text
                    if layer.get("viewer_centroid"):
                        js_text = export_geojson(
                            cur, layer, centroid=True,
                            extra_exclude=layer.get("viewer_exclude"))
                    elif layer.get("viewer_simplify"):
                        js_text = export_geojson(
                            cur, layer, simplify=layer["viewer_simplify"],
                            extra_exclude=layer.get("viewer_exclude"))
                    (out_dir / f"{layer['name']}.js").write_text(
                        f"var LAYER_{layer['name']} = {js_text};\n", encoding="utf-8")
                print(f"  {layer['name']:16s} {feature_count(text):>7d} features",
                      file=sys.stderr)

        if not args.geojson_only:
            write_html(out_dir, cfg.get("html") or {})
            print(f"  index.html written", file=sys.stderr)
            path = write_excel(conn, out_dir)
            print(f"  {path.name} (pas_50, pas_100)", file=sys.stderr)
    finally:
        conn.close()

    print("Done.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
