from flask import Flask
from werkzeug.exceptions import TooManyRequests

from ml_service.app.error_handlers import register_error_handlers


def test_http_exception_preserves_status_code():
    app = Flask(__name__)
    app.config["TESTING"] = False
    register_error_handlers(app)

    @app.get("/limited")
    def limited():
        raise TooManyRequests("feedback rate limit exceeded")

    response = app.test_client().get("/limited")

    assert response.status_code == 429
    assert response.get_json()["type"] == "TooManyRequests"
