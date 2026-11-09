"""Keep explicit reference collections out of operational dataset consumers.

The reserved directory survives missing catalog metadata. This is application
policy, not an OS sandbox against an operator copying and relabelling files.
"""
from pathlib import Path

DIRECTORY = '.reference-only'
CATALOG = 'reference-catalog.json'
KINDS = {'restricted_reference', 'restricted_reference_catalog', 'wbd_boundary',
         'usgs_elevation_reference', 'geoid18_reference', 'ssurgo_reference', 'nhdplus_reference',
         'nlcd_land_cover', 'nlcd_fractional_impervious', 'nlcd_land_cover_confidence'}
DATASETS = {'wbd_reference', 'nlcd_land_cover_reference', 'nlcd_impervious_reference',
            'usgs_elevation_b01_reference',
            'usgs_elevation_b03_reference', 'usgs_elevation_b04_reference',
            'geoid18_reference', 'ssurgo_reference', 'nhdplus_reference',
            'nlcd_land_cover_confidence_reference'}


class ReferenceUseError(ValueError):
    """A restricted reference cannot satisfy an operational source request."""


def reject_path(path):
    """Reject lexical and resolved reference paths, including external aliases."""
    for candidate in (Path(path).absolute(), Path(path).resolve()):
        if DIRECTORY in {part.casefold() for part in candidate.parts}:
            raise ReferenceUseError('reference_only_source_forbidden')
        for parent in (candidate, *candidate.parents):
            marker = parent / CATALOG
            if marker.exists() or marker.is_symlink():
                raise ReferenceUseError('reference_only_source_forbidden')
    return Path(path)


def reject_metadata(document):
    """Deny reference declarations; unsupported purpose policies never grant use."""
    if not isinstance(document, dict):
        raise ValueError('invalid_source_policy')
    if any(document.get(key) is not None and not isinstance(document[key], str)
           for key in ('kind', 'dataset')):
        raise ValueError('invalid_source_policy')
    if (document.get('kind') in KINDS or document.get('dataset') in DATASETS
            or any(key in document for key in ('allowed_uses', 'allowed_use', 'prohibited_uses',
                                               'purpose_policy', 'reference_only', 'permitted_use'))
            or document.get('model_eligible') is False):
        raise ReferenceUseError('reference_only_source_forbidden')
