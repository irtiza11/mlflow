# Sub-models for the MLflow Model Registry (fork of MLflow 2.17.2)

This fork adds **hierarchical grouping of registered models**: any registered model can have a
parent registered model, so related models can be organized under a "main" model in a tree of any
depth.

```
fraud-detection                (parent – can have its own versions, or just act as a container)
├── fraud-card
│   └── fraud-card-xgb
├── fraud-wire
└── fraud-ach
```

Base: tag `v2.17.2` → branch `sub-models`.

## Install from this fork

```bash
git clone https://github.com/irtiza11/mlflow.git
cd mlflow
pip install -e .                                 # Python package + server (Python 3.9–3.11)

# Build the web UI (Node 18+ and Yarn; needs ~8 GB RAM)
cd mlflow/server/js
yarn install --immutable
yarn build
cd ../../..

# Existing MLflow database? Add the new column once:
mlflow db upgrade <backend-store-uri>            # e.g. sqlite:///mlflow.db, postgresql://...

mlflow server --backend-store-uri <backend-store-uri>
```

New databases get the column automatically. File-based stores (`./mlruns`) need no migration.

## Python API

```python
from mlflow import MlflowClient

client = MlflowClient()
client.create_registered_model("fraud-detection")
client.create_registered_model("fraud-card", parent_name="fraud-detection")   # new kwarg
client.set_registered_model_parent("fraud-card", "fraud-detection")           # move
client.set_registered_model_parent("fraud-card", None)                        # detach
client.get_registered_model("fraud-card").parent_name                         # new property
client.get_sub_models("fraud-detection")                                      # direct children
client.get_sub_models("fraud-detection", recursive=True)                      # all descendants

client.search_registered_models("parent_name = 'fraud-detection'")            # children
client.search_registered_models("parent_name = ''")                           # top-level only
client.search_registered_models("parent_name != ''")                          # all sub-models
```

## REST API

| Change | Detail |
|---|---|
| `RegisteredModel.parent_name` (field 9) | Returned on every registered model response when set |
| `CreateRegisteredModel.parent_name` (field 4) | Optional on `POST /api/2.0/mlflow/registered-models/create` |
| **New** `SetRegisteredModelParent` | `POST /api/2.0/mlflow/registered-models/set-parent` `{"name": "...", "parent_name": "..."}`; omit/empty `parent_name` to detach |
| `SearchRegisteredModels` filter | New attribute `parent_name` (`=`, `!=`, `LIKE`, `ILIKE`; `''` means "no parent") |

All changes are additive, so old clients keep working against the new server. Requests from new
clients that use `parent_name` against an old server fail with "endpoint not found" / ignored field.

## Integrity rules

* Parent must exist (`RESOURCE_DOES_NOT_EXIST`).
* No cycles, including self-parenting (`INVALID_PARAMETER_VALUE`).
* Renaming a parent re-points its sub-models automatically.
* Deleting a model that still has sub-models is refused (`RESOURCE_CONFLICT`, HTTP 409).
* Names stay globally unique; `models:/<name>/<version>` and alias URIs are unchanged.

## UI

* Model page: new **Model hierarchy** section (parent link, *Change parent* dialog, sub-model
  links) and the parent appears in the breadcrumbs.
* Registered models list: new **Parent model** column.

## Storage & migration

* SQL: nullable, indexed `registered_models.parent_name VARCHAR(256)` – Alembic revision
  `b8f3e1a2c4d5` (down-revision `f5a4f2784254`). Run `mlflow db upgrade <db-uri>` on existing
  databases; downgrade drops the column.
  Integrity is enforced in the store rather than with a self-referencing foreign key because
  MySQL and MSSQL do not support `ON UPDATE CASCADE` on self-referencing keys.
* File store: `parent_name` is stored in each model's `meta.yaml`; older files without the key are
  read as top-level models.
* Store capability flag `AbstractStore.supports_model_hierarchy` – `True` for SQL, file and REST
  stores; `False` for Databricks workspace and Unity Catalog stores, which raise a clean
  `NOT_IMPLEMENTED` error if hierarchy APIs are used.

## Auth

`SetRegisteredModelParent` requires *edit* permission on the model being moved (same as rename).

## Files changed

* Protos: `mlflow/protos/model_registry.proto` (+ regenerated `model_registry_pb2.py`, Java)
* Entity: `mlflow/entities/model_registry/registered_model.py`
* Stores: `mlflow/store/model_registry/{abstract_store,sqlalchemy_store,file_store,rest_store,databricks_workspace_model_registry_rest_store}.py`, `dbmodels/models.py`
* Migration: `mlflow/store/db_migrations/versions/b8f3e1a2c4d5_add_parent_name_to_registered_models.py`
* Search: `mlflow/utils/search_utils.py`
* Server: `mlflow/server/handlers.py`, `mlflow/server/auth/__init__.py`
* Client: `mlflow/tracking/client.py`, `mlflow/tracking/_model_registry/client.py`
* UI: `ModelHierarchySection.tsx` (new), `ModelView.tsx`, `ModelListTable.tsx`, `services.ts`, `types.ts`, `lang/default/en.json`
* Tests: `tests/store/model_registry/test_model_hierarchy.py` (new, 43 tests across SQL / file / live REST server), `ModelHierarchySection.test.tsx` (new), schema snapshots, updated entity tests
* Docs: `docs/source/model-registry.rst`

## Known limitations

* Cycle and delete checks are application-level; two perfectly concurrent conflicting writes on
  the SQL store could in theory slip past them. Reads tolerate this (cycle walks are bounded).
* `get_sub_models(recursive=True)` issues one search per tree level node; fine for typical trees,
  not optimized for thousands of nodes.
* The `mlflow.register_model()` fluent API does not take `parent_name`; create the parent link
  with `MlflowClient` (once is enough – later versions stay under the same registered model).
