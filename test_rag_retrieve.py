import httpx
import json
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

print("测试 MindGlass ReAct 流程（含 rag_retrieve 工具）")
print("=" * 60)

with httpx.Client(timeout=60.0) as client:
    with client.stream('GET', 'http://localhost:8002/api/run', params={'query': '激光治眼睛会复发吗'}) as resp:
        for line in resp.iter_lines():
            if line.startswith('data: '):
                event = json.loads(line[6:])
                etype = event['type']
                if etype == 'node_complete':
                    node = event['data']['node']
                    print(f"[{etype}] {node['type']} (step={node['step_index']}) status={node['status']}")
                    if 'data' in node and node['data']:
                        # 只打印简短信息
                        for k, v in node['data'].items():
                            if isinstance(v, str) and len(v) > 100:
                                print(f"  {k}: {v[:100]}...")
                            else:
                                print(f"  {k}: {v}")
                elif etype == 'run_complete':
                    meta = event['data']['graph']['meta']
                    nodes = event['data']['graph']['nodes']
                    edges = event['data']['graph']['edges']
                    print(f"[{etype}] query='{meta['query']}' steps={meta['total_steps']} nodes={len(nodes)} edges={len(edges)}")
                elif etype == 'status':
                    print(f"[{etype}] {event['data']['message']}")
                elif etype == 'error':
                    print(f"[{etype}] {event['data']['message']}")
                else:
                    print(f"[{etype}]")

print("\n测试完成!")
