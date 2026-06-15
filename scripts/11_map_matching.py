#!/usr/bin/env python3
"""Map-matching: assign ``id_tronc`` and ``axe`` to every point in
``public.image`` by projecting it onto ``client.troncon_client``.

Adapted for this project from the RoadcareSig algorithm
(``55_RoadcareSigProd/.../src/map_matching.py``). Same 10-step SQL logic; the
changes here are the database wiring and the column names of this database:

- connection read from ``config/config.yaml`` ``source:`` block;
- ``public.image."sessionId"`` (was ``session_id``),
  ``public.image."cumulStartSession"`` (was ``cumuld_session``),
  ``public.session."geomCalibration"`` and
  ``client.troncon_client.geom`` (our ``LineStringM, 2154``) in place of the old
  ``geom_calib`` columns;
- ``public.image.id_tronc`` is ``BIGINT`` (the troncon PK type);
- the image/session geometries are SRID 0 but hold Lambert-93 (2154) coordinates,
  so their SRID is set to 2154 up front (coordinates unchanged) — otherwise the
  spatial joins and the 2154-typed output columns fail.

Usage
-----
    python scripts/11_map_matching.py
    python scripts/11_map_matching.py --buffer-radius 24 --min-segment-length 50 \\
        --perpendicular-iterations 2 --config config/config.yaml
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Any

import psycopg2
import psycopg2.extras
import yaml

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Geometry columns that hold Lambert-93 coords but may carry SRID 0.
SRID_FIX = [("public", "image", "geom"),
            ("public", "session", "geom"),
            ("public", "session", "geomCalibration")]


class MapMatcher:
    def __init__(self, db_config: dict[str, Any], buffer_radius: float = 24.0,
                 min_segment_length: float = 50.0, srid: int = 2154):
        self.db_config = db_config
        self.buffer_radius = buffer_radius
        self.min_segment_length = min_segment_length
        self.srid = srid
        self.conn = None

    # -- connection ---------------------------------------------------------
    def connect(self):
        self.conn = psycopg2.connect(
            host=self.db_config["host"], port=self.db_config["port"],
            user=self.db_config["user"], password=self.db_config["password"],
            dbname=self.db_config["database"])
        self.conn.autocommit = False
        logger.info("Database connection established")

    def disconnect(self):
        if self.conn:
            self.conn.close()
            logger.info("Database connection closed")

    # -- preparation --------------------------------------------------------
    def ensure_srid(self):
        """Stamp SRID on the image/session geometries when they are 0 (their
        coordinates are already Lambert-93 / 2154)."""
        logger.info("Step 0: ensuring SRID %s on image/session geometries", self.srid)
        with self.conn.cursor() as cur:
            for schema, table, col in SRID_FIX:
                cur.execute(
                    "SELECT Find_SRID(%s, %s, %s)", (schema, table, col))
                current = cur.fetchone()[0]
                if current == self.srid:
                    continue
                cur.execute(
                    f'UPDATE {schema}.{table} '
                    f'SET "{col}" = ST_SetSRID("{col}", %s) '
                    f'WHERE "{col}" IS NOT NULL AND ST_SRID("{col}") <> %s',
                    (self.srid, self.srid))
                logger.info("  set SRID %s on %s.%s.%s (%d rows)",
                            self.srid, schema, table, col, cur.rowcount)
        self.conn.commit()

    def check_and_create_image_fields(self):
        """Add the projection output columns to public.image if missing."""
        logger.info("Checking required fields in public.image")
        required = {
            "id_tronc": "BIGINT",                     # troncon PK type
            "axe": "TEXT",
            "prj_quality": "NUMERIC",
            "cumuld": "NUMERIC",
            "geom_prj": f"geometry(Point,{self.srid})",
            "ln_prj": f"geometry(LineString,{self.srid})",
            "seg_ss": f"geometry(LineString,{self.srid})",
            "seg_prj": f"geometry(LineString,{self.srid})",
            "d_angle_seg": "NUMERIC",
        }
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT lower(column_name) FROM information_schema.columns
                WHERE table_schema='public' AND table_name='image'
            """)
            existing = {r[0] for r in cur.fetchall()}
            created = []
            for name, typ in required.items():
                if name.lower() not in existing:
                    cur.execute(f"ALTER TABLE public.image ADD COLUMN {name} {typ}")
                    created.append(name)
            if created:
                logger.info("Created fields: %s", ", ".join(created))
        self.conn.commit()

    # -- algorithm steps ----------------------------------------------------
    def step1_update_seg_ss(self):
        logger.info("Step 1: seg_ss (±1 m session segment at each image)")
        with self.conn.cursor() as cur:
            cur.execute("""
                UPDATE public.image t1
                SET seg_ss = ST_Force2D(st_geometryN(
                    ST_LocateBetween(t2."geomCalibration",
                                     t1."cumulStartSession"-1.0,
                                     t1."cumulStartSession"+1.0), 1))
                FROM public.session t2
                WHERE t1."sessionId" = t2.id
                  AND GeometryType(ST_Force2D(st_geometryN(
                        ST_LocateBetween(t2."geomCalibration",
                                         t1."cumulStartSession"-1.0,
                                         t1."cumulStartSession"+1.0), 1))) = 'LINESTRING'
            """)
            logger.info("  seg_ss updated for %d images", cur.rowcount)
        self.conn.commit()

    def step2_projection_paire(self):
        logger.info("Step 2: traitement.projection_paire (session × troncon)")
        br = self.buffer_radius
        with self.conn.cursor() as cur:
            cur.execute("CREATE SCHEMA IF NOT EXISTS traitement")
            cur.execute("DROP TABLE IF EXISTS traitement.projection_paire")
            cur.execute(f"""
                CREATE TABLE traitement.projection_paire AS
                SELECT
                    t1.id AS session_id,
                    t2.id_tronc,
                    ST_Length(ST_Intersection(ST_Buffer(t2.geom,{br},'endcap=flat join=bevel'),t1.geom)) AS len_ss_on_client,
                    ST_Length(t1.geom) AS len_ss,
                    ST_Length(ST_Intersection(t2.geom,ST_Buffer(t1.geom,{br},'endcap=flat join=bevel'))) AS len_client_sur_ss,
                    ST_Length(t2.geom) AS len_client,
                    ST_Intersection(ST_Buffer(t2.geom,{br},'endcap=flat join=bevel'),t1.geom) AS geom_ss_sur_client,
                    ST_Intersection(t2.geom,ST_Buffer(t1.geom,{br},'endcap=flat join=bevel')) AS geom_client_sur_session,
                    degrees(st_angle(
                        ST_Intersection(ST_Buffer(t2.geom,{br},'endcap=flat join=bevel'),t1.geom),
                        ST_Intersection(t2.geom,ST_Buffer(t1.geom,{br},'endcap=flat join=bevel'))
                    )) AS angle_client_ss,
                    ST_Intersection(ST_Buffer(t2.geom,{br},'endcap=flat join=bevel'),ST_Buffer(t1.geom,{br})) AS geom_intersect
                FROM public.session t1
                JOIN client.troncon_client t2
                  ON ST_Distance(t2.geom,t1.geom) < {br + 1}
                 AND (ST_Intersects(ST_Buffer(t2.geom,{br},'endcap=flat join=bevel'), t1.geom)
                      OR ST_Intersects(t2.geom, ST_Buffer(t1.geom,{br},'endcap=flat join=bevel')))
            """)
            cur.execute("ALTER TABLE traitement.projection_paire ADD COLUMN id SERIAL")
            cur.execute("ALTER TABLE traitement.projection_paire ADD COLUMN is_paire BOOLEAN")
            cur.execute("ALTER TABLE traitement.projection_paire ADD COLUMN d_angle NUMERIC")
            cur.execute("UPDATE traitement.projection_paire SET d_angle = degrees(ST_Angle(geom_ss_sur_client,geom_client_sur_session))")
            cur.execute("ALTER TABLE traitement.projection_paire ADD PRIMARY KEY (id)")
            cur.execute("SELECT COUNT(*) FROM traitement.projection_paire")
            logger.info("  projection_paire rows: %d", cur.fetchone()[0])
        self.conn.commit()

    def step3_valid_pairs(self):
        logger.info("Step 3: flag valid session-troncon pairs")
        with self.conn.cursor() as cur:
            cur.execute("UPDATE traitement.projection_paire SET is_paire = false")
            cur.execute("""
                UPDATE traitement.projection_paire SET d_angle = CASE
                    WHEN abs(d_angle) BETWEEN 0 AND 180 THEN d_angle
                    WHEN abs(d_angle) BETWEEN 180 AND 360 THEN d_angle - 180 END
            """)
            cur.execute("UPDATE traitement.projection_paire SET d_angle = 0.0 WHERE d_angle IS NULL")
            cur.execute(f"""
                UPDATE traitement.projection_paire SET is_paire = true
                WHERE NOT (
                    (CASE WHEN abs(d_angle) BETWEEN 0 AND 180 THEN d_angle
                          WHEN abs(d_angle) BETWEEN 180 AND 360 THEN d_angle - 180 END
                     BETWEEN 45 AND 135
                     OR (len_client_sur_ss < {self.min_segment_length}
                         OR len_ss_on_client < {self.min_segment_length})))
            """)
            cur.execute("SELECT COUNT(*) FROM traitement.projection_paire WHERE is_paire")
            logger.info("  valid pairs: %d", cur.fetchone()[0])
        self.conn.commit()

    def step4_reset_image_projections(self):
        logger.info("Step 4: reset image projection fields")
        with self.conn.cursor() as cur:
            cur.execute("UPDATE public.image SET id_tronc=NULL, axe=NULL, "
                        "prj_quality=NULL, cumuld=NULL")
            logger.info("  reset %d images", cur.rowcount)
        self.conn.commit()

    def step5_projection_img_dist(self):
        logger.info("Step 5: traitement.projection_img_dist (image × pair)")
        image_buffer = min(5.0, self.buffer_radius / 5.0)
        with self.conn.cursor() as cur:
            cur.execute("DROP TABLE IF EXISTS traitement.projection_img_dist")
            cur.execute(f"""
                CREATE TABLE traitement.projection_img_dist AS
                SELECT t1.id, t2.id_tronc,
                       st_distance(t1.geom, t2.geom_client_sur_session) AS dist
                FROM public.image t1
                JOIN traitement.projection_paire t2
                  ON t2.is_paire IS TRUE
                 AND t1."sessionId" = t2.session_id
                 AND ST_Within(t1.geom, ST_Buffer(t2.geom_ss_sur_client,
                                                  {image_buffer}, 'endcap=round join=bevel'))
            """)
            logger.info("  image-troncon distances: %d (image buffer %.1f m)",
                        cur.rowcount, image_buffer)
        self.conn.commit()

    def step6_assign_best(self):
        logger.info("Step 6: assign nearest troncon to each image")
        with self.conn.cursor() as cur:
            cur.execute("""
                UPDATE public.image t1
                SET id_tronc = r1.id_tronc, prj_quality = r1.min_dist
                FROM (
                    SELECT t1.id, t1.id_tronc, r1.min_dist
                    FROM traitement.projection_img_dist t1
                    JOIN (SELECT id, min(dist) AS min_dist
                          FROM traitement.projection_img_dist GROUP BY id) r1
                      ON t1.id = r1.id AND t1.dist = r1.min_dist
                ) r1
                WHERE t1.id = r1.id
            """)
            logger.info("  assigned troncons to %d images", cur.rowcount)
        self.conn.commit()

    def step7_projections(self):
        logger.info("Step 7: projections (cumuld, geom_prj, ln_prj, seg_prj, angle)")
        with self.conn.cursor() as cur:
            cur.execute("""
                UPDATE public.image point
                SET cumuld = ST_M(ST_LineInterpolatePoint(line.geom, ST_LineLocatePoint(line.geom, point.geom))),
                    geom_prj = ST_Force2D(ST_LineInterpolatePoint(line.geom, ST_LineLocatePoint(line.geom, point.geom)))
                FROM client.troncon_client line
                WHERE point.id_tronc = line.id_tronc AND point.id_tronc IS NOT NULL
            """)
            cur.execute("UPDATE public.image SET ln_prj = ST_Force2D(ST_MakeLine(geom, geom_prj)) WHERE geom_prj IS NOT NULL")
            cur.execute("""
                UPDATE public.image t1
                SET seg_prj = ST_Force2D(st_geometryN(
                    ST_LocateBetween(t2.geom, t1.cumuld-1.0, t1.cumuld+1.0), 1))
                FROM client.troncon_client t2
                WHERE t1.id_tronc = t2.id_tronc AND t1.cumuld IS NOT NULL
            """)
            cur.execute("UPDATE public.image SET d_angle_seg = degrees(ST_Angle(seg_ss, seg_prj)) WHERE seg_ss IS NOT NULL AND seg_prj IS NOT NULL")
            cur.execute("""
                UPDATE public.image SET d_angle_seg = CASE
                    WHEN abs(d_angle_seg) BETWEEN 0 AND 180 THEN d_angle_seg
                    WHEN abs(d_angle_seg) BETWEEN 180 AND 360 THEN d_angle_seg - 180 END
                WHERE d_angle_seg IS NOT NULL
            """)
        self.conn.commit()

    def step8_handle_perpendicular(self):
        logger.info("Step 8: re-project perpendicular cases (45°-135°)")
        with self.conn.cursor() as cur:
            cur.execute("ALTER TABLE traitement.projection_img_dist ADD COLUMN IF NOT EXISTS gid SERIAL")
            cur.execute("ALTER TABLE traitement.projection_img_dist ADD COLUMN IF NOT EXISTS d_angle_seg NUMERIC")
            cur.execute("UPDATE traitement.projection_img_dist SET d_angle_seg = 0.0")
            cur.execute("""
                UPDATE traitement.projection_img_dist t1
                SET d_angle_seg = t2.d_angle_seg FROM public.image t2
                WHERE t1.id = t2.id AND t1.id_tronc = t2.id_tronc
            """)
            cur.execute("""
                UPDATE public.image
                SET id_tronc=NULL, prj_quality=NULL, cumuld=NULL, geom_prj=NULL, seg_prj=NULL
                WHERE d_angle_seg BETWEEN 45.0 AND 135.0
            """)
            cur.execute("""
                UPDATE public.image t1
                SET id_tronc = r1.id_tronc, prj_quality = r1.min_dist
                FROM (
                    SELECT t1.id, t1.id_tronc, r1.min_dist
                    FROM traitement.projection_img_dist t1
                    JOIN (SELECT id, min(dist) AS min_dist
                          FROM traitement.projection_img_dist
                          WHERE NOT d_angle_seg BETWEEN 45.0 AND 135.0 GROUP BY id) r1
                      ON t1.id = r1.id AND t1.dist = r1.min_dist
                ) r1
                WHERE t1.id = r1.id AND t1.id_tronc IS NULL
            """)
        self.conn.commit()

    def step9_final_projections(self):
        logger.info("Step 9: final projections for re-assigned images")
        with self.conn.cursor() as cur:
            cur.execute("""
                UPDATE public.image point
                SET cumuld = ST_M(ST_LineInterpolatePoint(line.geom, ST_LineLocatePoint(line.geom, point.geom))),
                    geom_prj = ST_Force2D(ST_LineInterpolatePoint(line.geom, ST_LineLocatePoint(line.geom, point.geom)))
                FROM client.troncon_client line
                WHERE (point.d_angle_seg BETWEEN 45.0 AND 135.0)
                  AND point.id_tronc = line.id_tronc AND point.id_tronc IS NOT NULL
            """)
            cur.execute("UPDATE public.image SET ln_prj = ST_Force2D(ST_MakeLine(geom, geom_prj)) WHERE d_angle_seg BETWEEN 45.0 AND 135.0 AND geom_prj IS NOT NULL")
            cur.execute("""
                UPDATE public.image t1
                SET seg_prj = ST_Force2D(st_geometryN(
                    ST_LocateBetween(t2.geom, t1.cumuld-1.0, t1.cumuld+1.0), 1))
                FROM client.troncon_client t2
                WHERE (t1.d_angle_seg BETWEEN 45.0 AND 135.0)
                  AND t1.id_tronc = t2.id_tronc AND t1.cumuld IS NOT NULL
            """)
            cur.execute("""
                UPDATE public.image t1
                SET seg_prj = ST_Force2D(st_geometryN(
                    ST_LocateBetween(t2.geom, t1.cumuld-1.0, t1.cumuld+1.0), 1))
                FROM client.troncon_client t2
                WHERE t1.id_tronc = t2.id_tronc AND t1.cumuld IS NOT NULL
            """)
            cur.execute("UPDATE public.image SET d_angle_seg = degrees(ST_Angle(seg_ss, seg_prj)) WHERE seg_ss IS NOT NULL AND seg_prj IS NOT NULL")
            cur.execute("""
                UPDATE public.image SET d_angle_seg = CASE
                    WHEN abs(d_angle_seg) BETWEEN 0 AND 180 THEN d_angle_seg
                    WHEN abs(d_angle_seg) BETWEEN 180 AND 360 THEN d_angle_seg - 180 END
                WHERE d_angle_seg IS NOT NULL
            """)
        self.conn.commit()

    def step10_update_axe(self):
        logger.info("Step 10: set axe from troncon_client")
        with self.conn.cursor() as cur:
            cur.execute("""
                UPDATE public.image t1 SET axe = t2.axe
                FROM client.troncon_client t2
                WHERE t1.id_tronc = t2.id_tronc AND t1.axe IS NULL
            """)
            logger.info("  axe set for %d images", cur.rowcount)
        self.conn.commit()

    def get_statistics(self) -> dict[str, Any]:
        with self.conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM public.image")
            total = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM public.image WHERE id_tronc IS NOT NULL")
            matched = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM traitement.projection_paire WHERE is_paire")
            valid = cur.fetchone()[0]
            cur.execute("SELECT COUNT(DISTINCT session_id) FROM traitement.projection_paire WHERE is_paire")
            sessions = cur.fetchone()[0]
        return {"total_images": total, "matched_images": matched,
                "match_rate_percent": round(matched / total * 100 if total else 0, 2),
                "valid_pairs": valid, "sessions_processed": sessions}

    def run(self, perpendicular_iterations: int = 2) -> dict[str, Any]:
        logger.info("Map-matching: db=%s buffer=%.1fm min_seg=%.1fm iters=%d",
                    self.db_config["database"], self.buffer_radius,
                    self.min_segment_length, perpendicular_iterations)
        try:
            self.connect()
            self.ensure_srid()
            self.check_and_create_image_fields()
            self.step1_update_seg_ss()
            self.step2_projection_paire()
            self.step3_valid_pairs()
            self.step4_reset_image_projections()
            self.step5_projection_img_dist()
            self.step6_assign_best()
            self.step7_projections()
            for i in range(perpendicular_iterations):
                logger.info("Perpendicular iteration %d/%d", i + 1, perpendicular_iterations)
                self.step8_handle_perpendicular()
            self.step9_final_projections()
            self.step10_update_axe()
            results = self.get_statistics()
            logger.info("Done: %s", results)
            return results
        except Exception as exc:
            logger.error("Fatal error: %s", exc)
            if self.conn:
                self.conn.rollback()
            raise
        finally:
            self.disconnect()


def load_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    if not raw or "source" not in raw:
        raise ValueError(f"Config {path} is missing the 'source' section")
    src = raw["source"]
    for key in ("host", "port", "user", "password", "database"):
        if key not in src:
            raise ValueError(f"Config 'source' is missing key: {key}")
    return src


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-c", "--config", type=Path,
                        default=PROJECT_ROOT / "config" / "config.yaml")
    parser.add_argument("-i", "--perpendicular-iterations", type=int, default=2)
    parser.add_argument("-b", "--buffer-radius", type=float, default=24.0)
    parser.add_argument("-s", "--min-segment-length", type=float, default=50.0)
    parser.add_argument("--srid", type=int, default=2154,
                        help="SRID of troncon_client / output projections.")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    if args.perpendicular_iterations < 1:
        parser.error("perpendicular_iterations must be >= 1")
    if args.buffer_radius <= 0 or args.min_segment_length <= 0:
        parser.error("buffer-radius and min-segment-length must be > 0")
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    db_config = load_config(args.config)
    matcher = MapMatcher(db_config, args.buffer_radius, args.min_segment_length,
                         args.srid)
    try:
        r = matcher.run(args.perpendicular_iterations)
    except Exception as exc:  # noqa: BLE001
        print(f"Map-matching failed: {exc}", file=sys.stderr)
        return 1
    print("\n=== Map-matching Results ===")
    print(f"Database: {db_config['database']}")
    print(f"Total images:        {r['total_images']}")
    print(f"Successfully matched:{r['matched_images']:>7}  ({r['match_rate_percent']}%)")
    print(f"Valid pairs:         {r['valid_pairs']}")
    print(f"Sessions processed:  {r['sessions_processed']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
