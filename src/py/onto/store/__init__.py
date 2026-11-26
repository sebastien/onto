"""Module: store — spec-08 store files: partition kinds, held slots, lifecycle policies and indexes."""

from __future__ import annotations

from .model import STORE_FORMAT, Store, StoreColumn, StoreExclusion, StoreIndex, StorePartition, StorePopulation, StoreSystem
from .parser import parseStore, storeFromJson
from .formatter import printStore, storeToJson

__all__ = [
	"STORE_FORMAT", "Store", "StoreColumn", "StoreExclusion", "StoreIndex", "StorePartition", "StorePopulation", "StoreSystem",
	"parseStore", "storeFromJson", "printStore", "storeToJson",
]

# EOF
