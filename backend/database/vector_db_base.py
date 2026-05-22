"""Vector DB base contract.

Documents the public surface that ``database.vector_db`` exposes today and
that any provider replacement (Pinecone, Qdrant, …) must continue to honor.
The functions below are *type stubs only*; the active implementation is
selected by ``providers.get_vector_db_provider()``.
"""

from datetime import datetime
from typing import List, Optional, Protocol, TypedDict


class VectorMatch(TypedDict, total=False):
    id: str
    score: float
    metadata: dict


# Namespace constants — preserved across providers so callers see the same
# namespacing semantics whether the backend talks to Pinecone or Qdrant.
NS_CONVERSATIONS = "ns1"
NS_MEMORIES = "ns2"
NS_SCREEN_ACTIVITY = "ns3"
NS_ACTION_ITEMS = "ns4"


class VectorDBContract(Protocol):
    # Conversation vectors (ns1)
    def upsert_vector(self, uid: str, conversation_id: str, vector: List[float]) -> None: ...
    def upsert_vector2(
        self, uid: str, conversation_id: str, vector: List[float], metadata: dict
    ) -> None: ...
    def update_vector_metadata(self, uid: str, conversation_id: str, metadata: dict) -> None: ...
    def upsert_vectors(
        self, uid: str, vectors: List[List[float]], conversation_ids: List[str]
    ) -> None: ...
    def query_vectors(
        self,
        query: str,
        uid: str,
        starts_at: Optional[int] = None,
        ends_at: Optional[int] = None,
        k: int = 5,
    ) -> List[str]: ...
    def query_vectors_by_metadata(
        self,
        uid: str,
        vector: List[float],
        dates_filter: List[datetime],
        people: List[str],
        topics: List[str],
        entities: List[str],
        dates: List[str],
        limit: int = 5,
    ) -> List[str]: ...
    def delete_vector(self, uid: str, conversation_id: str) -> None: ...

    # Memory vectors (ns2)
    def upsert_memory_vector(
        self, uid: str, memory_id: str, content: str, category: str
    ) -> Optional[List[float]]: ...
    def upsert_memory_vectors_batch(self, uid: str, items: List[dict]) -> int: ...
    def find_similar_memories(
        self, uid: str, content: str, threshold: float = 0.85, limit: int = 5
    ) -> List[dict]: ...
    def search_memories_by_vector(self, uid: str, query: str, limit: int = 10) -> List[str]: ...
    def delete_memory_vector(self, uid: str, memory_id: str) -> None: ...

    # Action item vectors (ns4)
    def upsert_action_item_vector(
        self, uid: str, action_item_id: str, description: str
    ) -> Optional[List[float]]: ...
    def upsert_action_item_vectors_batch(self, uid: str, items: List[dict]) -> int: ...
    def search_action_items_by_vector(
        self, uid: str, query: str, limit: int = 10, min_score: float = 0.3
    ) -> List[str]: ...
    def find_similar_action_items(
        self, uid: str, query: str, threshold: float = 0.6, limit: int = 10
    ) -> List[dict]: ...
    def delete_action_item_vector(self, uid: str, action_item_id: str) -> None: ...
    def delete_action_item_vectors_batch(self, uid: str, action_item_ids: List[str]) -> None: ...

    # Screen activity vectors (ns3)
    def upsert_screen_activity_vectors(self, uid: str, rows: List[dict]) -> int: ...
    def search_screen_activity_vectors(
        self,
        uid: str,
        query_vector: List[float],
        start_date: Optional[int] = None,
        end_date: Optional[int] = None,
        app_filter: Optional[str] = None,
        k: int = 10,
    ) -> List[dict]: ...
    def delete_screen_activity_vectors(self, uid: str, ids: List[int]) -> None: ...
