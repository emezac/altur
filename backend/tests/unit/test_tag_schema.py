import pytest
from pydantic import ValidationError
from app.schemas.tag_schema import TagUpdateRequest, TagCategory

def test_tag_update_request_valid():
    # Valid outcome
    req = TagUpdateRequest(category="outcome", value="won_deal_closed")
    assert req.category == "outcome"
    assert req.value == "won_deal_closed"
    
    # Valid sentiment
    req = TagUpdateRequest(category="sentiment", value="mixed")
    assert req.category == "sentiment"
    assert req.value == "mixed"

def test_tag_update_request_invalid_category():
    with pytest.raises(ValidationError) as exc_info:
        TagUpdateRequest(category="invalid_category_xyz", value="some_val")
    assert "Invalid category" in str(exc_info.value)

def test_tag_update_request_invalid_value():
    with pytest.raises(ValidationError) as exc_info:
        TagUpdateRequest(category="sentiment", value="super_happy")
    assert "Invalid value" in str(exc_info.value)
    assert "sentiment" in str(exc_info.value)

def test_tag_update_request_product_interest_open_list():
    # product_interest category does not enforce a set of closed allowed values
    req = TagUpdateRequest(category="product_interest", value="Arbitrary Plan Name 123")
    assert req.category == "product_interest"
    assert req.value == "Arbitrary Plan Name 123"
