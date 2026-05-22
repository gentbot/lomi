"""Vector database dispatcher.

Routes all vector operations to either the Qdrant or Pinecone implementation
based on the VECTOR_DB_PROVIDER env var.  All existing callers import from
this module unchanged — the provider swap is invisible to them.

When VECTOR_DB_PROVIDER=qdrant (local mode), embeddings are sourced from
utils.embeddings.router which in turn respects EMBEDDINGS_PROVIDER, so both
the vector DB and the embeddings can be swapped independently.
"""

from providers import get_vector_db_provider

if get_vector_db_provider() == "qdrant":
    from database.vector_db_qdrant import (
        upsert_vector,
        upsert_vector2,
        update_vector_metadata,
        upsert_vectors,
        query_vectors,
        query_vectors_by_metadata,
        delete_vector,
        upsert_memory_vector,
        upsert_memory_vectors_batch,
        find_similar_memories,
        check_memory_duplicate,
        search_memories_by_vector,
        delete_memory_vector,
        upsert_screen_activity_vectors,
        search_screen_activity_vectors,
        delete_screen_activity_vectors,
        upsert_action_item_vector,
        upsert_action_item_vectors_batch,
        search_action_items_by_vector,
        find_similar_action_items,
        delete_action_item_vector,
        delete_action_item_vectors_batch,
    )
else:
    from database.vector_db_pinecone import (
        upsert_vector,
        upsert_vector2,
        update_vector_metadata,
        upsert_vectors,
        query_vectors,
        query_vectors_by_metadata,
        delete_vector,
        upsert_memory_vector,
        upsert_memory_vectors_batch,
        find_similar_memories,
        check_memory_duplicate,
        search_memories_by_vector,
        delete_memory_vector,
        upsert_screen_activity_vectors,
        search_screen_activity_vectors,
        delete_screen_activity_vectors,
        upsert_action_item_vector,
        upsert_action_item_vectors_batch,
        search_action_items_by_vector,
        find_similar_action_items,
        delete_action_item_vector,
        delete_action_item_vectors_batch,
    )
