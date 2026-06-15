from sc_runner.runner import (
    _custom_resource_urns,
    _missing_cloud_resource_failure,
    _pruned_stack_resources,
    _refresh_failed_due_to_missing_resource,
)


def test_refresh_failure_detects_missing_vultr_instance():
    exc = Exception(
        'refreshing urn:pulumi:vultr.atl.foo::runner::vultr:index/instance:Instance::foo: '
        'error getting instance (abc): {"error":"instance not found","status":404}'
    )
    assert _refresh_failed_due_to_missing_resource(exc)


def test_destroy_failure_detects_missing_vultr_instance():
    exc = Exception(
        'deleting urn:pulumi:vultr.ord.foo::runner::vultr:index/instance:Instance::foo: '
        'error destroying instance abc: {"error":"Invalid instance-id.","status":404}'
    )
    assert _missing_cloud_resource_failure(exc)


def test_missing_resource_failure_does_not_mask_other_errors():
    exc = Exception("quota exceeded in region atl")
    assert not _missing_cloud_resource_failure(exc)


def test_custom_resource_urns_skips_stack_resource():
    class FakeDeployment:
        deployment = {
            "resources": [
                {"urn": "urn:pulumi:stack::proj::pulumi:pulumi:Stack::stack", "type": "pulumi:pulumi:Stack"},
                {
                    "urn": "urn:pulumi:stack::proj::vultr:index/instance:Instance::foo",
                    "type": "vultr:index/instance:Instance",
                    "custom": True,
                },
            ]
        }

    class FakeStack:
        def export_stack(self):
            return FakeDeployment()

    assert _custom_resource_urns(FakeStack()) == [
        "urn:pulumi:stack::proj::vultr:index/instance:Instance::foo"
    ]


def test_pruned_stack_resources_keeps_only_stack():
    resources = [
        {"type": "pulumi:pulumi:Stack", "custom": True},
        {"type": "vultr:index/instance:Instance", "custom": True},
        {"type": "pulumi:providers:vultr", "custom": True},
    ]
    assert _pruned_stack_resources(resources) == [
        {"type": "pulumi:pulumi:Stack", "custom": True},
        {"type": "pulumi:providers:vultr", "custom": True},
    ]
