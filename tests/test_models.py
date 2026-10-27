import pytest
from sqlalchemy.exc import IntegrityError

from app import db
from app.models import ClassRoom, User


def test_invalid_role_is_rejected(app):
    with app.app_context():
        class_room = ClassRoom(name="Test Class")
        db.session.add(class_room)
        db.session.commit()

        user = User(
            username="bad-role",
            role="admin",
            class_id=class_room.id,
            password_hash="hash",
        )
        db.session.add(user)
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_missing_class_is_rejected(app):
    with app.app_context():
        user = User(
            username="no-class",
            role="teacher",
            class_id=None,
            password_hash="hash",
        )
        db.session.add(user)
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()
