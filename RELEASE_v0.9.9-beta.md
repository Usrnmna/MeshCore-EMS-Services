# MeshCore EMS v0.9.9-beta

Source release preparation — November 9, 2026. Release builds and publication
are pending; older archives and verification records do not validate this version.

## Command additions and changes

Each platform registers 50 commands against 50 dedicated executable programs.
The [complete command reference](meshcore_mqtt_service/COMMAND_REFERENCE.md#command-index)
specifies accepted selectors and source qualifications.

- `!help` and `!data`: channel discovery, prerequisite availability, installed-generation
  integrity, observation freshness and existing source-cache status.
- `!statepark`, `!entrance`, `!camp`, `!parking`, `!facility`: installed park identities,
  recorded points, combined attribute filters and qualified cross-collection facilities.
- `!gauge`, `!gauges`: exact agency-qualified station readings and bounded inventory discovery.
- `!downstream`, `!tributaries`, `!wateruse`: reviewed directed relationships and recorded
  Basin Plan designations, with exact identities and explicit ambiguity.
- `!sat`, `!satfreq`, `!satpoint`, `!satpass`: satellite identity/frequency references and
  bounded predictions using eligible local orbital data and datum-qualified GIS terrain.
- `!where`, `!weather`, `!brief`: geographic containment, NWS forecasts and selected
  location briefings with per-source freshness and unavailable-data qualifications.
- Existing `!trail` supports recorded endpoint selection and AND-combined filters;
  `!waterway` supports source IDs/names, `!basin` recorded parents, `!fire` explicit
  incident fields, and `!slideinfo` exact station instrumentation/status/source metadata.

## Maintenance and isolation

The shared archive publisher retains the established water inventory, network,
routing and review generation contracts alongside static and observation generations.
Publication still requires isolated candidates, verified hashes and protected pointer
replacement. Detached candidates do not activate themselves. Installer fixtures include
the reference-isolation dependency and compare the GUI's command list with package configuration.

W10 modelling remains paused. There is no MeshCore `!floodref` or `!rivertrend` command.
Existing `!floodwarn`, `!floodstatus` and service-owned `!floodalarm` behavior is retained.
Restricted local elevation, datum-grid, hydrography, soil and land-cover references
remain reference-only and cannot satisfy model readiness or satellite precision inputs.
Additional-source investigations W19A/B/C/E/F/G/H are deferred.

## Upgrade and verification boundaries

Preserved channel assignments can leave added commands unassigned. Review the desired
channels, install the required independently managed collections, restart the service,
and check `!help` / `!data`. Missing dependencies remain explicit rather than enabling
automatic acquisition. Queries and standalone command programs do not create subscriptions.

Radio replies remain one message of at most 150 UTF-8 bytes including the sender tag.
Essential identity, units and qualifications take priority; a narrower selector or a
supported local structured query is required when the qualified answer cannot fit.

Host fixture checks do not establish native clean installation, reboot behavior,
live-provider validity, physical radio delivery or reception. See the
[current verification record](installers/VALIDATION.md#v099-beta-source-verification)
and [development checks](docs/DEVELOPMENT.md). No v0.9.9-beta release artifact is
claimed built, signed, published or deployed by these preparation notes.
