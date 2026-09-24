# Frozen suite revisions

Create a new dated directory for each live sweep. Record whether upstream updates were checked, then save the read-only source check JSON, accepted command packets, exact model/tool/fixture hashes, hardware cohort, and final run plan before starting any server. If updates were not checked, mark remote freshness `not checked`. Never edit a frozen plan after a run begins; create another revision for changes.
