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
import os

try:
    import redis as _redis
except ImportError:
    _redis = None

REDIS_HOST = os.getenv("MINDGLASS_REDIS_HOST", "127.0.0.1")
REDIS_PORT = int(os.getenv("MINDGLASS_REDIS_PORT", "6379"))
REDIS_DB = int(os.getenv("MINDGLASS_REDIS_DB", "0"))
TTL_SECONDS = int(os.getenv("MINDGLASS_REDIS_TTL", str(24 * 3600)))

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
        return True
    except Exception as e:
        print(f"[redis-cache] overwrite 失败（不影响主流程）: {e}")
        return False


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
        return {"redis": "down"}
