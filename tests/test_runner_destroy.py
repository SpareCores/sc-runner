from sc_runner.runner import _refresh_failed_due_to_missing_resource


def test_refresh_failure_detects_missing_vultr_instance():
    exc = Exception(
        'refreshing urn:pulumi:vultr.atl.foo::runner::vultr:index/instance:Instance::foo: '
        'error getting instance (abc): {"error":"instance not found","status":404}'
    )
    assert _refresh_failed_due_to_missing_resource(exc)


def test_refresh_failure_does_not_mask_other_errors():
    exc = Exception("quota exceeded in region atl")
    assert not _refresh_failed_due_to_missing_resource(exc)
