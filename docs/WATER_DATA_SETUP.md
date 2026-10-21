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

## Connect downloaded water data to radio commands

After the final successful routing refresh, build the spatial index for each
platform package that will run the service:

```console
python meshcore_mqtt_service/scripts/water_refresh.py --index
python meshcore_mqtt_service_windows/scripts/water_refresh.py --index
```

Index schema 2 also retains station identities without coordinates for supported
upstream links. Rerun these commands when upgrading from the earlier index.
Rebuild after inventory/routing dependencies change. Observation-only refreshes
are read directly and need no index rebuild. `responder.water.data_directory`
defaults to `../data` relative to the package; configure an absolute data root
for standalone service installations. No download schedule is installed. The
service's source cache refreshes on demand during lookups/subscription checks.
Original datasets remain unchanged and excluded from publication.

[Water commands, current-only retention, interpretation and NOAA citations](../meshcore_mqtt_service/WATER_GUIDE.md).

The [NOAA station relationship review](../meshcore_mqtt_service/WATER_STATION_REVIEW.md)
supplements 33 investigated upstream identities without changing the original
USGS identifier table. Refresh the overlay independently in each installed package:

```console
python meshcore_mqtt_service/scripts/water_refresh.py --noaa-identifiers
python meshcore_mqtt_service_windows/scripts/water_refresh.py --noaa-identifiers
```

The current runtime review replaces earlier review outcomes, including failures
and unresolved matches. No index rebuild or observation download is required.
The packaged static evidence table is small; large original datasets remain local.

The identifier refresh also verifies the 17-station agency review, including a
pinned report and current CDEC/HADS metadata for CDM/YDMC1. USGS series-catalog
requests retain coverage dates only. Agency-source failures are saved explicitly
and return exit code 1; no failed review can reuse a previously accepted successor.
The programs add no observation-history downloads or automatic schedules.

The [NOAA map and operator-record audit](../meshcore_mqtt_service/WATER_STATION_REVIEW.md#further-map-and-operator-record-review)
retains static evidence for sixteen unresolved stations. Identifier refresh also
checks current map/candidate metadata; source failures and changed candidate
identities require review. These auxiliary records cannot authorize a link,
change routing or add historical readings. Existing exact and agency-successor
validation remains in effect.

The [source-access retry](../meshcore_mqtt_service/WATER_STATION_REVIEW.md#archived-source-and-onerain-access-retry)
recovered the USGS PDFs and OneRain inventory. Identifier refresh now checks the
public OneRain sites endpoint using transient cookies. Only static metadata is
retained; PDF evidence remains dated manual-review context, and no additional
station link or reading history is created.


The [additional local agency findings](../meshcore_mqtt_service/WATER_STATION_REVIEW.md#additional-local-operating-agency-records)
are preserved under `map_record_review.operator_record_review` during identifier
refresh. Their fixed manual-review dates are separate from current retrieval
times. They add no accepted links, observation downloads or index rebuilds.


WAC/WAS [vertical-reference uncertainty](../meshcore_mqtt_service/WATER_STATION_REVIEW.md#wacwas-elevation-and-logger-offset-review)
is retained in the two Warm Springs review rows as static metadata. The raw
logger offset is evidence only; no datum transformation or reading correction
is authorized. Identifier refresh preserves this manual assessment without
requesting historical observations.

Identifier refresh also runs [automatic WAC/WAS metadata checks](../meshcore_mqtt_service/WATER_STATION_REVIEW.md#automatic-wacwas-metadata-checks)
against five official CW3E/CDEC pages. The latest structured source statuses and
changed fields replace the preceding check, including access failures. Review
flags produce exit code 1 after saving; unchanged known uncertainty does not.
Manual evidence dates remain fixed, and no offset or datum conversion is applied.
