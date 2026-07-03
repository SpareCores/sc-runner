import base64

from sc_runner.resources.multi_vm import (
    MultiVmStackSpec,
    VmSpec,
    build_user_data_b64,
    render_user_data,
    render_user_data_from_replacements,
)


def test_render_user_data_substitutes_placeholders():
    rendered = render_user_data(
        "role={ROLE} peer={CLIENT_PRIVATE_IP}",
        {"ROLE": "server", "CLIENT_PRIVATE_IP": "10.0.0.2"},
    )
    assert rendered == "role=server peer=10.0.0.2"


def test_render_user_data_from_replacements_uses_template_key():
    rendered = render_user_data_from_replacements(
        {
            "USER_DATA_TEMPLATE": "host={HOST}",
            "HOST": "db.local",
        }
    )
    assert rendered == "host=db.local"


def test_build_user_data_b64_static():
    vm = VmSpec(
        role="client",
        instance="t3.small",
        user_data_template="#!/bin/bash\necho {MSG}",
        user_data_static={"MSG": "hello"},
    )
    b64 = build_user_data_b64(vm)
    assert base64.b64decode(b64).decode() == "#!/bin/bash\necho hello"


def test_two_vm_factory_sets_bindings():
    spec = MultiVmStackSpec.two_vm(
        primary_instance="db-sku",
        client_instance="client-sku",
        primary_disk_gib=128,
        client_user_data_b64="Y2xpZW50",
        primary_user_data_template="#!/bin/bash\npeer={CLIENT_PRIVATE_IP}",
    )
    assert spec.db_instance == "db-sku"
    assert spec.client_instance == "client-sku"
    primary = spec.vm("db")
    assert primary.user_data_bindings == {"CLIENT_PRIVATE_IP": ("client", "private_ip")}
