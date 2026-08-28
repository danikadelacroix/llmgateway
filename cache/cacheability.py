# cache/cacheability.py
import re
from enum import Enum
from dataclasses import dataclass
from typing import List, Dict

class QueryClass(str, Enum):
    # Bypass classes
    EPHEMERAL = "EPHEMERAL"
    PERSONALIZED = "PERSONALIZED"
    NON_DETERMINISTIC = "NON_DETERMINISTIC"
    
    # Cacheable classes
    STABLE_SHORT = "STABLE_SHORT"
    STABLE_LONG = "STABLE_LONG"
    STABLE_PERMANENT = "STABLE_PERMANENT"

    @property
    def is_cacheable(self) -> bool:
        return self in (
            QueryClass.STABLE_SHORT, 
            QueryClass.STABLE_LONG, 
            QueryClass.STABLE_PERMANENT
        )

@dataclass
class CachePolicy:
    class_ttls: Dict[QueryClass, int]
    
    def ttl_for(self, query_class: QueryClass) -> int:
        return self.class_ttls.get(query_class, 86400)

DEFAULT_POLICY = CachePolicy(
    class_ttls={
        QueryClass.EPHEMERAL: 0,
        QueryClass.PERSONALIZED: 0,
        QueryClass.NON_DETERMINISTIC: 0,
        QueryClass.STABLE_SHORT: 6 * 3600,       # 6 hours
        QueryClass.STABLE_LONG: 24 * 3600,       # 24 hours
        QueryClass.STABLE_PERMANENT: 7 * 86400,  # 7 days
    }
)

# Ordered most specific to least specific
_PATTERNS = [
    # EPHEMERAL
    (re.compile(r'\b(today|tomorrow|yesterday|now|current time|weather|news|latest)\b'), QueryClass.EPHEMERAL),
    
    # PERSONALIZED
    (re.compile(r'\b(my order|remind me|my account|my name|what did i say)\b'), QueryClass.PERSONALIZED),
    
    # NON_DETERMINISTIC
    (re.compile(r'\b(random|roll a dice|surprise me|flip a coin)\b'), QueryClass.NON_DETERMINISTIC),
    
    # STABLE_PERMANENT
    (re.compile(r'\b(math|equation|sort algorithm|binary search|what is \d+[\+\-\*\/]\d+)\b'), QueryClass.STABLE_PERMANENT),
    
    # STABLE_SHORT
    (re.compile(r'\b(capital of|population of|current ceo|stock price)\b'), QueryClass.STABLE_SHORT),
]

def classify(messages: List[Dict]) -> QueryClass:
    """
    Classifies a list of messages into a QueryClass using regex patterns.
    Evaluates the concatenated text of all user messages.
    """
    text = " ".join(
        m.get("content", "") for m in messages if m.get("role", "").lower() == "user"
    ).lower()
    
    for pattern, qclass in _PATTERNS:
        if pattern.search(text):
            return qclass
            
    # Default fallback
    return QueryClass.STABLE_LONG
