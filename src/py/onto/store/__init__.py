"""Module: store — spec-08 store files: partition kinds, held slots, lifecycle policies and indexes, and their bundles."""

from __future__ import annotations

from .model import STORE_FORMAT, Store, StoreColumn, StoreExclusion, StoreIndex, StorePartition, StorePopulation, StoreSystem
from .parser import parseStore, storeFromJson
from .formatter import printStore, storeToJson
from .operations import Operator, formatStore, loadStore, validateStore
from .bundle import STORE_BUNDLE_FORMAT, storeBundle
from .origins import ORIGIN_SHARED, ORIGIN_STORE, holds, originOf

StoreOperator = Operator

__all__ = [
	"STORE_FORMAT", "STORE_BUNDLE_FORMAT", "ORIGIN_STORE", "ORIGIN_SHARED",
	"Store", "StoreColumn", "StoreExclusion", "StoreIndex", "StorePartition", "StorePopulation", "StoreSystem",
	"Operator", "StoreOperator", "parseStore", "storeFromJson", "printStore", "storeToJson", "validateStore", "loadStore", "formatStore",
	"storeBundle", "originOf", "holds",
]

# EOF
