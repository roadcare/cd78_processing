# Matrice de décision — règles de calcul (`pas_100`)

Source : `D:\MyProject\71_CD7892\00_Data\travaux\pas_Antonin_rev01.xlsx`, onglets
**`pas_100`** et **`Matrice décision`** uniquement (l'onglet `pas_50` n'est pas
pris en compte).

Ce document décrit, pour chaque segment, comment calculer les 4 colonnes finales :
**`Priorité`**, **`Technique entretien`**, **`Coût_surfacique`**, **`Coût_Total`**.

Le calcul se fait en deux temps :

1. à partir des données brutes du segment, on dérive 4 *clés* de décision
   (état structure, état surface, type de chaussée, importance trafic) puis on
   construit un **code unique** ;
2. ce code unique sert de clé de recherche (`XLOOKUP`) dans la **matrice de
   décision** (80 combinaisons) qui renvoie `Priorité`, `Technique entretien` et
   `Coût_surfacique`. Le `Coût_Total` est ensuite calculé.

---

## 1. Données d'entrée (colonnes du segment)

| Colonne | Sens |
|---|---|
| `surface` | surface du pas en m² (`= (cumulf-cumuld) * avg_width`) |
| `avg_note_global` | note globale moyenne, échelle 0–1 |
| `avg_note_structure` | note de structure moyenne, échelle 0–1 |
| `avg_note_surface` | note de surface moyenne, échelle 0–1 |
| `nb_pl_final` | trafic poids-lourds (nombre de PL/jour) |
| `nature_cr_final` | nature de la couche de roulement (`BB`, `ECF`, `BBSG`, `ESU`, …) |

---

## 2. Étapes de dérivation

### 2.1 Notes 0–20

Les notes 0–1 sont ramenées sur une échelle 0–20 :

| Note | Formule | Excel |
|---|---|---|
| `Note_globale` | `tronquer(avg_note_global * 20)` (arrondi **inférieur**) | `=ROUNDDOWN(H*20,0)` |
| `Note_structure` | `arrondi(avg_note_structure * 20)` | `=ROUND(I*20,0)` |
| `Note_surface` | `arrondi(avg_note_surface * 20)` | `=ROUND(J*20,0)` |

> Attention : `Note_globale` utilise l'arrondi **inférieur** (`ROUNDDOWN`),
> alors que `Note_structure` et `Note_surface` utilisent l'arrondi **au plus
> proche** (`ROUND`).

### 2.2 État (3 classes A / B / C)

C'est cette classification (et non la version `_OLD` à 4 classes) qui alimente
la matrice. Appliquée à `Note_structure` → `Etat_structure`, à `Note_surface`
→ `Etat_surface` (idem `Etat_global` pour information) :

| Note (n) | État |
|---|---|
| `n <= 8` | `C-Mauvais` |
| `8 < n <= 16` | `B-Moyen` |
| `n >= 16` | `A-Bon` |

```
Etat = IF(n<=8,"C-Mauvais", IF(n>=16,"A-Bon", IF(AND(n>8,n<16),"B-Moyen")))
```

### 2.3 Classe de trafic PL → `classe_trafic_PL`

À partir de `nb_pl_final` (n) :

| `nb_pl_final` (n) | Classe |
|---|---|
| `n < 25` | `T5` |
| `25 <= n < 50` | `T4` |
| `50 <= n < 85` | `T3-` |
| `85 <= n < 150` | `T3+` |
| `150 <= n < 300` | `T2` |
| `300 <= n < 750` | `T1` |
| `n >= 750` | `T0` |

### 2.4 Importance trafic PL → `Importance_trafic_PL`

À partir de la classe de trafic :

| Classe de trafic | Importance |
|---|---|
| `T5`, `T4`, `T3-` | `Faible` |
| `T3+`, `T2` | `Moyen` |
| `T1`, `T0` | `Important` |

### 2.5 Type de chaussée → `Type_chaussée`

À partir de `nature_cr_final` :

| `nature_cr_final` | Type |
|---|---|
| `BB`, `BBM`, `BBTM`, `BBME`, `ECF` | `BB` |
| `BBSG`, `BBSG ET ECF`, `BBSG/BBME` | `LH` |
| `ESU`, `ES` | `Souple` |

### 2.6 Code unique → `code_unique_simple`

Concaténation des 4 clés (1ʳᵉ lettre de l'état structure, 1ʳᵉ lettre de l'état
surface, type de chaussée, importance trafic) :

```
code_unique_simple = LEFT(Etat_structure,1) & "-" & LEFT(Etat_surface,1)
                     & "-" & Type_chaussée & "-" & Importance_trafic_PL
```

Exemples : `A-A-BB-Faible`, `B-C-LH-Important`, `C-A-Souple-Moyen`.

---

## 3. Recherche dans la matrice de décision

`Priorité`, `Technique entretien` et `Coût_surfacique` sont obtenus par
recherche du `code_unique_simple` dans la matrice (`XLOOKUP` sur la colonne
`Code_unique`) :

```
Priorité          = XLOOKUP(code_unique_simple, Matrice.Code_unique, Matrice.Priorité)
Technique entretien = XLOOKUP(code_unique_simple, Matrice.Code_unique, Matrice.Technique_entretien)
Coût_surfacique   = XLOOKUP(code_unique_simple, Matrice.Code_unique, Matrice.Coût_surfacique)
```

- `Priorité` ∈ { `-` (rien à faire), `P1`, `P2`, `P3` } — P1 = la plus urgente.
- `Coût_surfacique` est un coût en €/m².

### Matrice complète (81 combinaisons)

`Code_unique` = `Etat_structure - Etat_surface - Type_chaussée - Importance_trafic_PL`

| Code_unique | Priorité | Technique entretien | Coût_surfacique (€/m²) |
|---|---|---|---|
| A-A-BB-Faible | - | RAS | 0 |
| A-A-BB-Important | - | RAS | 0 |
| A-A-BB-Moyen | - | RAS | 0 |
| A-A-LH-Faible | - | RAS | 0 |
| A-A-LH-Important | - | RAS | 0 |
| A-A-LH-Moyen | - | RAS | 0 |
| A-A-Souple-Faible | - | RAS | 0 |
| A-A-Souple-Important | - | RAS | 0 |
| A-A-Souple-Moyen | - | RAS | 0 |
| A-B-BB-Faible | P2 | ECF/ESU | 15 |
| A-B-BB-Important | P1 | BBM | 27 |
| A-B-BB-Moyen | P1 | ECF/ESU | 15 |
| A-B-LH-Faible | P2 | ECF/ESU | 15 |
| A-B-LH-Important | P1 | BBSG | 28 |
| A-B-LH-Moyen | P1 | BBSG | 28 |
| A-B-Souple-Faible | P2 | ECF/ESU | 15 |
| A-B-Souple-Important | P1 | ECF/ESU | 15 |
| A-B-Souple-Moyen | P1 | ECF/ESU | 15 |
| A-C-BB-Faible | P1 | ECF/ESU | 15 |
| A-C-BB-Important | P1 | BBM | 27 |
| A-C-BB-Moyen | P1 | ECF/ESU | 15 |
| A-C-LH-Faible | P1 | ECF/ESU | 15 |
| A-C-LH-Important | P1 | BBSG | 28 |
| A-C-LH-Moyen | P1 | BBSG | 28 |
| A-C-Souple-Faible | P1 | ECF/ESU | 15 |
| A-C-Souple-Important | P1 | ECF/ESU | 15 |
| A-C-Souple-Moyen | P1 | ECF/ESU | 15 |
| B-A-BB-Faible | P3 | BBM | 27 |
| B-A-BB-Important | P1 | BBM | 27 |
| B-A-BB-Moyen | P2 | BBM | 27 |
| B-A-LH-Faible | P3 | ECF/ESU | 15 |
| B-A-LH-Important | P1 | BBSG | 28 |
| B-A-LH-Moyen | P1 | Traitement de surface + BBSG | 43 |
| B-A-Souple-Faible | P3 | BBM | 27 |
| B-A-Souple-Important | P1 | BBM | 27 |
| B-A-Souple-Moyen | P2 | BBM | 27 |
| B-B-BB-Faible | P2 | BBM | 27 |
| B-B-BB-Important | P1 | BBM | 27 |
| B-B-BB-Moyen | P1 | BBM | 27 |
| B-B-LH-Faible | P2 | Traitement de surface + BBSG | 43 |
| B-B-LH-Important | P1 | GB+BBM | 75 |
| B-B-LH-Moyen | P1 | Traitement de surface + BBSG | 43 |
| B-B-Souple-Faible | P2 | BBM | 27 |
| B-B-Souple-Important | P1 | BBM | 27 |
| B-B-Souple-Moyen | P1 | BBM | 27 |
| B-C-BB-Faible | P2 | BBM | 27 |
| B-C-BB-Important | P1 | BBM | 27 |
| B-C-BB-Moyen | P2 | BBM | 27 |
| B-C-LH-Faible | P2 | Traitement de surface + BBSG | 43 |
| B-C-LH-Important | P1 | GB+BBM | 75 |
| B-C-LH-Moyen | P2 | Traitement de surface + BBSG | 43 |
| B-C-Souple-Faible | P2 | BBM | 27 |
| B-C-Souple-Important | P1 | BBM | 27 |
| B-C-Souple-Moyen | P2 | BBM | 27 |
| C-A-BB-Faible | P3 | BBM | 27 |
| C-A-BB-Important | P1 | GB+BBM | 75 |
| C-A-BB-Moyen | P2 | BBM | 27 |
| C-A-LH-Faible | P3 | Traitement de surface + BBSG | 43 |
| C-A-LH-Important | P1 | GB + BBM | 75 |
| C-A-LH-Moyen | P2 | GB+BBM | 75 |
| C-A-Souple-Faible | P3 | Traitement de surface + ECF/ESU | 30 |
| C-A-Souple-Important | P1 | Traitement de surface + BBM | 42 |
| C-A-Souple-Moyen | P2 | Traitement de surface + BBM | 42 |
| C-B-BB-Faible | P3 | BBM | 27 |
| C-B-BB-Important | P1 | GB+BBM | 75 |
| C-B-BB-Moyen | P2 | BBM | 27 |
| C-B-LH-Faible | P3 | Traitement de surface + BBSG | 43 |
| C-B-LH-Important | P1 | GB + BBM | 75 |
| C-B-LH-Moyen | P2 | GB+BBM | 75 |
| C-B-Souple-Faible | P3 | Traitement de surface + ECF/ESU | 30 |
| C-B-Souple-Important | P1 | Traitement de surface + BBM | 42 |
| C-B-Souple-Moyen | P3 | Traitement de surface + BBM | 42 |
| C-C-BB-Faible | P3 | BBM | 27 |
| C-C-BB-Important | P1 | GB+BBM | 75 |
| C-C-BB-Moyen | P2 | BBM | 27 |
| C-C-LH-Faible | P3 | Traitement de surface + BBSG | 43 |
| C-C-LH-Important | P1 | GB + BBM | 75 |
| C-C-LH-Moyen | P2 | GB+BBM | 75 |
| C-C-Souple-Faible | P3 | Traitement de surface + ECF/ESU | 30 |
| C-C-Souple-Important | P1 | Traitement de surface + BBM | 42 |
| C-C-Souple-Moyen | P3 | Traitement de surface + BBM | 42 |

> Toutes les combinaisons `A-A-*` (structure **et** surface bonnes) → aucune
> action (`Priorité = -`, `Technique entretien = RAS`, `Coût_surfacique = 0`).

---

## 4. Coût total → `Coût_Total`

```
Coût_Total = arrondi( Coût_surfacique * surface , au plus proche 100 )
```

Excel : `=ROUND(AC2*G2,-2)` — `Coût_surfacique` (€/m²) × `surface` (m²),
arrondi à la centaine d'euros la plus proche. (Référence de colonne `AC` depuis
le retrait de la colonne `geom` de l'onglet `pas_100` ; auparavant `AD`.)

Exemples vérifiés :

| code_unique | Coût_surfacique | surface (m²) | Coût_surf × surface | **Coût_Total** |
|---|---|---|---|---|
| A-B-BB-Faible | 15 | 638.2 | 9573.0 | **9600** |
| C-A-BB-Faible | 27 | 516.1 | 13934.7 | **13900** |
| A-B-LH-Moyen | 28 | 705.2 | 19745.6 | **19700** |
| B-B-LH-Faible | 43 | 463.1 | 19913.3 | **19900** |
| A-A-* | 0 | * | 0 | **0** |

---

## 5. Chaîne de calcul (résumé)

```
avg_note_structure ─ROUNDDOWN/ROUND─► Note_structure ─seuils 8/16─► Etat_structure (A/B/C) ┐
avg_note_surface   ─ROUND─────────► Note_surface   ─seuils 8/16─► Etat_surface   (A/B/C) ┤
nature_cr_final    ─table─────────────────────────────────────► Type_chaussée (BB/LH/Souple) ┤─► code_unique_simple
nb_pl_final ─table─► classe_trafic_PL ─table─► Importance_trafic_PL (Faible/Moyen/Important) ┘        │
                                                                                                      ▼
                                          Matrice décision (XLOOKUP) ─► Priorité, Technique entretien, Coût_surfacique
                                                                                                      │
                                                                       Coût_Total = ROUND(Coût_surfacique × surface, -2)
```

## Notes de mise en œuvre

- Le code unique de la matrice utilise l'état à **3 classes** (`A/B/C`), pas la
  version `_OLD` à 4 classes (`01-Bon … 04-Mauvais`) qui sert seulement
  d'affichage (`code_unique_OLD`).
- `Etat_global` (colonne `avg_note_global`) n'entre **pas** dans la matrice ;
  seuls `Etat_structure` et `Etat_surface` sont utilisés.
- Si `nature_cr_final` ou `nb_pl_final` ne correspond à aucune entrée des tables
  ci-dessus, la clé reste vide et la recherche dans la matrice échoue : prévoir
  une valeur par défaut côté implémentation.
