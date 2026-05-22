# ── LOCAL ONLY — this entire file has no upstream equivalent ──
"""Qdrant-backed vector storage.

Mirrors the public functions of ``database.vector_db`` (Pinecone today) so the
router can swap implementations without touching call sites.

Design:
- One Qdrant collection per logical namespace (``ns1`` … ``ns4``). This avoids
  the per-vector ``namespace`` field Pinecone uses.
- Point IDs are deterministic UUID5 hashes derived from the
  ``"{uid}-{logical_id}"`` strings the rest of the backend already constructs;
  Qdrant requires ints or UUIDs, not arbitrary strings, so this preserves
  idempotent upserts without changing call sites.
- Embeddings come from ``utils.embeddings.router`` so the dimension follows
  the configured local model.
- Failures degrade to log + return empty/None, matching the Pinecone module's
  fail-open behavior.
"""

import logging
import os
import uuid
from datetime import datetime, timezone
from typing import List, Optional

logger = logging.getLogger(__name__)

QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")
QDRANT_API_KEY = os.environ.get("QDRANT_API_KEY") or None

NS_CONVERSATIONS = "ns1"
NS_MEMORIES = "ns2"
NS_SCREEN_ACTIVITY = "ns3"
NS_ACTION_ITEMS = "ns4"

_NAMESPACE_UUID = uuid.UUID("c0ffee00-0000-4000-8000-000000000001")

_client = None
_initialized_collections: set[str] = set()


def _get_client():
    global _client
    if _client is not None:
        return _client
    try:
        from qdrant_client import QdrantClient
    except ImportError as exc:
        raise RuntimeError(
            "qdrant-client is not installed. Add 'qdrant-client' to requirements.txt "
            "to use VECTOR_DB_PROVIDER=qdrant."
        ) from exc
    _client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)
    return _client


def _embedder():
    from utils.embeddings.router import get_embeddings_object

    return get_embeddings_object()


def _embed_query(text: str) -> List[float]:
    return _embedder().embed_query(text)


def _embed_documents(texts: List[str]) -> List[List[float]]:
    return _embedder().embed_documents(texts)


def _ensure_collection(name: str) -> None:
    if name in _initialized_collections:
        return
    from qdrant_client.http import models as qm

    from utils.embeddings.router import dimension

    client = _get_client()
    existing = {c.name for c in client.get_collections().collections}
    if name not in existing:
        client.create_collection(
            collection_name=name,
            vectors_config=qm.VectorParams(size=dimension(), distance=qm.Distance.COSINE),
        )
        logger.info("Created Qdrant collection %s (dim=%d)", name, dimension())
    _initialized_collections.add(name)


def _point_id(raw_id: str) -> str:
    return str(uuid.uuid5(_NAMESPACE_UUID, raw_id))


def _upsert_point(namespace: str, raw_id: str, vector: List[float], metadata: dict) -> None:
    from qdrant_client.http import models as qm

    _ensure_collection(namespace)
    client = _get_client()
    client.upsert(
        collection_name=namespace,
        points=[
            qm.PointStruct(
                id=_point_id(raw_id),
                vector=vector,
                payload={**metadata, "_raw_id": raw_id},
            )
        ],
    )


def _upsert_points(namespace: str, items: List[dict]) -> int:
    """``items`` rows = ``{"raw_id": str, "vector": [..], "metadata": {..}}``."""
    if not items:
        return 0
    from qdrant_client.http import models as qm

    _ensure_collection(namespace)
    client = _get_client()
    points = [
        qm.PointStruct(
            id=_point_id(it["raw_id"]),
            vector=it["vector"],
            payload={**it["metadata"], "_raw_id": it["raw_id"]},
        )
        for it in items
    ]
    client.upsert(collection_name=namespace, points=points)
    return len(points)


def _filter_for_uid(uid: str, extra: Optional[dict] = None):
    from qdrant_client.http import models as qm

    must = [qm.FieldCondition(key="uid", match=qm.MatchValue(value=uid))]
    if extra:
        for key, value in extra.items():
            if isinstance(value, dict) and ("gte" in value or "lte" in value):
                rng = qm.Range(gte=value.get("gte"), lte=value.get("lte"))
                must.append(qm.FieldCondition(key=key, range=rng))
            elif isinstance(value, list):
                must.append(qm.FieldCondition(key=key, match=qm.MatchAny(any=value)))
            else:
                must.append(qm.FieldCondition(key=key, match=qm.MatchValue(value=value)))
    return qm.Filter(must=must)


def _search(
    namespace: str,
    query_vector: List[float],
    *,
    query_filter=None,
    limit: int = 10,
):
    """Compatibility shim for qdrant-client ≥1.10 where ``.search`` was
    superseded by ``.query_points``. Returns a list of objects exposing
    ``.payload`` / ``.score`` regardless of the installed client version."""
    client = _get_client()
    if hasattr(client, "query_points"):
        result = client.query_points(
            collection_name=namespace,
            query=query_vector,
            query_filter=query_filter,
            limit=limit,
            with_payload=True,
        )
        return getattr(result, "points", result)
    return client.search(
        collection_name=namespace,
        query_vector=query_vector,
        query_filter=query_filter,
        limit=limit,
        with_payload=True,
    )


def _delete_by_raw_id(namespace: str, raw_ids: List[str]) -> None:
    if not raw_ids:
        return
    from qdrant_client.http import models as qm

    _ensure_collection(namespace)
    client = _get_client()
    client.delete(
        collection_name=namespace,
        points_selector=qm.PointIdsList(points=[_point_id(r) for r in raw_ids]),
    )


# ---------------------------------------------------------------------------
# Conversation vectors (ns1)
# ---------------------------------------------------------------------------


def upsert_vector(uid: str, conversation_id: str, vector: List[float]) -> None:
    metadata = {
        "uid": uid,
        "memory_id": conversation_id,
        "created_at": int(datetime.now(timezone.utc).timestamp()),
    }
    _upsert_point(NS_CONVERSATIONS, f"{uid}-{conversation_id}", vector, metadata)


def upsert_conversation_text_vector(uid: str, conversation_id: str, text: str) -> Optional[List[float]]:
    """Embed ``text`` and upsert into the conversations namespace (ns1)."""
    vector = _embed_query(text)
    metadata = {
        "uid": uid,
        "memory_id": conversation_id,
        "created_at": int(datetime.now(timezone.utc).timestamp()),
    }
    _upsert_point(NS_CONVERSATIONS, f"{uid}-{conversation_id}", vector, metadata)
    return vector


def upsert_vector2(uid: str, conversation_id: str, vector: List[float], metadata: dict) -> None:
    payload = {
        "uid": uid,
        "memory_id": conversation_id,
        "created_at": int(datetime.now(timezone.utc).timestamp()),
        **metadata,
    }
    _upsert_point(NS_CONVERSATIONS, f"{uid}-{conversation_id}", vector, payload)


def update_vector_metadata(uid: str, conversation_id: str, metadata: dict) -> None:
    from qdrant_client.http import models as qm

    _ensure_collection(NS_CONVERSATIONS)
    client = _get_client()
    payload = {**metadata, "uid": uid, "memory_id": conversation_id}
    client.set_payload(
        collection_name=NS_CONVERSATIONS,
        payload=payload,
        points=[_point_id(f"{uid}-{conversation_id}")],
    )


def upsert_vectors(uid: str, vectors: List[List[float]], conversation_ids: List[str]) -> None:
    now_ts = int(datetime.now(timezone.utc).timestamp())
    items = [
        {
            "raw_id": f"{uid}-{cid}",
            "vector": v,
            "metadata": {"uid": uid, "memory_id": cid, "created_at": now_ts},
        }
        for cid, v in zip(conversation_ids, vectors)
    ]
    _upsert_points(NS_CONVERSATIONS, items)


def query_vectors(
    query: str,
    uid: str,
    starts_at: Optional[int] = None,
    ends_at: Optional[int] = None,
    k: int = 5,
) -> List[str]:
    _ensure_collection(NS_CONVERSATIONS)
    extra = None
    if starts_at is not None and ends_at is not None:
        extra = {"created_at": {"gte": starts_at, "lte": ends_at}}
    vector = _embed_query(query)
    res = _search(
        NS_CONVERSATIONS,
        vector,
        query_filter=_filter_for_uid(uid, extra),
        limit=k,
    )
    return [(p.payload or {}).get("memory_id", "") for p in res if (p.payload or {}).get("memory_id")]


def query_vectors_by_metadata(
    uid: str,
    vector: List[float],
    dates_filter: List[datetime],
    people: List[str],
    topics: List[str],
    entities: List[str],
    dates: List[str],
    limit: int = 5,
) -> List[str]:
    """Approximation of the Pinecone variant — uses Qdrant's filter language
    and applies the people/topics/entities boost in Python."""
    from collections import defaultdict
    from qdrant_client.http import models as qm

    _ensure_collection(NS_CONVERSATIONS)
    must = [qm.FieldCondition(key="uid", match=qm.MatchValue(value=uid))]
    if dates_filter and len(dates_filter) == 2 and dates_filter[0] and dates_filter[1]:
        must.append(
            qm.FieldCondition(
                key="created_at",
                range=qm.Range(
                    gte=int(dates_filter[0].timestamp()),
                    lte=int(dates_filter[1].timestamp()),
                ),
            )
        )
    should = []
    for key, values in (("people_mentioned", people), ("topics", topics), ("entities", entities)):
        if values:
            should.append(qm.FieldCondition(key=key, match=qm.MatchAny(any=values)))
    flt = qm.Filter(must=must, should=should or None)

    res = _search(NS_CONVERSATIONS, vector, query_filter=flt, limit=1000)
    if not res and should:
        flt = qm.Filter(must=must)
        res = _search(NS_CONVERSATIONS, vector, query_filter=flt, limit=20)

    score_map: defaultdict[str, int] = defaultdict(int)
    ids: List[str] = []
    for p in res:
        payload = p.payload or {}
        cid = payload.get("memory_id")
        if not cid:
            continue
        ids.append(cid)
        for topic in topics:
            if topic in payload.get("topics", []):
                score_map[cid] += 1
        for entity in entities:
            if entity in payload.get("entities", []):
                score_map[cid] += 1
        for person in people:
            if person in payload.get("people_mentioned", []):
                score_map[cid] += 1
    ids.sort(key=lambda x: score_map[x], reverse=True)
    return ids[:limit]


def delete_vector(uid: str, conversation_id: str) -> None:
    _delete_by_raw_id(NS_CONVERSATIONS, [f"{uid}-{conversation_id}"])


# ---------------------------------------------------------------------------
# Memory vectors (ns2)
# ---------------------------------------------------------------------------


def upsert_memory_vector(
    uid: str, memory_id: str, content: str, category: str
) -> Optional[List[float]]:
    vector = _embed_query(content)
    metadata = {
        "uid": uid,
        "memory_id": memory_id,
        "category": category,
        "created_at": int(datetime.now(timezone.utc).timestamp()),
    }
    _upsert_point(NS_MEMORIES, f"{uid}-{memory_id}", vector, metadata)
    return vector


def upsert_memory_vectors_batch(uid: str, items: List[dict]) -> int:
    if not items:
        return 0
    contents = [it["content"] for it in items]
    vectors = _embed_documents(contents)
    now_ts = int(datetime.now(timezone.utc).timestamp())
    payload = [
        {
            "raw_id": f"{uid}-{it['memory_id']}",
            "vector": vectors[i],
            "metadata": {
                "uid": uid,
                "memory_id": it["memory_id"],
                "category": it["category"],
                "created_at": now_ts,
            },
        }
        for i, it in enumerate(items)
    ]
    return _upsert_points(NS_MEMORIES, payload)


def find_similar_memories(
    uid: str, content: str, threshold: float = 0.85, limit: int = 5
) -> List[dict]:
    _ensure_collection(NS_MEMORIES)
    vector = _embed_query(content)
    res = _search(NS_MEMORIES, vector, query_filter=_filter_for_uid(uid), limit=limit)
    return [
        {
            "memory_id": (p.payload or {}).get("memory_id"),
            "category": (p.payload or {}).get("category"),
            "score": p.score,
        }
        for p in res
        if p.score >= threshold and (p.payload or {}).get("memory_id")
    ]


def search_memories_by_vector(uid: str, query: str, limit: int = 10) -> List[str]:
    _ensure_collection(NS_MEMORIES)
    vector = _embed_query(query)
    res = _search(NS_MEMORIES, vector, query_filter=_filter_for_uid(uid), limit=limit)
    return [(p.payload or {}).get("memory_id") for p in res if (p.payload or {}).get("memory_id")]


def check_memory_duplicate(uid: str, content: str, threshold: float = 0.85) -> Optional[dict]:
    similar = find_similar_memories(uid, content, threshold=threshold, limit=1)
    return similar[0] if similar else None


def delete_memory_vector(uid: str, memory_id: str) -> None:
    _delete_by_raw_id(NS_MEMORIES, [f"{uid}-{memory_id}"])


# ---------------------------------------------------------------------------
# Action item vectors (ns4)
# ---------------------------------------------------------------------------


def upsert_action_item_vector(
    uid: str, action_item_id: str, description: str
) -> Optional[List[float]]:
    vector = _embed_query(description)
    metadata = {
        "uid": uid,
        "action_item_id": action_item_id,
        "created_at": int(datetime.now(timezone.utc).timestamp()),
    }
    _upsert_point(NS_ACTION_ITEMS, f"{uid}-ai-{action_item_id}", vector, metadata)
    return vector


def upsert_action_item_vectors_batch(uid: str, items: List[dict]) -> int:
    if not items:
        return 0
    descriptions = [it["description"] for it in items]
    vectors = _embed_documents(descriptions)
    now_ts = int(datetime.now(timezone.utc).timestamp())
    payload = [
        {
            "raw_id": f"{uid}-ai-{it['action_item_id']}",
            "vector": vectors[i],
            "metadata": {
                "uid": uid,
                "action_item_id": it["action_item_id"],
                "created_at": now_ts,
            },
        }
        for i, it in enumerate(items)
    ]
    return _upsert_points(NS_ACTION_ITEMS, payload)


def search_action_items_by_vector(
    uid: str, query: str, limit: int = 10, min_score: float = 0.3
) -> List[str]:
    _ensure_collection(NS_ACTION_ITEMS)
    vector = _embed_query(query)
    res = _search(NS_ACTION_ITEMS, vector, query_filter=_filter_for_uid(uid), limit=limit)
    return [
        (p.payload or {}).get("action_item_id")
        for p in res
        if p.score >= min_score and (p.payload or {}).get("action_item_id")
    ]


def find_similar_action_items(
    uid: str, query: str, threshold: float = 0.6, limit: int = 10
) -> List[dict]:
    _ensure_collection(NS_ACTION_ITEMS)
    try:
        vector = _embed_query(query)
        res = _search(NS_ACTION_ITEMS, vector, query_filter=_filter_for_uid(uid), limit=limit)
    except Exception as exc:
        logger.exception("find_similar_action_items qdrant failed uid=%s: %s", uid, exc)
        return []
    kept = []
    for p in res:
        aid = (p.payload or {}).get("action_item_id")
        if aid and p.score >= threshold:
            kept.append({"action_item_id": aid, "score": p.score})
    return kept


def delete_action_item_vector(uid: str, action_item_id: str) -> None:
    _delete_by_raw_id(NS_ACTION_ITEMS, [f"{uid}-ai-{action_item_id}"])


def delete_action_item_vectors_batch(uid: str, action_item_ids: List[str]) -> None:
    if not action_item_ids:
        return
    _delete_by_raw_id(NS_ACTION_ITEMS, [f"{uid}-ai-{aid}" for aid in action_item_ids])


# ---------------------------------------------------------------------------
# Screen activity vectors (ns3)
# ---------------------------------------------------------------------------


def upsert_screen_activity_vectors(uid: str, rows: List[dict]) -> int:
    items = []
    for row in rows:
        embedding = row.get("embedding")
        if not embedding:
            continue
        ts = row["timestamp"]
        if isinstance(ts, str):
            ts = int(datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp())
        else:
            ts = int(ts)
        items.append(
            {
                "raw_id": f'{uid}-sa-{row["id"]}',
                "vector": embedding,
                "metadata": {
                    "uid": uid,
                    "screenshot_id": str(row["id"]),
                    "timestamp": ts,
                    "appName": row.get("appName", ""),
                },
            }
        )
    return _upsert_points(NS_SCREEN_ACTIVITY, items)


def search_screen_activity_vectors(
    uid: str,
    query_vector: List[float],
    start_date: Optional[int] = None,
    end_date: Optional[int] = None,
    app_filter: Optional[str] = None,
    k: int = 10,
) -> List[dict]:
    _ensure_collection(NS_SCREEN_ACTIVITY)
    extra: dict = {}
    if start_date is not None or end_date is not None:
        extra["timestamp"] = {"gte": start_date, "lte": end_date}
    if app_filter:
        extra["appName"] = app_filter
    res = _search(
        NS_SCREEN_ACTIVITY,
        query_vector,
        query_filter=_filter_for_uid(uid, extra or None),
        limit=k,
    )
    return [
        {
            "screenshot_id": (p.payload or {}).get("screenshot_id"),
            "timestamp": (p.payload or {}).get("timestamp"),
            "appName": (p.payload or {}).get("appName"),
            "score": p.score,
        }
        for p in res
    ]


def delete_screen_activity_vectors(uid: str, ids: List[int]) -> None:
    if not ids:
        return
    _delete_by_raw_id(NS_SCREEN_ACTIVITY, [f"{uid}-sa-{sid}" for sid in ids])
