# Download water datasets after cloning

The Basin Plan, flood-reference and statewide USGS collections are distributed
as programs, tests, curated inputs and documentation. Their downloaded originals,
GeoJSON, databases, relationship tables, generated catalogs, generation pointers
and validation outputs are excluded from Git. Existing local downloads are
preserved. No Git LFS download is required for these collections.

Python 3.11 or later, an internet connection and several gigabytes of free disk
space are required. Additional immutable metadata generations consume more space.
Run the following commands from the repository root on Windows or Linux.
A virtual environment is recommended.

## Initial acquisition

Install the dependencies, then acquire the collections in dependency order:

```console
python -m pip install -r data/flood_impacts/requirements.txt -r data/usgs_water/requirements.txt
python data/basin_plans/refresh.py
python data/flood_impacts/refresh.py --mode static
python -m data.usgs_water.refresh --mode all
python -m data.usgs_water.refresh --mode link-review
python -m data.usgs_water.refresh --mode agency-review
python -m data.usgs_water.refresh --mode local-review
python -m data.usgs_water.refresh --mode routing --reuse-routing-sources
```

Basin Plan acquisition also builds regional review folders and separate CalWater
categories. The static flood pilot supplies reference geometry needed by the
statewide inventory; it does not limit USGS acquisition to the Russian River.
USGS `all` builds the first statewide routing generation. The subsequent review
passes inspect unresolved station addresses; the final routing rebuild applies
supported review decisions using previously downloaded geometry.

This sequence downloads USGS latest values only. The flood pilot's separate
observation/forecast acquisition is not required by this sequence. It is not
invoked by the static-only command above.

Anonymous USGS requests may be rate-limited. Stop when a command fails, inspect
its message and retained pending directory, and follow the
[USGS resume instructions](../data/usgs_water/README.md#refresh). Do not skip a
failed prerequisite or treat a pending generation as complete. An optional
`USGS_API_KEY` environment variable supports authenticated API access; never
commit the key. Agency access failures remain explicit in review catalogs.

The curated `data/usgs_water/local_review_rules.json` includes reviewed station
names, coordinates and exact metadata excerpts. Source or station changes may
withhold previously supported links. Counts can differ from historical reports.

## Verify and query local results

```console
python data/basin_plans/reference.py
python data/basin_plans/organize.py --verify
python -m data.usgs_water.validate_routing --output data/usgs_water/routing_verification.json
python -m data.usgs_water.validate_local_review --output data/usgs_water/local_review_verification.json
python -m data.usgs_water.report --station USGS-11464000
```

Generated catalogs become available at `data/basin_plans/REVIEW.md`,
`data/flood_impacts/REVIEW.md`, and the USGS inventory, network, routing and review
Markdown files. Links to generated files in collection documentation intentionally
refer to local outputs that do not exist in a fresh clone.

The optional native geodatabase inventory requires `pyogrio`:

```console
python -m pip install pyogrio
python data/basin_plans/native_inventory.py
```

## Later refreshes and retention

```console
python -m data.usgs_water.refresh --mode observations
python -m data.usgs_water.refresh --mode local-review
```

Observation refresh replaces the prior USGS snapshot after verification, retaining
only one latest value per time series. Static metadata and source evidence retain
versioned local generations. Review-only refresh does not acquire observations.
When refreshing inventory or upstream sources, rebuild dependent collections
before combining their records; manifests bind the relevant versions.

No scheduled download is installed. No downloaded dataset is automatically
committed. Derived downstream basin connections are review candidates, not
predicted flood extent, depth or arrival time.

See the [Basin Plan guide](../data/basin_plans/README.md),
[flood-reference methods](../data/flood_impacts/METHODS.md), and
[USGS current-data guide](../data/usgs_water/README.md) for source citations,
individual commands, interpretation and verification limits.
