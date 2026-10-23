"""Transformacion: de ``data/raw`` a ``data/processed``."""

from astroca.transform.affiliations import (
    AffiliationResolver,
    AffiliationTransformer,
    Resolution,
)
from astroca.transform.base import Transformer

__all__ = [
    "Transformer",
    "AffiliationResolver",
    "AffiliationTransformer",
    "Resolution",
]
