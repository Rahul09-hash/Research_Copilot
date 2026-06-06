from research_copilot.graph import extract_entities


def test_extract_entities_finds_capitalized_phrases():
    entities = extract_entities("Qdrant stores vectors while Research Copilot uses Ollama and NetworkX.")

    assert "Research Copilot" in entities
    assert "Qdrant" in entities
