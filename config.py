import os

basedir = os.path.abspath(os.path.dirname(__file__))


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-me")
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL",
        "postgresql+psycopg://livebid:livebid@localhost:5432/livebid",
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False


class TestConfig(Config):
    """Tests truncate tables, so they must never point at the dev database."""

    TESTING = True
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "TEST_DATABASE_URL",
        "postgresql+psycopg://livebid:livebid@localhost:5432/livebid_test",
    )
