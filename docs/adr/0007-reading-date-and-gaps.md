# 7. Which date a reading belongs to, and gaps stay visible

Status: accepted (2026-11-07)

## Context

CDEC's CSV has two dates. `DATE TIME` is the day the reading is for. `OBS DATE` is usually the next day, but not always: for Oroville on 21 July 2026 both are `20260721`, while the 20 July row has `OBS DATE` 21 July. Keying on `OBS DATE` would put two Oroville readings on 21 July and none on 22 July.

Missing readings come as `---`, including the most recent day for stations that report late (Camanche's 6 November value was `---` on 7 November, and CDEC's own Reservoir Conditions report showed `---` for it the same day).

## Decision

* The reading date is `DATE TIME`. A test pins the Oroville case.
* `---` becomes `storage_af = NULL, is_missing = 1`. Nothing is interpolated or carried forward.
* `gold.reservoir_latest` shows each station's last real reading and `days_behind`, how many days it trails the newest date in the feed.
* `gold.statewide_daily.total_storage_af` is NULL on any day where a station has no reading; `partial_storage_af` shows the sum of the stations that did report. A total that silently drops a large reservoir would look like a real fall in storage.
* The 7-day change is NULL when the reading a week earlier is missing.

## Consequences

A chart of the statewide total will have holes on gap days. That is the honest picture; filling them is a choice for the reader of the data, not for the pipeline.
