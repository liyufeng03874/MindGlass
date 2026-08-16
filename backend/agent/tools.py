"""MindGlass Agent — 工具注册与执行（统一工具注册表）

chatBI 扩展：gen_sql / exec_sql / plot
注册表字段：name / description / params / func / readonly / needs_confirm
"""

import httpx
import json
import hashlib
from typing import Callable, Optional
from decimal import Decimal
from dotenv import load_dotenv
import os
import re
from bs4 import BeautifulSoup

load_dotenv()

RAG_API_URL = os.getenv("RAG_API_URL", "http://localhost:8001")

# chatBI 数据库连接（只读账号）
CHATBI_DB_HOST = os.getenv("CHATBI_DB_HOST", "127.0.0.1")
CHATBI_DB_PORT = int(os.getenv("CHATBI_DB_PORT", "3306"))
CHATBI_DB_USER = os.getenv("CHATBI_DB_USER", "readonly")
CHATBI_DB_PASS = os.getenv("CHATBI_DB_PASS", "")
CHATBI_DB_NAME = os.getenv("CHATBI_DB_NAME", "analytics")

# chatBI 可用数据库列表（支持多库，逗号分隔）
CHATBI_DATABASES = [db.strip() for db in os.getenv("CHATBI_DATABASES", CHATBI_DB_NAME).split(",")]

# Redis 连接信息（复用思镜 Redis）
REDIS_HOST = os.getenv("MINDGLASS_REDIS_HOST", "127.0.0.1")
REDIS_PORT = int(os.getenv("MINDGLASS_REDIS_PORT", "6379"))
REDIS_DB = int(os.getenv("MINDGLASS_REDIS_DB", "0"))

# 工具注册表
_tools: dict[str, dict] = {}


def register_tool(name: str, description: str, params: list[dict],
                  readonly: bool = True, needs_confirm: bool = False):
    """装饰器：注册工具

    Args:
        name: 工具名
        description: 工具描述（给 LLM planner 看）
        params: 参数 schema 列表
        readonly: 是否只读（True=安全无需确认）
        needs_confirm: 是否需要人工确认后才执行
    """
    def decorator(func: Callable):
        _tools[name] = {
            "name": name,
            "description": description,
            "params": params,
            "func": func,
            "readonly": readonly,
            "needs_confirm": needs_confirm,
        }
        return func
    return decorator


def get_tool(name: str) -> Optional[dict]:
    return _tools.get(name)


def list_tools() -> list[dict]:
    return [
        {
            "name": t["name"],
            "description": t["description"],
            "params": t["params"],
            "readonly": t.get("readonly", True),
            "needs_confirm": t.get("needs_confirm", False),
        }
        for t in _tools.values()
    ]


# ============ 内置工具 ============

@register_tool(
    name="search",
    description="网络搜索，返回搜索结果摘要（使用 Tavily AI 搜索引擎）",
    params=[
        {"name": "query", "type": "string", "description": "搜索关键词"},
        {"name": "top_k", "type": "integer", "description": "返回结果数量", "default": 5},
    ],
)
async def tool_search(query: str, top_k: int = 5) -> dict:
    """
    网络搜索工具（使用 Tavily AI 搜索引擎）
    返回结构化搜索结果
    """
    import os
    tavily_key = os.getenv("TAVILY_API_KEY")
    if not tavily_key:
        return {"query": query, "error": "TAVILY_API_KEY not configured", "results": []}

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                "https://api.tavily.com/search",
                json={
                    "query": query,
                    "search_depth": "basic",
                    "max_results": top_k,
                    "include_answer": True,
                    "include_images": False,
                },
                headers={"Authorization": f"Bearer {tavily_key}", "Content-Type": "application/json"},
            )
            if resp.status_code == 200:
                data = resp.json()
                results = []
                for r in data.get("results", []):
                    results.append({
                        "title": r.get("title", ""),
                        "url": r.get("url", ""),
                        "snippet": r.get("content", ""),
                    })
                return {
                    "query": query,
                    "answer": data.get("answer", ""),
                    "results": results,
                    "count": len(results),
                }
            else:
                return {"query": query, "error": f"Tavily API error: {resp.status_code} - {resp.text}", "results": []}
    except Exception as e:
        return {"query": query, "error": str(e), "results": []}


@register_tool(
    name="rag_retrieve",
    description="从本地知识库检索相关段落（复用 other-world 的 RAG 能力）",
    params=[
        {"name": "query", "type": "string", "description": "检索查询"},
        {"name": "top_k", "type": "integer", "description": "返回段落数量", "default": 5},
    ],
)
async def tool_rag_retrieve(query: str, top_k: int = 5) -> dict:
    """
    调用 other-world 的纯检索接口（不做 LLM 生成）
    POST /api/chat/retrieve
    """
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{RAG_API_URL}/api/chat/retrieve",
                json={"message": query},
            )
            if resp.status_code == 200:
                data = resp.json()
                return {
                    "query": query,
                    "passages": data.get("passages", []),
                    "count": data.get("count", 0),
                }
            else:
                return {
                    "query": query,
                    "error": f"RAG retrieve error: {resp.status_code}",
                    "passages": [],
                    "count": 0,
                }
    except Exception as e:
        return {
            "query": query,
            "error": str(e),
            "passages": [],
            "count": 0,
        }


# ============ chatBI 工具 ============

@register_tool(
    name="gen_sql",
    description=(
        "根据用户的自然语言数据分析问题，生成 SQL 查询语句。"
        "只生成 SELECT 语句，不执行。需要配合 exec_sql 工具使用。"
        "适用场景：用户问数据相关的问题（统计、趋势、排名、对比等）"
    ),
    params=[
        {"name": "query", "type": "string", "description": "用户的自然语言数据分析问题"},
        {"name": "schema_hint", "type": "string", "description": "可选的表结构提示", "default": ""},
    ],
    readonly=True,
)
async def tool_gen_sql(query: str, schema_hint: str = "") -> dict:
    """
    gen_sql: 调用 LLM 根据 schema 生成 SQL。
    schema 优先从 Redis 缓存读取，miss 则查 information_schema。
    生成的 SQL 只做 SELECT，不做任何写入操作。
    """
    from agent.llm import client, LLM_MODEL

    # 1. 获取 schema（Redis 缓存 → 查库兜底）
    schema_text = await _get_schema_cached()
    if schema_hint:
        schema_text = f"{schema_text}\n\n补充提示：{schema_hint}"

    # 2. 调 LLM 生成 SQL
    system_prompt = (
        "你是一个 SQL 生成专家。根据用户问题和数据库 schema 生成 MySQL SELECT 语句。\n"
        "规则：\n"
        "1. 只生成 SELECT 语句，禁止 INSERT/UPDATE/DELETE/DROP/ALTER/CREATE\n"
        "2. 使用标准 MySQL 语法\n"
        "3. 如果问题无法用现有表回答，返回 {\"error\": \"原因\"}\n"
        "4. 只返回纯 SQL，不要 markdown 围栏，不要解释\n"
        "5. 涉及时间范围时注意字段的实际格式\n"
        "6. 聚合查询必须有 GROUP BY\n"
        "7. 大表查询加 LIMIT（默认 100）\n"
    )
    user_prompt = f"数据库 schema:\n{schema_text}\n\n用户问题: {query}\n\n请生成 SQL:"

    try:
        resp = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
            max_tokens=1024,
        )
        sql_text = resp.choices[0].message.content.strip()
        # 清理 markdown 围栏
        if sql_text.startswith("```"):
            sql_text = sql_text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

        # 基础安全校验：禁止非 SELECT 语句
        sql_upper = sql_text.upper().strip()
        forbidden = ["INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "TRUNCATE", "EXEC"]
        for kw in forbidden:
            if sql_upper.startswith(kw) or f" {kw} " in sql_upper:
                return {"error": f"SQL 安全检查失败：包含禁止关键字 {kw}", "sql": sql_text}

        return {"sql": sql_text, "query": query}
    except Exception as e:
        return {"error": f"SQL 生成失败: {str(e)}", "query": query}


@register_tool(
    name="exec_sql",
    description=(
        "执行 gen_sql 生成的 SQL 查询并返回结构化结果。"
        "使用只读数据库连接，有超时保护和结果行数限制。"
        "输入必须是 gen_sql 输出的 SQL 字符串。"
    ),
    params=[
        {"name": "sql", "type": "string", "description": "要执行的 SQL 查询语句"},
    ],
    readonly=True,
)
async def tool_exec_sql(sql: str) -> dict:
    """
    exec_sql: 校验 → 缓存查找 → 执行 → 返回结构化结果。
    只读连接，禁止写入；超时 30s；结果上限 1000 行。
    """
    import time

    # 1. 安全校验
    sql_upper = sql.upper().strip()
    if not sql_upper.startswith("SELECT") and not sql_upper.startswith("WITH"):
        return {"error": "只允许 SELECT/WITH 查询", "sql": sql}

    forbidden = ["INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "TRUNCATE", "EXEC", ";--"]
    for kw in forbidden:
        if f" {kw} " in sql_upper or sql_upper.endswith(kw):
            return {"error": f"SQL 安全检查失败：包含禁止关键字 {kw}", "sql": sql}

    # 2. 查 Redis 缓存
    cache_key = f"mg:sql_result:{hashlib.md5(sql.encode()).hexdigest()}"
    cached = await _redis_get(cache_key)
    if cached:
        try:
            result = json.loads(cached)
            result["_cache_hit"] = True
            return result
        except Exception:
            pass

    # 3. 执行 SQL
    try:
        import pymysql
        conn = pymysql.connect(
            host=CHATBI_DB_HOST,
            port=CHATBI_DB_PORT,
            user=CHATBI_DB_USER,
            password=CHATBI_DB_PASS,
            database=CHATBI_DB_NAME,
            charset="utf8mb4",
            read_timeout=30,
            connect_timeout=10,
            cursorclass=pymysql.cursors.DictCursor,
        )
        start_time = time.time()
        with conn.cursor() as cursor:
            cursor.execute(sql)
            rows = cursor.fetchall()
        elapsed_ms = round((time.time() - start_time) * 1000)
        conn.close()

        # 截断保护
        total_rows = len(rows)
        truncated = False
        if total_rows > 1000:
            rows = rows[:1000]
            truncated = True

        result = {
            "columns": list(rows[0].keys()) if rows else [],
            "rows": rows,
            "row_count": total_rows,
            "truncated": truncated,
            "elapsed_ms": elapsed_ms,
            "sql": sql,
        }

        # 4. 写入 Redis 缓存（TTL 30min）
        await _redis_set(cache_key, json.dumps(result, ensure_ascii=False, default=str), ttl=1800)

        return result
    except ImportError:
        return {"error": "pymysql 未安装，请 pip install pymysql", "sql": sql}
    except Exception as e:
        return {"error": f"SQL 执行失败: {str(e)}", "sql": sql}


@register_tool(
    name="plot",
    description=(
        "将 SQL 查询结果转换为 ECharts 图表配置。"
        "输出标准 ECharts option JSON，前端直接渲染。"
        "支持折线图(line)、柱状图(bar)、饼图(pie)、散点图(scatter)。"
    ),
    params=[
        {"name": "data", "type": "object", "description": "exec_sql 返回的结构化数据（含 columns 和 rows）"},
        {"name": "type", "type": "string", "description": "图表类型: line/bar/pie/scatter/auto", "default": "auto"},
        {"name": "title", "type": "string", "description": "图表标题", "default": ""},
    ],
    readonly=True,
)
async def tool_plot(data: dict, type: str = "auto", title: str = "") -> dict:
    chart_type = type  # 兼容 LLM 输出的 type 参数
    """
    plot: 将 SQL 结果转为 ECharts option。
    auto 模式根据数据结构自动选择图表类型。
    """
    columns = data.get("columns", [])
    rows = data.get("rows", [])

    if not rows:
        return {"error": "无数据可绘图", "echarts_option": None}

    # 自动推断图表类型
    if chart_type == "auto":
        chart_type = _infer_chart_type(columns, rows)

    # 生成 ECharts option
    option = _build_echarts_option(columns, rows, chart_type, title)

    return {
        "echarts_option": option,
        "chart_type": chart_type,
        "title": title or option.get("title", {}).get("text", ""),
        "row_count": len(rows),
    }


# ── chatBI 辅助函数 ──

async def _get_schema_cached() -> str:
    """从 Redis 缓存或 information_schema 获取所有可用数据库的 schema"""
    all_schemas = []
    for db_name in CHATBI_DATABASES:
        cache_key = f"mg:schema:{db_name}"
        cached = await _redis_get(cache_key)
        if cached:
            all_schemas.append(f"=== 数据库: {db_name} ===\n{cached}")
            continue

        try:
            import pymysql
            conn = pymysql.connect(
                host=CHATBI_DB_HOST, port=CHATBI_DB_PORT,
                user=CHATBI_DB_USER, password=CHATBI_DB_PASS,
                database=db_name, charset="utf8mb4",
                connect_timeout=10,
            )
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE, COLUMN_COMMENT "
                    "FROM INFORMATION_SCHEMA.COLUMNS "
                    "WHERE TABLE_SCHEMA = %s ORDER BY TABLE_NAME, ORDINAL_POSITION",
                    (db_name,)
                )
                rows = cursor.fetchall()
            conn.close()

            tables: dict[str, list] = {}
            for table, col, dtype, comment in rows:
                tables.setdefault(table, []).append(f"  {col} ({dtype}){' -- ' + comment if comment else ''}")
            schema_lines = []
            for table, cols in tables.items():
                schema_lines.append(f"表 {table}:")
                schema_lines.extend(cols)
            schema_text = "\n".join(schema_lines)

            await _redis_set(cache_key, schema_text, ttl=3600)
            all_schemas.append(f"=== 数据库: {db_name} ===\n{schema_text}")
        except Exception as e:
            all_schemas.append(f"=== 数据库: {db_name} ===\n(schema 获取失败: {str(e)})")

    return "\n\n".join(all_schemas)


def _infer_chart_type(columns: list[str], rows: list[dict]) -> str:
    """根据数据结构自动推断图表类型"""
    if not rows or not columns:
        return "bar"
    n_cols = len(columns)
    n_rows = len(rows)

    # 两列：一维分类 + 一维数值 → pie（少量）或 bar
    if n_cols == 2:
        is_numeric_second = all(_is_number(r.get(columns[1])) for r in rows[:20] if r.get(columns[1]) is not None)
        if is_numeric_second:
            metric_name = str(columns[1]).lower()
            share_hint = any(k in metric_name for k in ("占比", "比例", "份额", "share", "ratio", "rate", "percent", "pct"))
            if share_hint or n_rows <= 6:
                return "pie"
        return "bar"

    # 含日期/时间列 → line
    date_keywords = ["date", "time", "month", "year", "day", "日期", "时间", "月", "年"]
    for col in columns:
        if any(kw in col.lower() for kw in date_keywords):
            return "line"

    # 默认柱状图
    return "bar"


# ID/编号类列（emp_no、dept_no、orderid 等）不该当数值指标画柱子，只当标签用
_ID_SUFFIXES = ("id", "_id", "no", "_no", "_code", "_sn", "_uuid", "编号", "序号", "编码", "号")
_ID_EXACT = {"id", "ids", "no", "code"}


def _is_number(v) -> bool:
    """判断是不是数值（含 Decimal——pymysql 对 DECIMAL/AVG/SUM 返回该类型）"""
    return isinstance(v, (int, float, Decimal))


def _looks_like_id_column(name: str) -> bool:
    """判断列是不是 ID/编号类列（员工号、部门号、订单号等）"""
    n = str(name).lower().strip()
    if n in _ID_EXACT:
        return True
    return any(n.endswith(s) for s in _ID_SUFFIXES)


def _hex_to_rgba(hex_color: str, alpha: float) -> str:
    """#a78bfa → rgba(167,139,250,alpha)"""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


def _json_safe(v):
    """Decimal → float，其余原样（保证 option 可直接 JSON 序列化）"""
    if isinstance(v, Decimal):
        return float(v)
    return v


def _build_echarts_option(columns: list[str], rows: list[dict], chart_type: str, title: str) -> dict:
    """构建 ECharts option JSON"""
    if not rows:
        return {}

    # 列分类：维度列 / 数值指标列 / ID 标签列
    dims, metrics, label_cols = [], [], []
    for c in columns:
        if _looks_like_id_column(c):
            label_cols.append(c)
        elif _is_number(rows[0].get(c)):
            metrics.append(c)
        elif c not in dims:
            dims.append(c)

    x_col = (dims or columns)[0]  # X 轴/分类列（优先维度列）
    y_cols = metrics
    if not y_cols:
        y_cols = [columns[1]] if len(columns) > 1 else []  # 兜底取第二列
    if not y_cols:
        return {}

    x_data = [str(r.get(x_col, "")) for r in rows]

    # ── 深色主题配色（与思镜 UI 统一）──
    _TEXT_COLOR = "#fff"
    _AXIS_LINE = "rgba(255,255,255,0.15)"
    _SPLIT_LINE = "rgba(255,255,255,0.06)"
    _PALETTE = ["#a78bfa", "#60a5fa", "#34d399", "#fbbf24", "#f87171", "#c084fc", "#38bdf8"]

    series = []
    for yc in y_cols:
        s = {
            "name": yc,
            "type": chart_type,
            "data": [_json_safe(r.get(yc, 0)) for r in rows],
        }
        # 有 ID 标签列（如 emp_no）时，把标签值附到每个数据点，供 tooltip/柱顶标签用
        if label_cols:
            s["data"] = [
                dict({"value": _json_safe(r.get(yc, 0))}, **{lc: _json_safe(r.get(lc)) for lc in label_cols})
                for r in rows
            ]
        series.append(s)

    # 单指标 + 有 ID 标签列：tooltip 里额外展示标签（排除 X 轴那列，避免重复）
    # 用 trigger="item"（悬浮单根柱子），{@字段} 模板在此模式下 100% 生效
    display_label_cols = [c for c in label_cols if c != x_col]
    _item_trigger_single = chart_type == "bar" and len(y_cols) == 1 and display_label_cols

    option = {
        "backgroundColor": "transparent",
        "color": _PALETTE,
        "title": {
            "text": title or f"{y_cols[0]} by {x_col}",
            "textStyle": {"color": _TEXT_COLOR, "fontSize": 14, "fontWeight": 600},
            "left": "center",
        },
        "tooltip": {
            "trigger": "item" if _item_trigger_single else ("axis" if chart_type != "pie" else "item"),
            "backgroundColor": "rgba(30,30,46,0.85)",
            "borderColor": "rgba(255,255,255,0.1)",
            "textStyle": {"color": "#e0e0e0", "fontSize": 13},
        },
        "legend": {
            "data": y_cols if len(y_cols) > 1 else [],
            "top": 30,
            "textStyle": {"color": _TEXT_COLOR, "fontSize": 12},
        },
        "series": series,
    }

    if _item_trigger_single:
        tip_parts = [f"{x_col}: {{b}}"] + [f"{lc}: {{@{lc}}}" for lc in display_label_cols]
        option["tooltip"]["formatter"] = "<br/>".join(tip_parts)

    if chart_type != "pie":
        option["xAxis"] = {
            "type": "category",
            "data": x_data,
            "axisLabel": {"color": _TEXT_COLOR, "fontSize": 11},
            "axisLine": {"lineStyle": {"color": _AXIS_LINE}},
            "axisTick": {"show": False},
        }
        option["yAxis"] = {
            "type": "value",
            "axisLabel": {"color": _TEXT_COLOR, "fontSize": 11},
            "axisLine": {"show": False},
            "splitLine": {"lineStyle": {"color": _SPLIT_LINE}},
        }
        # bar 图加圆角 + 渐变（按系列下标取不同配色，避免多系列全同色）
        if chart_type == "bar":
            for idx, s in enumerate(option["series"]):
                base = _PALETTE[idx % len(_PALETTE)]
                s["itemStyle"] = {
                    "borderRadius": [4, 4, 0, 0],
                    "color": {
                        "type": "linear", "x": 0, "y": 0, "x2": 0, "y2": 1,
                        "colorStops": [
                            {"offset": 0, "color": base},
                            {"offset": 1, "color": _hex_to_rgba(base, 0.3)},
                        ],
                    },
                }
            # 单指标 + 有 ID 标签：柱顶显示标签值（如 emp_no），一眼看出是哪个员工
            if len(y_cols) == 1 and display_label_cols:
                lc = display_label_cols[0]
                for s in option["series"]:
                    s["label"] = {
                        "show": True,
                        "position": "top",
                        "color": _TEXT_COLOR,
                        "fontSize": 10,
                        "formatter": f"{{@{lc}}}",
                    }
    else:
        # pie 图用 name+value 格式
        option["series"] = [{
            "name": y_cols[0] if y_cols else "",
            "type": "pie",
            "data": [{"name": x_data[i], "value": _json_safe(rows[i].get(y_cols[0], 0))} for i in range(len(rows))],
        }]

    return option


# ── Redis 辅助（轻量封装，不依赖 redis_cache.py 的主流程逻辑）──

_redis_pool = None

async def _get_redis():
    """获取 Redis 连接（懒初始化）"""
    global _redis_pool
    if _redis_pool is None:
        try:
            import redis.asyncio as aioredis
            _redis_pool = aioredis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, decode_responses=True)
        except Exception:
            return None
    return _redis_pool

async def _redis_get(key: str) -> Optional[str]:
    """Redis GET，失败静默降级返回 None"""
    try:
        r = await _get_redis()
        if r:
            return await r.get(key)
    except Exception:
        pass
    return None

async def _redis_set(key: str, value: str, ttl: int = 3600) -> bool:
    """Redis SET with TTL，失败静默降级返回 False"""
    try:
        r = await _get_redis()
        if r:
            await r.set(key, value, ex=ttl)
            return True
    except Exception:
        pass
    return False


# ============ 工具执行器 ============

async def execute_tool(tool_name: str, params: dict) -> dict:
    """执行指定工具"""
    tool = get_tool(tool_name)
    if not tool:
        return {"error": f"Unknown tool: {tool_name}", "tool": tool_name, "params": params}

    func = tool["func"]
    try:
        result = await func(**params)
        return {
            "tool": tool_name,
            "params": params,
            "result": result,
        }
    except Exception as e:
        return {
            "tool": tool_name,
            "params": params,
            "error": str(e),
        }
