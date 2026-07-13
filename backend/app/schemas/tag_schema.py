from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field, field_validator

class TagCategory(str, Enum):
    OUTCOME = "outcome"
    SENTIMENT = "sentiment"
    INTENT_LEVEL = "intent_level"
    OBJECTION_TYPE = "objection_type"
    NEXT_STEP = "next_step"
    COMPLIANCE_FLAG = "compliance_flag"
    PRODUCT_INTEREST = "product_interest"

ALLOWED_VALUES = {
    TagCategory.OUTCOME: {
        "won_deal_closed",
        "follow_up_scheduled",
        "not_interested",
        "no_decision",
        "unresolved_objection"
    },
    TagCategory.SENTIMENT: {
        "positive",
        "neutral",
        "negative",
        "mixed"
    },
    TagCategory.INTENT_LEVEL: {
        "high",
        "medium",
        "low"
    },
    TagCategory.OBJECTION_TYPE: {
        "price_budget",
        "timing_schedule",
        "competitor_brand",
        "no_immediate_need",
        "no_purchasing_authority",
        "no_objections_raised"
    },
    TagCategory.NEXT_STEP: {
        "demo_scheduled",
        "send_proposal",
        "call_again_follow_up",
        "escalated_to_supervisor",
        "closed_lost"
    },
    TagCategory.COMPLIANCE_FLAG: {
        "possible_sensitive_data",
        "inappropriate_language",
        "none"
    }
}

class TagUpdateRequest(BaseModel):
    category: str
    value: str
    reason: Optional[str] = None

    @field_validator("category")
    @classmethod
    def validate_category(cls, v: str) -> str:
        try:
            TagCategory(v)
        except ValueError:
            raise ValueError(f"Invalid category '{v}'.")
        return v

    @field_validator("value")
    @classmethod
    def validate_value(cls, v: str, info) -> str:
        category = info.data.get("category")
        if not category:
            return v
        
        cat_enum = TagCategory(category)
        # product_interest is an open list
        if cat_enum == TagCategory.PRODUCT_INTEREST:
            return v
            
        allowed = ALLOWED_VALUES.get(cat_enum)
        if allowed and v not in allowed:
            raise ValueError(f"Invalid value '{v}' for category '{category}'.")
        return v
