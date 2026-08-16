"""MindGlass Redis 热缓存层（2026-08-10 哥哥设计定稿）

设计核心：
- 同一套 Redis 缓存，存的就是 graph 本身（node + edge + branch），
  每次有新节点/边就 RPUSH 增量追加（高频低代价快路径）
- 编辑/重放节点：后端算好完整新图 → 整体覆盖 key（低频重算慢路径，但干净）
  （深图编辑中间层节点会产生数量未知的废弃分支，Redis 里做节点级更新不现实，
    交给后端算完整新图整体覆盖才对）
- 断连恢复：从 Redis 读 graph，位置由前端固定算法重排（不存坐标）
- SQLite 仍是冷存储/权威层（run 结束时落盘），Redis 是热缓存/恢复层

Key 设计：
- mg:graph:{run_id}:items   LIST   每个元素 JSON：{"kind": "node|edge|branch", "data": {...}}
- mg:graph:{run_id}:meta    STRING JSON meta
- mg:graph:current          STRING 最近的 run_id（恢复入口）
- 所有 key TTL 24 小时（热缓存，过期自然清；冷数据在 SQLite）

降级原则：Redis 挂了绝不影响主流程——所有操作 try/except 兜底，只打日志。
"""

import json
import math
import os
import urllib.request

try:
    import redis as _redis
except ImportError:
    print("[state/redis_cache.py] 捕获到异常 ImportError（except 行 28）", flush=True)
    _redis = None

REDIS_HOST = os.getenv("MINDGLASS_REDIS_HOST", "127.0.0.1")
REDIS_PORT = int(os.getenv("MINDGLASS_REDIS_PORT", "6379"))
REDIS_DB = int(os.getenv("MINDGLASS_REDIS_DB", "0"))
TTL_SECONDS = int(os.getenv("MINDGLASS_REDIS_TTL", str(24 * 3600)))

# 复用 other-world 的向量化接口（本地 bge-large-zh-v1.5，1024 维，L2 已归一化）
RAG_API_URL = os.getenv("RAG_API_URL", "http://localhost:5000")
# 语义相似判定阈值：高于它才复用旧图（L2 归一化向量点积 = 余弦相似度）
REUSE_THRESHOLD = float(os.getenv("MINDGLASS_REUSE_THRESHOLD", "0.92"))
# query 向量索引 key（HASH：field=run_id，value=JSON{query, vector}）
QUERY_INDEX_KEY = "mg:query:index"

_client = None


def _get_client():
    """懒加载 Redis 客户端；连不上返回 None（降级）"""
    global _client
    if _redis is None:
        return None
    if _client is None:
        try:
            _client = _redis.Redis(
                host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB,
                decode_responses=True,
                protocol=2,  # Windows 版 Redis 5.0.14 不认 RESP3 的 HELLO，固定走 RESP2
                socket_connect_timeout=1, socket_timeout=2,
            )
            _client.ping()
        except Exception as e:
            print(f"[redis-cache] 连接失败，降级为无缓存: {e}")
            _client = None
    return _client


def _items_key(run_id: str) -> str:
    return f"mg:graph:{run_id}:items"


def _meta_key(run_id: str) -> str:
    return f"mg:graph:{run_id}:meta"


CURRENT_KEY = "mg:graph:current"


def append_item(run_id: str, kind: str, data: dict, meta: dict) -> bool:
    """正常推进快路径：RPUSH 增量追加一个图组件（node/edge/branch）。

    kind: "node" | "edge" | "branch"
    meta: 当前 meta 快照（随每次追加刷新，恢复时 meta 才是新的）
    返回是否写入成功。
    """
    c = _get_client()
    if c is None or not run_id:
        return False
    try:
        entry = json.dumps({"kind": kind, "data": data}, ensure_ascii=False)
        pipe = c.pipeline(transaction=False)
        pipe.rpush(_items_key(run_id), entry)
        pipe.set(_meta_key(run_id), json.dumps(meta, ensure_ascii=False))
        pipe.set(CURRENT_KEY, run_id)
        pipe.expire(_items_key(run_id), TTL_SECONDS)
        pipe.expire(_meta_key(run_id), TTL_SECONDS)
        pipe.execute()
        return True
    except Exception as e:
        print(f"[redis-cache] append 失败（不影响主流程）: {e}")
        return False


def overwrite(run_id: str, snapshot: dict) -> bool:
    """编辑/重放慢路径：后端算好的完整新图整体覆盖 Redis key。

    snapshot: _store.to_dict() 的完整图 {nodes, edges, branches, meta}
    用 pipeline 的 DEL+RPUSH 全量实现"整体覆盖"，语义等价于 SET。
    覆盖成功后后台线程登记 query 向量进复用索引（不阻塞 SSE 流收尾）。
    """
    c = _get_client()
    if c is None or not run_id:
        return False
    try:
        items = []
        for n in snapshot.get("nodes", []):
            items.append(json.dumps({"kind": "node", "data": n}, ensure_ascii=False))
        for e in snapshot.get("edges", []):
            items.append(json.dumps({"kind": "edge", "data": e}, ensure_ascii=False))
        for b in snapshot.get("branches", []):
            items.append(json.dumps({"kind": "branch", "data": b}, ensure_ascii=False))

        pipe = c.pipeline(transaction=False)
        pipe.delete(_items_key(run_id), _meta_key(run_id))
        if items:
            pipe.rpush(_items_key(run_id), *items)
        pipe.set(_meta_key(run_id),
                 json.dumps(snapshot.get("meta", {}), ensure_ascii=False))
        pipe.set(CURRENT_KEY, run_id)
        pipe.expire(_items_key(run_id), TTL_SECONDS)
        pipe.expire(_meta_key(run_id), TTL_SECONDS)
        pipe.execute()
        # 后台登记 query 向量（embed 可能慢，不能堵住流收尾）
        q = snapshot.get("meta", {}).get("query", "")
        if q:
            import threading
            threading.Thread(
                target=_index_query_bg, args=(run_id, q), daemon=True
            ).start()
        return True
    except Exception as e:
        print(f"[redis-cache] overwrite 失败（不影响主流程）: {e}")
        return False


def _index_query_bg(run_id: str, query: str):
    vec = embed_query(query)
    if vec:
        index_query(run_id, query, vec)


def load(run_id: str = "") -> dict:
    """断连恢复：从 Redis 读回完整图。

    run_id 为空时读 CURRENT_KEY（最近的 run）。
    返回 {nodes, edges, branches, meta}；没有数据返回空图。
    """
    empty = {"nodes": [], "edges": [], "branches": [], "meta": {}}
    c = _get_client()
    if c is None:
        return empty
    try:
        if not run_id:
            run_id = c.get(CURRENT_KEY)
            if not run_id:
                return empty
        raw_items = c.lrange(_items_key(run_id), 0, -1)
        if not raw_items:
            return empty
        graph = {"nodes": [], "edges": [], "branches": [], "meta": {}}
        for raw in raw_items:
            entry = json.loads(raw)
            kind, data = entry.get("kind"), entry.get("data")
            if kind == "node":
                graph["nodes"].append(data)
            elif kind == "edge":
                graph["edges"].append(data)
            elif kind == "branch":
                graph["branches"].append(data)
        raw_meta = c.get(_meta_key(run_id))
        if raw_meta:
            graph["meta"] = json.loads(raw_meta)
        return graph
    except Exception as e:
        print(f"[redis-cache] load 失败: {e}")
        return empty


def health() -> dict:
    """探活：/api/health 附带显示 Redis 状态"""
    c = _get_client()
    if c is None:
        return {"redis": "unavailable"}
    try:
        c.ping()
        return {"redis": "ok", "host": REDIS_HOST, "port": REDIS_PORT}
    except Exception:
        print("[state/redis_cache.py] 捕获到异常 Exception（except 行 195）", flush=True)
        return {"redis": "down"}


# ─────────────────── 高频 query 思维图复用 ───────────────────

def embed_query(text: str):
    """调 other-world /api/embed 拿 1024 维向量；服务不在线返回 None（静默降级）"""
    if not text:
        return None
    try:
        body = json.dumps({"texts": [text]}).encode("utf-8")
        req = urllib.request.Request(
            f"{RAG_API_URL}/api/embed",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        vecs = result.get("embeddings", [])
        return vecs[0] if vecs else None
    except Exception as e:
        print(f"[redis-cache] embed 失败（降级为不复用）: {e}")
        return None


def index_query(run_id: str, query: str, vector: list) -> bool:
    """run 结束时登记 query 向量进索引（复用候选）"""
    c = _get_client()
    if c is None or not run_id or not query or not vector:
        return False
    try:
        payload = json.dumps({"query": query, "vector": vector}, ensure_ascii=False)
        c.hset(QUERY_INDEX_KEY, run_id, payload)
        c.expire(QUERY_INDEX_KEY, TTL_SECONDS)
        return True
    except Exception as e:
        print(f"[redis-cache] query 索引写入失败: {e}")
        return False


def find_reusable(query: str, threshold: float = None) -> dict:
    """语义相似检索：找可复用的已缓存思维图。

    返回：
      命中：{"hit": True, "similarity", "run_id", "cached_query", "graph"}
      未命中：{"hit": False, "best_similarity", "reason"}
    向量化服务不在线或索引为空均返回未命中，绝不阻断主流程。
    """
    threshold = REUSE_THRESHOLD if threshold is None else threshold
    c = _get_client()
    if c is None:
        return {"hit": False, "best_similarity": 0.0, "reason": "redis_down"}
    vec = embed_query(query)
    if vec is None:
        return {"hit": False, "best_similarity": 0.0, "reason": "embed_unavailable"}
    try:
        entries = c.hgetall(QUERY_INDEX_KEY)  # {run_id: json}
        if not entries:
            return {"hit": False, "best_similarity": 0.0, "reason": "index_empty"}
        best_sim, best_run = 0.0, ""
        best_payload = None
        for run_id, raw in entries.items():
            try:
                item = json.loads(raw)
            except Exception:
                print("[state/redis_cache.py] 捕获到异常 Exception（except 行 261）", flush=True)
                continue
            cached_vec = item.get("vector", [])
            if len(cached_vec) != len(vec):
                continue
            # 两边都 L2 归一化 → 点积即余弦相似度
            sim = sum(a * b for a, b in zip(vec, cached_vec))
            if sim > best_sim:
                best_sim, best_run, best_payload = sim, run_id, item
        if best_sim >= threshold and best_payload is not None:
            graph = load(best_run)
            if graph.get("nodes"):
                return {
                    "hit": True,
                    "similarity": round(best_sim, 4),
                    "run_id": best_run,
                    "cached_query": best_payload.get("query", ""),
                    "graph": graph,
                }
            return {"hit": False, "best_similarity": round(best_sim, 4),
                    "reason": "graph_expired"}
        return {"hit": False, "best_similarity": round(best_sim, 4),
                "reason": "below_threshold"}
    except Exception as e:
        print(f"[redis-cache] 复用检索失败: {e}")
        return {"hit": False, "best_similarity": 0.0, "reason": "error"}
