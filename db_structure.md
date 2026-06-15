# Database structure — `cd78_v2026`

_Generated 2026-06-15 10:35:04 from `localhost:5433` (user `postgres`)._

- PostgreSQL: `PostgreSQL 17.6 on x86_64-windows, compiled by msvc-19.44.35213, 64-bit`
- Schemas inspected: `client`, `public`, `rendu`
- Edit `db_descriptions.yaml` to fill in descriptions. They are preserved on re-run.

## About this database

_Add a description of the database and its use case in_ `db_descriptions.yaml` _under the_ `_database:` _key. It will be preserved across re-runs._

## Overview

| Schema | Exists | Tables |
|---|:---:|---:|
| `client` | YES | 3 |
| `public` | YES | 0 |
| `rendu` | NO | 0 |

## Contents

- [`client`](#schema-client)
- [`public`](#schema-public)
- [`rendu`](#schema-rendu)

## Schema `client` <a id="schema-client"></a>

| Table | Rows (est.) | Size | Description |
|---|---:|---:|---|
| [`20250916_trafic`](#tbl-client-20250916_trafic) | 506 | 1.0 MB |  |
| [`20260227_couche_roulement`](#tbl-client-20260227_couche_roulement) | 2,299 | 1.6 MB |  |
| [`itineraires_v2`](#tbl-client-itineraires_v2) | -1 | 136.0 KB |  |

### `client.20250916_trafic` <a id="tbl-client-20250916_trafic"></a>

**Description:** _(add via db_descriptions.yaml)_

- Row estimate: **506**  - Size: **1.0 MB**

**Columns**

| # | Column | Type | Nullable | Default | PK | Description |
|---:|---|---|:---:|---|:---:|---|
| 1 | `id` | `integer` | NO | nextval('client.trafic_id_seq'::regclass) | PK |  |
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

**Indexes**

| Name | Unique | Primary | Definition |
|---|:---:|:---:|---|
| `trafic_pkey` | YES | YES | `CREATE UNIQUE INDEX trafic_pkey ON client."20250916_trafic" USING btree (id)` |

### `client.20260227_couche_roulement` <a id="tbl-client-20260227_couche_roulement"></a>

**Description:** _(add via db_descriptions.yaml)_

- Row estimate: **2,299**  - Size: **1.6 MB**

**Columns**

| # | Column | Type | Nullable | Default | PK | Description |
|---:|---|---|:---:|---|:---:|---|
| 1 | `id` | `integer` | NO | nextval('client."20260227_couche_roulement_id_seq"'::regclass) | PK |  |
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

**Indexes**

| Name | Unique | Primary | Definition |
|---|:---:|:---:|---|
| `20260227_couche_roulement_pkey` | YES | YES | `CREATE UNIQUE INDEX "20260227_couche_roulement_pkey" ON client."20260227_couche_roulement" USING btree (id)` |

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

## Schema `public` <a id="schema-public"></a>

_No tables._

## Schema `rendu` <a id="schema-rendu"></a>

_Schema does not exist in the database._

