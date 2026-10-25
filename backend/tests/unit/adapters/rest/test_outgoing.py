"""The requests Lekto sends, in the OpenAPI document (`webhooks`)."""

from tests.unit.adapters.rest.support import Api


def test_the_contract_describes_every_request_lekto_sends(api: Api) -> None:
    schema = api.app.openapi()
    webhooks = schema["webhooks"]
    assert set(webhooks) == {
        "events",
        "rule.send",
        "rule.ask",
        "external.propose",
        "external.extract",
    }
    for name, item in webhooks.items():
        operation = item["post"]
        body = operation["requestBody"]["content"]["application/json"]["schema"]
        assert body["$ref"].startswith("#/components/schemas/"), name
        assert set(operation["responses"]) == {"2XX"}, name
        headers = {parameter["name"] for parameter in operation["parameters"]}
        assert {"webhook-id", "webhook-timestamp", "webhook-signature"} <= headers, name
        if name in ("rule.ask", "external.propose", "external.extract"):
            assert {"lekto-task-id", "lekto-callback", "lekto-task-token"} <= headers, name
    components = schema["components"]["schemas"]
    assert components["ProposeContext"]["properties"]["contract"]["const"] == "propose-ext-1"
    assert "webhook.test" in components["EventBody"]["properties"]["type"]["enum"]
