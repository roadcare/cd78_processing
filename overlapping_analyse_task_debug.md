find me and example of a paire overlapping (both geometry and accumulad distance) from client."20260227_couche_roulement" that t1 and t2 are overlapping and t1 is more recent than t2 and t1 is all inside (midle ) of t2

for example : t1 = id 2161, t2 = id 1440 (axe 078D0983)

  ┌────────────────────┬──────┬───────┬────────┬────────┬─────────────┐
  │                    │  id  │ annee │ cumuld │ cumulf │ geom length │
  ├────────────────────┼──────┼───────┼────────┼────────┼─────────────┤
  │ t1 (newer, inside) │ 2161 │ 2023  │ 46452  │ 48777  │ 2324.6 m    │
  ├────────────────────┼──────┼───────┼────────┼────────┼─────────────┤
  │ t2 (older, outer)  │ 1440 │ 2006  │ 46050  │ 51534  │ 5484.2 m    │
  └────────────────────┴──────┴───────┴────────┴────────┴─────────────┘

the ouput should containt 3 segments
- first segment: the begening the part of t2 wihch not overlapp with t1, (cumuld,cumulf) = (46050,46452)
- second (midle ) segment is the copie of t1 (newer), (cumuld,cumulf) = (46452,48777)
- third segment : the end of t2 which is not intersect with t1, (cumuld,cumulf) = (48777,51534)

but the actually out contain only 2 segments

there is another bug, is_overlapping = true, only when t1 and t2 not geometry overlapping but overlapping with accumulated