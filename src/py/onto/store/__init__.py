"""Module: store — spec-08 store files: partition kinds, held slots, lifecycle policies and indexes."""

from __future__ import annotations

from .model import STORE_FORMAT, Store, StoreColumn, StoreExclusion, StoreIndex, StorePartition, StorePopulation, StoreSystem
from .parser import parseStore, storeFromJson
from .formatter import printStore, storeToJson
from .operations import Operator, formatStore, loadStore, validateStore

StoreOperator = Operator

__all__ = [
	"STORE_FORMAT", "Store", "StoreColumn", "StoreExclusion", "StoreIndex", "StorePartition", "StorePopulation", "StoreSystem",
	"Operator", "StoreOperator", "parseStore", "storeFromJson", "printStore", "storeToJson", "validateStore", "loadStore", "formatStore",
]

# EOF
