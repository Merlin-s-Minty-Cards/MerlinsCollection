from merlins_collection.models.auth import AuthenticatedUser


def test_authenticated_user_defaults():
    user = AuthenticatedUser(sub="user-123")
    assert user.sub == "user-123"
    assert user.username is None
    assert user.email is None
    assert user.groups == []
    assert user.is_admin is False


def test_authenticated_user_full():
    user = AuthenticatedUser(
        sub="user-123",
        username="merlin",
        email="merlin@example.com",
        groups=["admin", "staff"],
        is_admin=True,
    )
    assert user.username == "merlin"
    assert user.email == "merlin@example.com"
    assert user.groups == ["admin", "staff"]
    assert user.is_admin is True
