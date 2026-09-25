# The artifact's value domain and serialisation are closed and pinned

The compiled artifact must load, under a plain YAML 1.1 loader, to values equal in type to what Reverie resolved. PyYAML/YAML 1.1 is named as the target dialect, and the value domain is closed to string, integer, float, boolean, null, list, map, plus the `!vault` and `!secret` tags — exactly JSON's types plus two tags. Timestamps, binary, sets, ordered maps, NaN, and infinity are load errors rather than silently accepted. Anchors, aliases, and `<<` merge keys are forbidden outright: a merge key would be a third, shallow, parse-time merge bypassing the declared per-key policy layer entirely, and reuse is the hierarchy's job, not YAML's.

File mechanics are pinned rather than left to a formatter's defaults: UTF-8 with no BOM, LF, block style, no line wrapping, two-space indent, a `---` document marker, and a timestamp-free generated header — because a committed, diffed artifact makes every free formatting parameter into diff churn.

## Consequences

Every map is sorted at every depth by Unicode code point (list order is preserved as data, never sorted, since after a merge there is no source order left to keep). This is a genuine constraint on the implementation and on any future serialisation library choice: swapping the YAML dialect or loader is not a casual change, since it can silently break the load-time type-equality guarantee this decision exists to hold.
