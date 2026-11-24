"""factory-graph-mcp — 설비 연결 그래프를 AI에게 도구로 주는 MCP 서버.

실행
  factory-graph-mcp                       예제 공장 데이터로 stdio 서버
  factory-graph-mcp --data ./my_plant     내 공장 데이터 폴더 (equipment.csv, connections.csv)
  factory-graph-mcp --http --port 8000    원격 데모용 Streamable HTTP (경로 /mcp)

데이터 폴더는 --data 또는 환경 변수 FACTORY_GRAPH_DATA 로 정한다. 둘 다 없으면 예제 공장을 쓴다.
도구는 모두 읽기 전용이다. 데이터 파일을 바꾸지 않는다.
"""

from __future__ import annotations

import argparse
import os
from importlib.resources import files
from pathlib import Path

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from . import __version__
from .graph import DataError, FactoryGraph

INSTRUCTIONS = """\
공장 설비가 서로 무엇(전원, 냉각수, 압축공기 …)을 주고받는지 담은 연결 그래프입니다.
설비에 이상이 생기면 원인은 그 설비가 아니라 상류(그 설비에 무언가를 공급하는 쪽)에 있을 수 있습니다.
상류 설비는 기준에 닿지 않아 알람이 없을 수도 있습니다.

쓰는 순서
1. 사람이 "1호기", "칠러1"처럼 부르면 find_equipment 로 설비 번호를 찾습니다.
2. 한 대에 이상이 있으면 trace_upstream 으로 상류를 가까운 것부터 봅니다.
3. 여러 대에 동시에 이상이 있으면 common_upstream 으로 함께 쓰는 상류를 먼저 봅니다.
이 도구는 "어디를 봐야 하는지"만 알려 줍니다. 원인을 단정하지 말고, 현장 확인이 필요하다고 함께 안내하세요.
"""

READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)


def default_data_dir() -> Path:
    env = os.environ.get("FACTORY_GRAPH_DATA")
    return Path(env) if env else Path(str(files("factory_graph_mcp") / "sample"))


def build_server(graph: FactoryGraph) -> MCPServer:
    mcp = MCPServer(
        name="factory-graph",
        title="Factory Graph",
        instructions=INSTRUCTIONS,
        version=__version__,
        website_url="https://github.com/prag-ai/factory-graph-mcp",
    )

    @mcp.tool(annotations=READ_ONLY)
    def find_equipment(query: str, limit: int = 10) -> list[dict]:
        """설비 번호, 이름, 현장에서 부르는 별칭, 설비 종류로 설비를 찾습니다.

        예: "1호기", "칠러", "CNC-03". 정확히 맞는 것이 앞에 옵니다.
        """
        return graph.find(query, limit)

    @mcp.tool(annotations=READ_ONLY)
    def get_equipment(equipment_id: str) -> dict:
        """설비 한 대의 정보와, 바로 붙은 연결(공급받는 것 receives_from, 공급하는 것 supplies_to)을 돌려줍니다."""
        return graph.get(equipment_id)

    @mcp.tool(annotations=READ_ONLY)
    def trace_upstream(equipment_id: str, max_depth: int = 5, kinds: list[str] | None = None) -> dict:
        """설비에서 출발해 공급하는 쪽으로 거슬러 올라가며 상류 설비를 가까운 순서로 돌려줍니다.

        depth 1 은 바로 공급하는 설비, 2 는 그 설비에 공급하는 설비입니다.
        path 는 상류에서 출발 설비까지 무엇이 흘러오는지 보여 줍니다.
        kinds 로 연결 종류를 좁힐 수 있습니다. 예: ["냉각수", "절삭유 냉각수"].
        서로 주고받는 연결(순환)은 한 번만 따라가고 cycles_skipped 에 적습니다.
        """
        return graph.upstream(equipment_id, max_depth, kinds)

    @mcp.tool(annotations=READ_ONLY)
    def common_upstream(equipment_ids: list[str], max_depth: int = 5, kinds: list[str] | None = None) -> dict:
        """여러 설비에 동시에 이상이 있을 때, 그 설비들이 함께 쓰는 상류 설비를 돌려줍니다.

        두 대 이상이 함께 쓰는 상류만 나오고, 많은 설비를 덮을수록, 가까울수록 앞에 옵니다.
        covers_all 이 true 이면 준 설비 전부가 그 상류를 씁니다.
        """
        return graph.common_upstream(equipment_ids, max_depth, kinds)

    @mcp.tool(annotations=READ_ONLY)
    def describe_plant() -> dict:
        """불러온 공장 데이터의 규모를 돌려줍니다: 설비 수, 연결 수, 설비 종류별 대수, 연결 종류별 개수."""
        return graph.summary()

    return mcp


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="factory-graph-mcp", description="설비 연결 그래프 MCP 서버")
    p.add_argument("--data", type=Path, default=None, help="equipment.csv, connections.csv 가 든 폴더")
    p.add_argument("--http", action="store_true", help="Streamable HTTP 로 띄운다 (기본은 stdio)")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--check", action="store_true", help="데이터만 읽어 요약을 찍고 끝낸다")
    args = p.parse_args(argv)

    data_dir = args.data or default_data_dir()
    try:
        graph = FactoryGraph.from_dir(data_dir)
    except DataError as e:
        raise SystemExit(f"데이터를 읽지 못했습니다 ({data_dir}): {e}")

    if args.check:
        import json
        print(json.dumps(graph.summary(), ensure_ascii=False, indent=2))
        return

    server = build_server(graph)
    if args.http:
        server.run("streamable-http", host=args.host, port=args.port, stateless_http=True)
    else:
        server.run("stdio")


if __name__ == "__main__":
    main()
