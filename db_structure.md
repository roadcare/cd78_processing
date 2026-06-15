# Database structure — `cd78_v2026`

_Generated 2026-06-15 23:23:50 from `localhost:5433` (user `postgres`)._

- PostgreSQL: `PostgreSQL 17.6 on x86_64-windows, compiled by msvc-19.44.35213, 64-bit`
- Schemas inspected: `client`, `public`, `rendu`
- Edit `db_descriptions.yaml` to fill in descriptions. They are preserved on re-run.

## About this database

_Add a description of the database and its use case in_ `db_descriptions.yaml` _under the_ `_database:` _key. It will be preserved across re-runs._

## Overview

| Schema | Exists | Tables |
|---|:---:|---:|
| `client` | YES | 7 |
| `public` | YES | 3 |
| `rendu` | NO | 0 |

## Contents

- [`client`](#schema-client)
- [`public`](#schema-public)
- [`rendu`](#schema-rendu)

## Schema `client` <a id="schema-client"></a>

| Table | Rows (est.) | Size | Description |
|---|---:|---:|---|
| [`20250916_trafic`](#tbl-client-20250916_trafic) | 506 | 1.0 MB | information about traffic on the road network |
| [`20250916_trafic_most_recent`](#tbl-client-20250916_trafic_most_recent) | 505 | 2.0 MB |  |
| [`20260227_couche_roulement`](#tbl-client-20260227_couche_roulement) | 2,299 | 1.6 MB | information about the road surface / pavement type on the road network |
| [`20260227_couche_roulement_most_recent`](#tbl-client-20260227_couche_roulement_most_recent) | 2,005 | 2.7 MB |  |
| [`20260301_trafic_couche_roulement_intersection`](#tbl-client-20260301_trafic_couche_roulement_intersection) | 1,635 | 2.8 MB |  |
| [`itineraires_v2`](#tbl-client-itineraires_v2) | -1 | 136.0 KB |  |
| [`troncon_client`](#tbl-client-troncon_client) | 2,064 | 3.1 MB |  |

### `client.20250916_trafic` <a id="tbl-client-20250916_trafic"></a>

**Description:** information about traffic on the road network

- Row estimate: **506**  - Size: **1.0 MB**

**Columns**

| # | Column | Type | Nullable | Default | PK | Description |
|---:|---|---|:---:|---|:---:|---|
| 1 | `id` | `integer` | NO | nextval('client.trafic_id_seq'::regclass) | PK |  |
| 2 | `geom` | `geometry(MultiLineString,3949)` | YES |  |  | geometry of the traffic measurement segments |
| 3 | `axe` | `character varying(254)` | YES |  |  | name of axe, id of the road in linear referencing system |
| 4 | `cumuld` | `bigint` | YES |  |  | cumulative distance along the axe for the start of the segment (m value in LRS) |
| 5 | `cumulf` | `bigint` | YES |  |  | cumulative distance along the axe for the end of the segment (m value in LRS) |
| 6 | `plod` | `character varying(254)` | YES |  |  | position of the start of the segment (m value in LRS) |
| 7 | `absd` | `bigint` | YES |  |  | absolute distance from the start of the axe for the start of the segment (m value in LRS) |
| 8 | `plof` | `character varying(254)` | YES |  |  | position of the end of the segment (m value in LRS) |
| 9 | `absf` | `bigint` | YES |  |  | absolute distance from the start of the axe for the end of the segment (m value in LRS) |
| 10 | `xd` | `double precision` | YES |  |  | longitude value of the start of the segment |
| 11 | `yd` | `double precision` | YES |  |  | latitude value of the start of the segment |
| 12 | `zd` | `double precision` | YES |  |  | elevation value of the start of the segment |
| 13 | `xf` | `double precision` | YES |  |  | longitude value of the end of the segment |
| 14 | `yf` | `double precision` | YES |  |  | latitude value of the end of the segment |
| 15 | `zf` | `double precision` | YES |  |  | elevation value of the end of the segment |
| 16 | `date_modif` | `date` | YES |  |  | date of the last modification of the traffic measurement segment |
| 17 | `num_sect` | `character varying(254)` | YES |  |  |  |
| 18 | `tmja` | `double precision` | YES |  |  |  |
| 19 | `p100_pl` | `double precision` | YES |  |  |  |
| 20 | `annee` | `double precision` | YES |  |  |  |
| 21 | `nb_pl` | `double precision` | YES |  |  |  |
| 22 | `sens1_de` | `character varying(100)` | YES |  |  |  |
| 23 | `sens1_vers` | `character varying(100)` | YES |  |  |  |
| 24 | `sens2_de` | `character varying(100)` | YES |  |  |  |
| 25 | `sens2_vers` | `character varying(100)` | YES |  |  |  |
| 26 | `tmja_sens1` | `bigint` | YES |  |  |  |
| 27 | `tmja_sens2` | `bigint` | YES |  |  |  |
| 28 | `tmja_sens3` | `bigint` | YES |  |  |  |
| 29 | `tmjo_sens1` | `bigint` | YES |  |  |  |
| 30 | `tmjo_sens2` | `bigint` | YES |  |  |  |
| 31 | `tmjo_sens3` | `bigint` | YES |  |  |  |
| 32 | `hpm_sens1` | `character varying(20)` | YES |  |  |  |
| 33 | `h_hpm_s1` | `character varying(20)` | YES |  |  |  |
| 34 | `hps_sens1` | `character varying(20)` | YES |  |  |  |
| 35 | `h_hps_s1` | `character varying(20)` | YES |  |  |  |
| 36 | `hpm_sens2` | `character varying(20)` | YES |  |  |  |
| 37 | `h_hpm_s2` | `character varying(20)` | YES |  |  |  |
| 38 | `hps_sens2` | `character varying(20)` | YES |  |  |  |
| 39 | `h_hps_s2` | `character varying(20)` | YES |  |  |  |

**Indexes**

| Name | Unique | Primary | Definition |
|---|:---:|:---:|---|
| `trafic_pkey` | YES | YES | `CREATE UNIQUE INDEX trafic_pkey ON client."20250916_trafic" USING btree (id)` |

### `client.20250916_trafic_most_recent` <a id="tbl-client-20250916_trafic_most_recent"></a>

**Description:** _(add via db_descriptions.yaml)_

- Row estimate: **505**  - Size: **2.0 MB**

**Columns**

| # | Column | Type | Nullable | Default | PK | Description |
|---:|---|---|:---:|---|:---:|---|
| 1 | `source_id` | `integer` | NO |  |  |  |
| 2 | `geom` | `geometry(MultiLineString,3949)` | YES |  |  |  |
| 3 | `axe` | `character varying(254)` | YES |  |  |  |
| 4 | `cumuld` | `bigint` | YES |  |  |  |
| 5 | `cumulf` | `bigint` | YES |  |  |  |
| 6 | `plod` | `character varying(254)` | YES |  |  |  |
| 7 | `absd` | `bigint` | YES |  |  |  |
| 8 | `plof` | `character varying(254)` | YES |  |  |  |
| 9 | `absf` | `bigint` | YES |  |  |  |
| 10 | `xd` | `double precision` | YES |  |  |  |
| 11 | `yd` | `double precision` | YES |  |  |  |
| 12 | `zd` | `double precision` | YES |  |  |  |
| 13 | `xf` | `double precision` | YES |  |  |  |
| 14 | `yf` | `double precision` | YES |  |  |  |
| 15 | `zf` | `double precision` | YES |  |  |  |
| 16 | `date_modif` | `date` | YES |  |  |  |
| 17 | `num_sect` | `character varying(254)` | YES |  |  |  |
| 18 | `tmja` | `double precision` | YES |  |  |  |
| 19 | `p100_pl` | `double precision` | YES |  |  |  |
| 20 | `annee` | `double precision` | YES |  |  |  |
| 21 | `nb_pl` | `double precision` | YES |  |  |  |
| 22 | `sens1_de` | `character varying(100)` | YES |  |  |  |
| 23 | `sens1_vers` | `character varying(100)` | YES |  |  |  |
| 24 | `sens2_de` | `character varying(100)` | YES |  |  |  |
| 25 | `sens2_vers` | `character varying(100)` | YES |  |  |  |
| 26 | `tmja_sens1` | `bigint` | YES |  |  |  |
| 27 | `tmja_sens2` | `bigint` | YES |  |  |  |
| 28 | `tmja_sens3` | `bigint` | YES |  |  |  |
| 29 | `tmjo_sens1` | `bigint` | YES |  |  |  |
| 30 | `tmjo_sens2` | `bigint` | YES |  |  |  |
| 31 | `tmjo_sens3` | `bigint` | YES |  |  |  |
| 32 | `hpm_sens1` | `character varying(20)` | YES |  |  |  |
| 33 | `h_hpm_s1` | `character varying(20)` | YES |  |  |  |
| 34 | `hps_sens1` | `character varying(20)` | YES |  |  |  |
| 35 | `h_hps_s1` | `character varying(20)` | YES |  |  |  |
| 36 | `hpm_sens2` | `character varying(20)` | YES |  |  |  |
| 37 | `h_hpm_s2` | `character varying(20)` | YES |  |  |  |
| 38 | `hps_sens2` | `character varying(20)` | YES |  |  |  |
| 39 | `h_hps_s2` | `character varying(20)` | YES |  |  |  |
| 40 | `id` | `bigint` | NO |  | PK |  |
| 41 | `is_overlapping` | `boolean` | YES | false |  |  |

**Indexes**

| Name | Unique | Primary | Definition |
|---|:---:|:---:|---|
| `20250916_trafic_most_recent_pkey` | YES | YES | `CREATE UNIQUE INDEX "20250916_trafic_most_recent_pkey" ON client."20250916_trafic_most_recent" USING btree (id)` |

### `client.20260227_couche_roulement` <a id="tbl-client-20260227_couche_roulement"></a>

**Description:** information about the road surface / pavement type on the road network

- Row estimate: **2,299**  - Size: **1.6 MB**

**Columns**

| # | Column | Type | Nullable | Default | PK | Description |
|---:|---|---|:---:|---|:---:|---|
| 1 | `id` | `integer` | NO | nextval('client."20260227_couche_roulement_id_seq"'::regclass) | PK |  |
| 2 | `geom` | `geometry(MultiLineString,3949)` | YES |  |  | geometry of the road surface segments |
| 3 | `axe` | `character varying(254)` | YES |  |  | name of axe, id of the road in linear referencing system |
| 4 | `cumuld` | `bigint` | YES |  |  | cumulative distance along the axe for the start of the segment (m value in LRS) |
| 5 | `cumulf` | `bigint` | YES |  |  | cumulative distance along the axe for the end of the segment (m value in LRS) |
| 6 | `plod` | `character varying(254)` | YES |  |  | position of the start of the segment (m value in LRS) |
| 7 | `absd` | `bigint` | YES |  |  | absolute distance from the start of the axe for the start of the segment (m value in LRS) |
| 8 | `plof` | `character varying(254)` | YES |  |  | position of the end of the segment (m value in LRS) |
| 9 | `absf` | `bigint` | YES |  |  | absolute distance from the start of the axe for the end of the segment (m value in LRS) |
| 10 | `subdivisio` | `character varying(254)` | YES |  |  |  |
| 11 | `generation` | `bigint` | YES |  |  |  |
| 12 | `annee` | `character varying(5)` | YES |  |  | year of the last modification of the road surface segment |
| 13 | `nature_cr` | `character varying(254)` | YES |  |  | nature of the road surface / pavement type (e.g., asphalt, concrete, gravel) |

**Indexes**

| Name | Unique | Primary | Definition |
|---|:---:|:---:|---|
| `20260227_couche_roulement_pkey` | YES | YES | `CREATE UNIQUE INDEX "20260227_couche_roulement_pkey" ON client."20260227_couche_roulement" USING btree (id)` |

### `client.20260227_couche_roulement_most_recent` <a id="tbl-client-20260227_couche_roulement_most_recent"></a>

**Description:** _(add via db_descriptions.yaml)_

- Row estimate: **2,005**  - Size: **2.7 MB**

**Columns**

| # | Column | Type | Nullable | Default | PK | Description |
|---:|---|---|:---:|---|:---:|---|
| 1 | `source_id` | `integer` | NO |  |  |  |
| 2 | `geom` | `geometry(MultiLineString,3949)` | YES |  |  |  |
| 3 | `axe` | `character varying(254)` | YES |  |  |  |
| 4 | `cumuld` | `bigint` | YES |  |  |  |
| 5 | `cumulf` | `bigint` | YES |  |  |  |
| 6 | `plod` | `character varying(254)` | YES |  |  |  |
| 7 | `absd` | `bigint` | YES |  |  |  |
| 8 | `plof` | `character varying(254)` | YES |  |  |  |
| 9 | `absf` | `bigint` | YES |  |  |  |
| 10 | `subdivisio` | `character varying(254)` | YES |  |  |  |
| 11 | `generation` | `bigint` | YES |  |  |  |
| 12 | `annee` | `character varying(5)` | YES |  |  |  |
| 13 | `nature_cr` | `character varying(254)` | YES |  |  |  |
| 14 | `id` | `bigint` | NO |  | PK |  |
| 15 | `is_overlapping` | `boolean` | YES | false |  |  |

**Indexes**

| Name | Unique | Primary | Definition |
|---|:---:|:---:|---|
| `20260227_couche_roulement_most_recent_pkey` | YES | YES | `CREATE UNIQUE INDEX "20260227_couche_roulement_most_recent_pkey" ON client."20260227_couche_roulement_most_recent" USING btree (id)` |

### `client.20260301_trafic_couche_roulement_intersection` <a id="tbl-client-20260301_trafic_couche_roulement_intersection"></a>

**Description:** _(add via db_descriptions.yaml)_

- Row estimate: **1,635**  - Size: **2.8 MB**

**Columns**

| # | Column | Type | Nullable | Default | PK | Description |
|---:|---|---|:---:|---|:---:|---|
| 1 | `id` | `bigint` | NO |  | PK |  |
| 2 | `axe` | `text` | YES |  |  |  |
| 3 | `cumuld` | `bigint` | YES |  |  |  |
| 4 | `cumulf` | `bigint` | YES |  |  |  |
| 5 | `geom` | `geometry(MultiLineString,3949)` | YES |  |  |  |
| 6 | `nb_pl` | `double precision` | YES |  |  |  |
| 7 | `nature_cr` | `text` | YES |  |  |  |
| 8 | `nb_pl_final` | `double precision` | YES |  |  |  |
| 9 | `nature_cr_final` | `character varying(254)` | YES |  |  |  |
| 10 | `plod` | `character varying(254)` | YES |  |  |  |
| 11 | `absd` | `bigint` | YES |  |  |  |
| 12 | `plof` | `character varying(254)` | YES |  |  |  |
| 13 | `absf` | `bigint` | YES |  |  |  |

**Indexes**

| Name | Unique | Primary | Definition |
|---|:---:|:---:|---|
| `20260301_trafic_couche_roulement_intersection_pkey` | YES | YES | `CREATE UNIQUE INDEX "20260301_trafic_couche_roulement_intersection_pkey" ON client."20260301_trafic_couche_roulement_intersection" USING btree (id)` |

### `client.itineraires_v2` <a id="tbl-client-itineraires_v2"></a>

**Description:** _(add via db_descriptions.yaml)_

- Row estimate: **-1**  - Size: **136.0 KB**

**Columns**

| # | Column | Type | Nullable | Default | PK | Description |
|---:|---|---|:---:|---|:---:|---|
| 1 | `id` | `integer` | NO | nextval('client.itineraires_v2_id_seq'::regclass) | PK |  |
| 2 | `geom` | `geometry(MultiLineStringM,3949)` | YES |  |  |  |
| 3 | `num_iti` | `bigint` | YES |  |  |  |
| 4 | `auscultation` | `bigint` | YES |  |  |  |
| 5 | `axe` | `character varying(254)` | YES |  |  |  |
| 6 | `pr_d` | `bigint` | YES |  |  |  |
| 7 | `abs_d` | `bigint` | YES |  |  |  |
| 8 | `pr_f` | `bigint` | YES |  |  |  |
| 9 | `abs_f` | `bigint` | YES |  |  |  |
| 10 | `lineaire_m` | `bigint` | YES |  |  |  |
| 11 | `pr_abs_d` | `character varying(254)` | YES |  |  |  |
| 12 | `pr_abs_f` | `character varying(254)` | YES |  |  |  |
| 13 | `m_ref_d` | `bigint` | YES |  |  |  |
| 14 | `m_ref_f` | `bigint` | YES |  |  |  |
| 15 | `loc_error` | `character varying(50)` | YES |  |  |  |
| 16 | `shape_length` | `double precision` | YES |  |  |  |

**Indexes**

| Name | Unique | Primary | Definition |
|---|:---:|:---:|---|
| `itineraires_v2_pkey` | YES | YES | `CREATE UNIQUE INDEX itineraires_v2_pkey ON client.itineraires_v2 USING btree (id)` |

### `client.troncon_client` <a id="tbl-client-troncon_client"></a>

**Description:** _(add via db_descriptions.yaml)_

- Row estimate: **2,064**  - Size: **3.1 MB**

**Columns**

| # | Column | Type | Nullable | Default | PK | Description |
|---:|---|---|:---:|---|:---:|---|
| 1 | `id_tronc` | `bigint` | NO |  | PK |  |
| 2 | `id` | `bigint` | YES |  |  |  |
| 3 | `axe` | `text` | YES |  |  |  |
| 4 | `cumuld` | `bigint` | YES |  |  |  |
| 5 | `cumulf` | `bigint` | YES |  |  |  |
| 6 | `geom` | `geometry(LineStringM,2154)` | YES |  |  |  |
| 7 | `nb_pl` | `double precision` | YES |  |  |  |
| 8 | `nature_cr` | `text` | YES |  |  |  |
| 9 | `nb_pl_final` | `double precision` | YES |  |  |  |
| 10 | `nature_cr_final` | `character varying(254)` | YES |  |  |  |
| 11 | `plod` | `character varying(254)` | YES |  |  |  |
| 12 | `absd` | `bigint` | YES |  |  |  |
| 13 | `plof` | `character varying(254)` | YES |  |  |  |
| 14 | `absf` | `bigint` | YES |  |  |  |
| 15 | `len_shp` | `numeric` | YES |  |  |  |
| 16 | `len_cumul` | `bigint` | YES |  |  |  |

**Indexes**

| Name | Unique | Primary | Definition |
|---|:---:|:---:|---|
| `troncon_client_pkey` | YES | YES | `CREATE UNIQUE INDEX troncon_client_pkey ON client.troncon_client USING btree (id_tronc)` |

## Schema `public` <a id="schema-public"></a>

| Table | Rows (est.) | Size | Description |
|---|---:|---:|---|
| [`image`](#tbl-public-image) | 12,378 | 54.1 MB |  |
| [`road_data`](#tbl-public-road_data) | 69,781 | 140.8 MB |  |
| [`session`](#tbl-public-session) | 14 | 896.0 KB |  |

### `public.image` <a id="tbl-public-image"></a>

**Description:** _(add via db_descriptions.yaml)_

- Row estimate: **12,378**  - Size: **54.1 MB**

**Columns**

| # | Column | Type | Nullable | Default | PK | Description |
|---:|---|---|:---:|---|:---:|---|
| 1 | `id` | `uuid` | NO |  | PK |  |
| 2 | `geom` | `geometry` | NO |  |  |  |
| 3 | `geomCalibration` | `geometry` | YES |  |  |  |
| 4 | `cumulStartSession` | `double precision` | YES |  |  |  |
| 5 | `cumulEndSession` | `double precision` | YES |  |  |  |
| 6 | `prIdStart` | `integer` | YES |  |  |  |
| 7 | `prDistanceStart` | `integer` | YES |  |  |  |
| 8 | `captureDate` | `timestamp without time zone` | NO |  |  |  |
| 9 | `filename` | `text` | YES |  |  |  |
| 10 | `url` | `text` | YES |  |  |  |
| 11 | `elapsedTime` | `integer` | NO |  |  |  |
| 12 | `sessionId` | `uuid` | YES |  |  |  |
| 13 | `index` | `integer` | NO |  |  |  |
| 14 | `created_at` | `timestamp without time zone` | NO |  |  |  |
| 15 | `updated_at` | `timestamp without time zone` | NO |  |  |  |
| 16 | `created_by_id` | `text` | YES |  |  |  |
| 17 | `updated_by_id` | `text` | YES |  |  |  |
| 18 | `road_cumul` | `double precision` | YES |  |  |  |
| 19 | `road_id` | `uuid` | YES |  |  |  |
| 20 | `id_tronc` | `bigint` | YES |  |  |  |
| 21 | `axe` | `text` | YES |  |  |  |
| 22 | `prj_quality` | `numeric` | YES |  |  |  |
| 23 | `cumuld` | `numeric` | YES |  |  |  |
| 24 | `geom_prj` | `geometry(Point,2154)` | YES |  |  |  |
| 25 | `ln_prj` | `geometry(LineString,2154)` | YES |  |  |  |
| 26 | `seg_ss` | `geometry(LineString,2154)` | YES |  |  |  |
| 27 | `seg_prj` | `geometry(LineString,2154)` | YES |  |  |  |
| 28 | `d_angle_seg` | `numeric` | YES |  |  |  |
| 29 | `Note_AFFAISSEMENT_SIGNIFICATIF` | `numeric` | YES |  |  |  |
| 30 | `Note_AFFAISSEMENT_GRAVE` | `numeric` | YES |  |  |  |
| 31 | `Note_ARRACHEMENT_SURFACE` | `numeric` | YES |  |  |  |
| 32 | `Note_ARRACHEMENT_PROFOND` | `numeric` | YES |  |  |  |
| 33 | `Note_AUTRE` | `numeric` | YES |  |  |  |
| 34 | `Note_JOINT_LONGITUDINAL` | `numeric` | YES |  |  |  |
| 35 | `Note_JOINT_TRANSVERSAL` | `numeric` | YES |  |  |  |
| 36 | `Note_NID_DE_POULE` | `numeric` | YES |  |  |  |
| 37 | `Note_ORNIERAGE_SIGNIFICATIF` | `numeric` | YES |  |  |  |
| 38 | `Note_ORNIERAGE_GRAVE` | `numeric` | YES |  |  |  |
| 39 | `Note_REGARD` | `numeric` | YES |  |  |  |
| 40 | `Note_TAMPON` | `numeric` | YES |  |  |  |
| 41 | `Note_FAIENCAGE_SIGNIFICATIF` | `numeric` | YES |  |  |  |
| 42 | `Note_FAIENCAGE_GRAVE` | `numeric` | YES |  |  |  |
| 43 | `Note_FAIENCAGE_BDR` | `numeric` | YES |  |  |  |
| 44 | `Note_FISSURE_LONGITUDINALE_SIGNIFICATIVE` | `numeric` | YES |  |  |  |
| 45 | `Note_FISSURE_LONGITUDINALE_GRAVE` | `numeric` | YES |  |  |  |
| 46 | `Note_FISSURE_LONGITUDINALE_BDR` | `numeric` | YES |  |  |  |
| 47 | `Note_FISSURE_LONGITUDINALE_PONTEE` | `numeric` | YES |  |  |  |
| 48 | `Note_FISSURE_TRANSVERSALE_SIGNIFICATIVE` | `numeric` | YES |  |  |  |
| 49 | `Note_FISSURE_TRANSVERSALE_GRAVE` | `numeric` | YES |  |  |  |
| 50 | `Note_FISSURE_TRANSVERSALE_PONTEE` | `numeric` | YES |  |  |  |
| 51 | `Note_GLACAGE_RESSUAGE_LOCALISE` | `numeric` | YES |  |  |  |
| 52 | `Note_GLACAGE_RESSUAGE_GENERALISE` | `numeric` | YES |  |  |  |
| 53 | `Note_REPARATION_PETITE_LARGEUR` | `numeric` | YES |  |  |  |
| 54 | `Note_REPARATION_PLEINE_LARGEUR` | `numeric` | YES |  |  |  |
| 55 | `Note_Structure` | `numeric` | YES |  |  |  |
| 56 | `Note_Surface` | `numeric` | YES |  |  |  |
| 57 | `geom_visible` | `geometry(Polygon,2154)` | YES |  |  |  |

**Indexes**

| Name | Unique | Primary | Definition |
|---|:---:|:---:|---|
| `image_pkey` | YES | YES | `CREATE UNIQUE INDEX image_pkey ON public.image USING btree (id)` |

### `public.road_data` <a id="tbl-public-road_data"></a>

**Description:** _(add via db_descriptions.yaml)_

- Row estimate: **69,781**  - Size: **140.8 MB**

**Columns**

| # | Column | Type | Nullable | Default | PK | Description |
|---:|---|---|:---:|---|:---:|---|
| 1 | `id` | `uuid` | NO |  | PK |  |
| 2 | `sessionName` | `text` | YES |  |  |  |
| 3 | `sessionId` | `uuid` | YES |  |  |  |
| 4 | `classe` | `text` | YES |  |  |  |
| 5 | `sous_classe` | `text` | YES |  |  |  |
| 6 | `cumuld` | `numeric` | YES |  |  |  |
| 7 | `cumulf` | `numeric` | YES |  |  |  |
| 8 | `image_id` | `uuid` | YES |  |  |  |
| 9 | `comment` | `text` | YES |  |  |  |
| 10 | `pixels_coords` | `text` | YES |  |  |  |
| 11 | `filename` | `text` | YES |  |  |  |
| 12 | `geom` | `geometry` | YES |  |  |  |
| 13 | `reliability` | `double precision` | YES |  |  |  |
| 14 | `measure_width` | `double precision` | YES |  |  |  |

**Indexes**

| Name | Unique | Primary | Definition |
|---|:---:|:---:|---|
| `road_data_pkey` | YES | YES | `CREATE UNIQUE INDEX road_data_pkey ON public.road_data USING btree (id)` |

### `public.session` <a id="tbl-public-session"></a>

**Description:** _(add via db_descriptions.yaml)_

- Row estimate: **14**  - Size: **896.0 KB**

**Columns**

| # | Column | Type | Nullable | Default | PK | Description |
|---:|---|---|:---:|---|:---:|---|
| 1 | `id` | `uuid` | NO |  | PK |  |
| 2 | `organizationId` | `uuid` | YES |  |  |  |
| 3 | `geom` | `geometry` | YES |  |  |  |
| 4 | `geomCalibration` | `geometry` | YES |  |  |  |
| 5 | `surfaceGrade` | `double precision` | YES |  |  |  |
| 6 | `structuralGrade` | `double precision` | YES |  |  |  |
| 7 | `calibrationId` | `uuid` | YES |  |  |  |
| 8 | `calibrationError` | `boolean` | YES |  |  |  |
| 9 | `calibrationErrorMailSent` | `boolean` | NO |  |  |  |
| 10 | `calibrationDone` | `boolean` | NO |  |  |  |
| 11 | `videoToImagesDone` | `boolean` | NO |  |  |  |
| 12 | `metadataId` | `uuid` | YES |  |  |  |
| 13 | `name` | `text` | NO |  |  |  |
| 14 | `created_at` | `timestamp without time zone` | NO |  |  |  |
| 15 | `updated_at` | `timestamp without time zone` | NO |  |  |  |
| 16 | `created_by_id` | `text` | YES |  |  |  |
| 17 | `updated_by_id` | `text` | YES |  |  |  |
| 18 | `state` | `text` | YES |  |  |  |
| 19 | `acquisition_date` | `timestamp without time zone` | YES |  |  |  |

**Indexes**

| Name | Unique | Primary | Definition |
|---|:---:|:---:|---|
| `session_pkey` | YES | YES | `CREATE UNIQUE INDEX session_pkey ON public.session USING btree (id)` |

## Schema `rendu` <a id="schema-rendu"></a>

_Schema does not exist in the database._

