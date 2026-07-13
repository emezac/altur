import json
import pytest
from app.core.config import settings
from app.services.llm.openai_llm import OpenAILLMProvider

@pytest.mark.slow
def test_contract_openai_llm():
    """
    Contract test for OpenAILLMProvider. Skipped by default unless running
    with slow markers and an OPENAI_API_KEY is supplied.
    """
    key = settings.OPENAI_API_KEY
    if not key or not key.strip() or key.startswith("change-me"):
        pytest.skip("OPENAI_API_KEY is not set. Skipping contract test.")
        
    provider = OpenAILLMProvider()
    
    system_prompt = (
        "You are an expert sales call analyzer. Parse the transcription and extract structured "
        "insights including executive summary, key points, sentiment, purchase intent, insights "
        "(buying signals, risks, inconsistencies, tone notes) and sales tags (outcome, next step, "
        "objections, compliance, product interest). Your response must be JSON only."
    )
    user_content = "Buenos días, soy Laura de Nube Ventas. ¿Hablo con Carlos? Sí, soy Carlos. Tengo unos minutos."
    
    try:
        response = provider.complete_json(system_prompt, user_content)
        assert response is not None
        
        data = json.loads(response)
        assert "summary" in data
        assert "tags" in data
        
        # Verify schema keys
        summary = data["summary"]
        tags = data["tags"]
        assert "executive_summary" in summary
        assert "sentiment" in summary
        assert "outcome" in tags
    except Exception as e:
        pytest.fail(f"Contract test failed with exception: {e}")
