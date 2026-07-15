import requests
import json
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

url = "http://localhost:8002/api/run"
params = {"query": "感冒发烧怎么办"}

print("=== 测试 SSE 流 ===")
resp = requests.get(url, params=params, stream=True, timeout=120)

edges_ok = True
node_count = 0
last_graph = None

for line in resp.iter_lines():
    if line:
        text = line.decode("utf-8")
        if text.startswith("data:"):
            data = json.loads(text[5:])
            event_type = data.get("type")
            print(f"\n--- {event_type} ---")
            if event_type == "node_complete":
                node = data["data"]["node"]
                node_count += 1
                print(f"  Node: {node['id']} ({node['type']}) - {node['status']}")
            elif event_type == "run_complete":
                graph = data["data"]["graph"]
                last_graph = graph
                print(f"  Nodes: {len(graph['nodes'])}")
                print(f"  Edges: {len(graph['edges'])}")
                # 检查边连接
                node_ids = {n["id"] for n in graph["nodes"]}
                for edge in graph["edges"]:
                    from_ok = edge["from"] in node_ids
                    to_ok = edge["to"] in node_ids
                    if not from_ok or not to_ok:
                        print(f"  ❌ 断线边: {edge['from']} -> {edge['to']}")
                        edges_ok = False
                    else:
                        print(f"  ✅ 边: {edge['from']} -> {edge['to']}")
            elif event_type == "status":
                print(f"  {data['data']['message']}")
            elif event_type == "error":
                print(f"  ❌ {data['data']['message']}")

print(f"\n=== 结果 ===")
print(f"节点数: {node_count}")
if edges_ok:
    print("✅ 所有边连接正确")
else:
    print("❌ 存在断线边")
