# Operational evidence design

Scenario assumptions were defined in `scenarios.json` before records were generated. All views use the same preventive blood-panel pathway, stage semantics, ten-calendar-day promise policy, and cutoff-aware calculation engine. The datasets cover twelve weeks, with a reference cutoff of 12 October 2026 at 23:59:59.

| View | Cases | Mechanism |
| --- | ---: | --- |
| Normal Operations | 222 | Stable weekly arrivals, four laboratory processing slots, and varied scheduling, transport, review and publication durations. |
| Growing Demand | 244 | Intake rises from 10 to 38 cases weekly. Three laboratory slots stay fixed, with 16–30 hours service per accession, matching Normal Operations. A chronological FIFO scheduler produces the queue. |
| Operational Disruption | 222 | Normal intake and laboratory capacity. North Clinic courier collections stop on 3 October; specimens remain in transport at cutoff. The 14 October restart is a recorded estimate. |

Laboratory slots represent continuously occupied analyzer/batch capacity operating seven days weekly. Growing Demand has approximately 22-case weekly capacity: early intake fits, but later intake exceeds capacity. The final review corrected an excessively severe original capacity assumption while preserving every original request, location and deadline. Neither stage counts nor bottleneck conclusions are generator inputs.

Entered/completed events define continuous responsibility intervals: intake, scheduling/collection, transport/receipt, laboratory queue/analysis, review and publication/delivery. A laboratory `work_started` event permits queue/service distinction. Future simulated transitions were discarded when records were saved. Notes were timestamped at the recorded exception or queue threshold, with deliberately incomplete coverage.

Requests and original promised deadlines are in `cases.json`/`.csv`. Authoritative stage histories and notes are in `stage_events.json`/`.csv`. `snapshot.json` is a convenience materialization at the reference cutoff; historical views reconstruct state from raw events. Delayed is an overdue flag, separate from current stage and interruption status.

The fixed seed is 4101. `manifest.json` records current checksums, and the application reuses these saved files. Growing Demand events and derived results were regenerated once for the final calibration. Normal Operations and Operational Disruption checksums remain unchanged. Routine application reruns never regenerate data.

Only fictional operational identifiers, locations and notes are included. Specimen storage notes are synthetic documentation, not validation of clinical suitability or stability. No patient names, diagnoses or test results are present.
