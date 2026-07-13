def test_architecture_endpoint_returns_document(client):
    """The architecture endpoint returns the modular components and scaling strategy."""
    res = client.get("/api/v1/architecture")
    assert res.status_code == 200

    data = res.json()
    # Core sections are present
    for key in ("app", "summary", "constraints", "layers", "pipeline", "scaling"):
        assert key in data, f"missing '{key}'"

    # Layers are well-formed and cover the key modules
    layer_ids = {layer["id"] for layer in data["layers"]}
    assert {"api", "queue", "stt", "llm", "db"}.issubset(layer_ids)
    for layer in data["layers"]:
        assert layer["title"] and layer["tech"] and layer["responsibility"]
        assert isinstance(layer["best_practices"], list) and layer["best_practices"]

    # Scaling strategy answers the challenge's production questions
    scaling = data["scaling"]
    assert scaling["strategy"] and scaling["bottlenecks"] and scaling["pii"]
