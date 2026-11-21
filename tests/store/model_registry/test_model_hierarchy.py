"""
Tests for registered model hierarchies (sub-models grouped under a parent registered model).

Each behavior is exercised against the SQLAlchemy store, the file store, and a live tracking
server (REST store), so all three stay consistent.
"""

from unittest import mock

import pytest

from mlflow import MlflowClient
from mlflow.entities.model_registry import RegisteredModel
from mlflow.exceptions import MlflowException
from mlflow.protos.databricks_pb2 import (
    INVALID_PARAMETER_VALUE,
    NOT_IMPLEMENTED,
    RESOURCE_CONFLICT,
    RESOURCE_DOES_NOT_EXIST,
    ErrorCode,
)
from mlflow.store.model_registry.abstract_store import AbstractStore

from tests.tracking.integration_test_utils import _init_server


@pytest.fixture(scope="module")
def _server(tmp_path_factory):
    root = tmp_path_factory.mktemp("server")
    backend_uri = "sqlite:///" + str(root / "server.db")
    with _init_server(backend_uri, root_artifact_uri=(root / "artifacts").as_uri()) as url:
        yield url


@pytest.fixture(params=["sqlalchemy", "file", "rest"])
def client(request, tmp_path, tmp_sqlite_uri):
    if request.param == "sqlalchemy":
        return MlflowClient(tracking_uri=tmp_sqlite_uri, registry_uri=tmp_sqlite_uri)
    if request.param == "file":
        uri = tmp_path.joinpath("mlruns").as_uri()
        return MlflowClient(tracking_uri=uri, registry_uri=uri)
    # The REST server is shared across tests; namespace model names to keep tests independent.
    return _NamespacedClient(request.getfixturevalue("_server"), request.node.name)


class _NamespacedClient:
    """Wraps MlflowClient so model names are unique per test on a shared server."""

    def __init__(self, url, test_name):
        self._c = MlflowClient(tracking_uri=url, registry_uri=url)
        self._p = "".join(ch if ch.isalnum() else "_" for ch in test_name) + "__"

    def _n(self, name):
        return None if name is None else (self._p + name if name else name)

    def _strip(self, rm):
        rm.name = rm.name[len(self._p) :]
        if rm.parent_name:
            rm.parent_name = rm.parent_name[len(self._p) :]
        return rm

    def create_registered_model(self, name, tags=None, description=None, parent_name=None):
        return self._strip(
            self._c.create_registered_model(self._n(name), tags, description, self._n(parent_name))
        )

    def set_registered_model_parent(self, name, parent_name):
        return self._strip(self._c.set_registered_model_parent(self._n(name), self._n(parent_name)))

    def get_registered_model(self, name):
        return self._strip(self._c.get_registered_model(self._n(name)))

    def get_sub_models(self, name, recursive=False):
        return [self._strip(m) for m in self._c.get_sub_models(self._n(name), recursive)]

    def rename_registered_model(self, name, new_name):
        return self._c.rename_registered_model(self._n(name), self._n(new_name))

    def delete_registered_model(self, name):
        return self._c.delete_registered_model(self._n(name))

    def search_registered_models(self, filter_string):
        # Restrict to this test's models, then apply the hierarchy filter.
        filter_string = filter_string.replace("parent_name = '", f"parent_name = '{self._p}")
        filter_string = filter_string.replace(f"parent_name = '{self._p}'", "parent_name = ''")
        f = f"name LIKE '{self._p}%' AND {filter_string}"
        return [self._strip(m) for m in self._c.search_registered_models(f)]


def _names(models):
    return [m.name for m in models]


def _assert_error(code, fn, *args, match=None):
    with pytest.raises(MlflowException, match=match) as e:
        fn(*args)
    assert e.value.error_code == ErrorCode.Name(code)


def test_create_with_parent_and_get(client):
    client.create_registered_model("root")
    child = client.create_registered_model("child", description="d", parent_name="root")
    assert child.parent_name == "root"
    assert client.get_registered_model("child").parent_name == "root"
    assert client.get_registered_model("root").parent_name is None


def test_create_with_missing_parent_fails(client):
    _assert_error(
        RESOURCE_DOES_NOT_EXIST, client.create_registered_model, "orphan", None, None, "nope"
    )
    _assert_error(RESOURCE_DOES_NOT_EXIST, client.get_registered_model, "orphan")


def test_create_with_self_as_parent_fails(client):
    _assert_error(INVALID_PARAMETER_VALUE, client.create_registered_model, "me", None, None, "me")


def test_get_sub_models_direct_and_recursive(client):
    client.create_registered_model("a")
    client.create_registered_model("b2", parent_name="a")
    client.create_registered_model("b1", parent_name="a")
    client.create_registered_model("c1", parent_name="b1")
    client.create_registered_model("d1", parent_name="c1")
    client.create_registered_model("unrelated")

    assert _names(client.get_sub_models("a")) == ["b1", "b2"]
    assert _names(client.get_sub_models("a", recursive=True)) == ["b1", "b2", "c1", "d1"]
    assert client.get_sub_models("d1") == []
    _assert_error(RESOURCE_DOES_NOT_EXIST, client.get_sub_models, "missing")


def test_set_parent_move_and_detach(client):
    client.create_registered_model("p1")
    client.create_registered_model("p2")
    client.create_registered_model("m")

    assert client.set_registered_model_parent("m", "p1").parent_name == "p1"
    assert _names(client.get_sub_models("p1")) == ["m"]

    client.set_registered_model_parent("m", "p2")
    assert client.get_sub_models("p1") == []
    assert _names(client.get_sub_models("p2")) == ["m"]

    assert client.set_registered_model_parent("m", None).parent_name is None
    assert client.get_registered_model("m").parent_name is None
    client.set_registered_model_parent("m", "p1")
    assert client.set_registered_model_parent("m", "").parent_name is None


def test_set_parent_rejects_cycles(client):
    client.create_registered_model("x")
    client.create_registered_model("y", parent_name="x")
    client.create_registered_model("z", parent_name="y")
    _assert_error(
        INVALID_PARAMETER_VALUE, client.set_registered_model_parent, "x", "x", match="cycle"
    )
    _assert_error(
        INVALID_PARAMETER_VALUE, client.set_registered_model_parent, "x", "z", match="cycle"
    )
    _assert_error(
        INVALID_PARAMETER_VALUE, client.set_registered_model_parent, "y", "z", match="cycle"
    )
    # hierarchy unchanged after rejected updates
    assert client.get_registered_model("x").parent_name is None
    assert client.get_registered_model("y").parent_name == "x"


def test_set_parent_missing_models(client):
    client.create_registered_model("exists")
    _assert_error(RESOURCE_DOES_NOT_EXIST, client.set_registered_model_parent, "exists", "nope")
    _assert_error(RESOURCE_DOES_NOT_EXIST, client.set_registered_model_parent, "nope", "exists")


def test_delete_parent_with_children_is_blocked(client):
    client.create_registered_model("parent")
    client.create_registered_model("kid", parent_name="parent")
    _assert_error(RESOURCE_CONFLICT, client.delete_registered_model, "parent", match="sub-models")
    assert client.get_registered_model("parent").name == "parent"

    client.delete_registered_model("kid")
    client.delete_registered_model("parent")
    _assert_error(RESOURCE_DOES_NOT_EXIST, client.get_registered_model, "parent")


def test_rename_parent_repoints_children(client):
    client.create_registered_model("old")
    client.create_registered_model("k1", parent_name="old")
    client.create_registered_model("k2", parent_name="old")
    client.rename_registered_model("old", "new")
    assert client.get_registered_model("k1").parent_name == "new"
    assert client.get_registered_model("k2").parent_name == "new"
    assert _names(client.get_sub_models("new")) == ["k1", "k2"]


def test_rename_child_keeps_parent(client):
    client.create_registered_model("dad")
    client.create_registered_model("before", parent_name="dad")
    client.rename_registered_model("before", "after")
    assert client.get_registered_model("after").parent_name == "dad"
    assert _names(client.get_sub_models("dad")) == ["after"]


def test_search_by_parent_name(client):
    client.create_registered_model("top1")
    client.create_registered_model("top2")
    client.create_registered_model("sub1", parent_name="top1")
    client.create_registered_model("sub2", parent_name="top1")
    client.create_registered_model("sub3", parent_name="top2")

    assert sorted(_names(client.search_registered_models("parent_name = 'top1'"))) == [
        "sub1",
        "sub2",
    ]
    assert sorted(_names(client.search_registered_models("parent_name = ''"))) == ["top1", "top2"]
    assert sorted(_names(client.search_registered_models("parent_name != ''"))) == [
        "sub1",
        "sub2",
        "sub3",
    ]


def test_parent_name_with_quote_character(client):
    client.create_registered_model("o'brien")
    client.create_registered_model("kid-of-quote", parent_name="o'brien")
    assert _names(client.get_sub_models("o'brien")) == ["kid-of-quote"]


# ---------------------------------------------------------------------------------------------
# Entity / proto and compatibility tests (store-independent)
# ---------------------------------------------------------------------------------------------


def test_registered_model_proto_round_trip():
    rm = RegisteredModel("child", 1, 2, "desc", [], parent_name="root")
    proto = rm.to_proto()
    assert proto.parent_name == "root"
    assert RegisteredModel.from_proto(proto).parent_name == "root"

    top = RegisteredModel("top")
    assert not top.to_proto().HasField("parent_name")
    assert RegisteredModel.from_proto(top.to_proto()).parent_name is None
    assert "parent_name" in dict(top)


def test_empty_parent_name_normalized_to_none():
    assert RegisteredModel("m", parent_name="").parent_name is None


def test_unsupported_store_raises_clean_error(tmp_sqlite_uri):
    client = MlflowClient(tracking_uri=tmp_sqlite_uri, registry_uri=tmp_sqlite_uri)
    registry_client = client._get_registry_client()

    class _LegacyStore:
        supports_model_hierarchy = False

        def create_registered_model(self, name, tags=None, description=None):
            return RegisteredModel(name)

    with mock.patch.object(
        type(registry_client), "store", new_callable=mock.PropertyMock, return_value=_LegacyStore()
    ):
        # Creating without a parent still works on stores without hierarchy support.
        assert client.create_registered_model("plain").name == "plain"
        _assert_error(NOT_IMPLEMENTED, client.create_registered_model, "x", None, None, "plain")
        _assert_error(NOT_IMPLEMENTED, client.set_registered_model_parent, "x", "plain")
        _assert_error(NOT_IMPLEMENTED, client.get_sub_models, "plain")


def test_abstract_store_default_set_parent_not_implemented():
    class _Store(AbstractStore):
        pass

    _assert_error(NOT_IMPLEMENTED, _Store().set_registered_model_parent, "a", "b")


def test_set_parent_requires_update_permission_in_auth_app():
    from mlflow.protos.model_registry_pb2 import SetRegisteredModelParent
    from mlflow.server import auth

    assert (
        auth.BEFORE_REQUEST_HANDLERS[SetRegisteredModelParent]
        is auth.validate_can_update_registered_model
    )


def test_migration_round_trip_preserves_data(tmp_sqlite_uri):
    import sqlalchemy as sa
    from alembic.command import downgrade, upgrade

    from mlflow.store.db.utils import _get_alembic_config
    from mlflow.store.model_registry.sqlalchemy_store import SqlAlchemyStore

    store = SqlAlchemyStore(tmp_sqlite_uri)
    store.create_registered_model("keep-me", description="survives")
    store._dispose_engine()

    config = _get_alembic_config(tmp_sqlite_uri)
    downgrade(config, "-1")
    engine = sa.create_engine(tmp_sqlite_uri)
    assert "parent_name" not in {
        c["name"] for c in sa.inspect(engine).get_columns("registered_models")
    }
    upgrade(config, "heads")
    engine.dispose()
    engine = sa.create_engine(tmp_sqlite_uri)
    assert "parent_name" in {c["name"] for c in sa.inspect(engine).get_columns("registered_models")}
    engine.dispose()

    store = SqlAlchemyStore(tmp_sqlite_uri)
    rm = store.get_registered_model("keep-me")
    assert rm.description == "survives"
    assert rm.parent_name is None


def test_hierarchy_support_flags():
    from mlflow.store._unity_catalog.registry.rest_store import UcModelRegistryStore
    from mlflow.store.model_registry.databricks_workspace_model_registry_rest_store import (
        DatabricksWorkspaceModelRegistryRestStore,
    )
    from mlflow.store.model_registry.file_store import FileStore
    from mlflow.store.model_registry.rest_store import RestStore
    from mlflow.store.model_registry.sqlalchemy_store import SqlAlchemyStore

    assert SqlAlchemyStore.supports_model_hierarchy
    assert FileStore.supports_model_hierarchy
    assert RestStore.supports_model_hierarchy
    assert not DatabricksWorkspaceModelRegistryRestStore.supports_model_hierarchy
    assert not UcModelRegistryStore.supports_model_hierarchy
