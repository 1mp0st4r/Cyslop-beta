from fastapi import Header, HTTPException, status
from models import EntityNode

# 1. Dependency to extract and verify the user's role from headers
def get_current_user_role(x_user_role: str = Header(default="analyst")) -> str:
    valid_roles = ["lead_investigator", "analyst"]
    role = x_user_role.lower()
    if role not in valid_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid clearance role."
        )
    return role

# 2. Data masking function for Personally Identifiable Information (PII)
def mask_entity_pii(entity: EntityNode, role: str) -> EntityNode:
    
    if role == "lead_investigator":
        return entity

    # Analysts receive masked PII
    masked_phones = []
    for phone in entity.phone_numbers:
        if len(phone) >= 6:
            masked = phone[:4] + "******" + phone[-2:]
        else:
            masked = "**********"
        masked_phones.append(masked)

    masked_entity = entity.model_copy()
    masked_entity.phone_numbers = masked_phones
    return masked_entity