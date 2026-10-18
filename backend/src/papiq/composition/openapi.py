"""`python -m papiq.composition.openapi [FILE]`: write the API's OpenAPI document as JSON to FILE
(default: standard output), without configuration and without a server.

The web UI generates its TypeScript client from it (`web/openapi.json`); a unit test fails while
that file differs from the document of the code.
"""

import json
import sys
from pathlib import Path

from papiq.adapters.inbound.rest import create_app
from papiq.composition.api import api_context
from papiq.composition.container import build_memory_container, build_services
from papiq.composition.settings import Settings


def openapi_document() -> dict[str, object]:
    """The OpenAPI document of the REST API. It does not depend on the configuration: the app is
    built on in-memory adapters only to read its routes."""
    container = build_memory_container()
    settings = Settings.model_construct()
    app = create_app(api_context(container, settings, build_services(container, settings)))
    return app.openapi()


def render(document: dict[str, object]) -> str:
    """The document as the checked-in file holds it."""
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def main(argv: list[str]) -> int:
    if len(argv) > 1:
        print("usage: python -m papiq.composition.openapi [FILE]", file=sys.stderr)
        return 2
    text = render(openapi_document())
    if argv:
        Path(argv[0]).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
