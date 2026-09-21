import os

from dotenv import load_dotenv
from flask import Flask

from app.extensions import db, migrate, socketio

load_dotenv()


def create_app(config_name="default"):
    app = Flask(__name__)

    from config import Config

    app.config.from_object(Config)
    if os.environ.get("TESTING") == "1":
        app.config.update(TESTING=True)

    db.init_app(app)
    migrate.init_app(app, db)
    socketio.init_app(app)

    from app.routes import bp as routes_bp

    app.register_blueprint(routes_bp)

    from app import sockets  # noqa: F401  (registers socket handlers)
    from app import closer  # noqa: F401  (deadline watcher)

    closer.start_deadline_watcher(app)

    return app
