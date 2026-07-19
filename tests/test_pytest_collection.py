def test_tests_package_is_importable() -> None:
    from tests.inmemory_repo import InMemoryRepository

    assert InMemoryRepository is not None
