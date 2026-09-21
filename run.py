import os

from dotenv import load_dotenv

from app import create_app

load_dotenv()
app = create_app(os.environ.get("FLASK_CONFIG", "default"))

if __name__ == "__main__":
    from app.extensions import socketio

    # ponytail: threading async mode is fine for the single-process MVP; no
    # message queue means this must not be scaled horizontally. Upgrade path:
    # eventlet/gevent + Redis message queue.
    socketio.run(app, debug=True, allow_unsafe_werkzeug=True, port=5000, host='0.0.0.0')
