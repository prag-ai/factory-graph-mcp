import asyncio
import json
from pathlib import Path

import pytest

from factory_graph_mcp.graph import DataError, FactoryGraph
from factory_graph_mcp.server import build_server, default_data_dir


@pytest.fixture(scope="module")
def g() -> FactoryGraph:
    return FactoryGraph.from_dir(default_data_dir())


def write_plant(tmp_path: Path, equipment: str, connections: str) -> Path:
    (tmp_path / "equipment.csv").write_text(equipment, encoding="utf-8")
    (tmp_path / "connections.csv").write_text(connections, encoding="utf-8")
    return tmp_path


def ids(rows, key="equipment_id"):
    return [r[key] for r in rows]


# ── 찾기 ──────────────────────────────────────────────────────────

def test_find_by_alias_exact_first(g):
    assert g.find("1호기")[0]["equipment_id"] == "CNC-01"


def test_find_by_type(g):
    assert set(ids(g.find("칠러"))) == {"CLT-01", "CLT-02"}


def test_find_empty_query(g):
    assert g.find("   ") == []


def test_get_lists_both_directions(g):
    e = g.get("CLT-01")
    assert {c["from_id"] for c in e["receives_from"]} == {"MCC-1", "CT-01"}
    assert {c["to_id"] for c in e["supplies_to"]} == {"CNC-01", "CNC-02"}


# ── 상류 ──────────────────────────────────────────────────────────

def test_upstream_depth_and_path(g):
    r = g.upstream("CNC-01")
    by_id = {u["equipment_id"]: u for u in r["upstream"]}
    assert {k for k, v in by_id.items() if v["depth"] == 1} == {"MCC-1", "CLT-01", "ADR-01"}
    assert by_id["CT-01"]["depth"] == 2
    assert by_id["CT-01"]["path"] == "CT-01 —냉각수→ CLT-01 —절삭유 냉각수→ CNC-01"
    assert by_id["P-01"]["depth"] == 3
    # 가까운 것이 먼저 나온다
    depths = [u["depth"] for u in r["upstream"]]
    assert depths == sorted(depths)


def test_upstream_accepts_alias(g):
    assert g.upstream("1호기")["start"]["equipment_id"] == "CNC-01"


def test_upstream_max_depth(g):
    r = g.upstream("CNC-01", max_depth=1)
    assert {u["depth"] for u in r["upstream"]} == {1}


def test_upstream_kinds_filter(g):
    r = g.upstream("CNC-01", kinds=["절삭유 냉각수", "냉각수", "순환수"])
    assert ids(r["upstream"]) == ["CLT-01", "CT-01", "P-01"]


def test_upstream_unknown_equipment(g):
    with pytest.raises(DataError, match="찾을 수 없습니다"):
        g.upstream("CNC-99")


def test_upstream_cycle_terminates(tmp_path):
    # 기계가 조절기에 전원을 주고, 조절기가 기계에 온수를 준다 — 서로 주고받는 연결
    d = write_plant(
        tmp_path,
        "equipment_id,name,type\nM-1,기계,기계\nT-1,조절기,조절기\nP-1,분전반,분전반\n",
        "from_id,to_id,kind\nP-1,M-1,전원\nM-1,T-1,전원\nT-1,M-1,온수\n",
    )
    r = FactoryGraph.from_dir(d).upstream("M-1")
    assert sorted(ids(r["upstream"])) == ["P-1", "T-1"]
    assert r["cycles_skipped"] == ["M-1 → T-1 (전원)"]


# ── 공통 상류 ──────────────────────────────────────────────────────

def test_common_upstream_two_machines_same_chiller(g):
    r = g.trace_common_upstream(["CNC-01", "CNC-02"])
    first = r["shared_upstream"][:3]
    assert set(ids(first)) == {"ADR-01", "CLT-01", "MCC-1"}
    assert all(u["covers_all"] and u["nearest_depth"] == 1 for u in first)
    assert "CLT-02" not in ids(r["shared_upstream"])


def test_common_upstream_across_lines(g):
    # A열 1호기와 B열 3호기: 칠러는 다르지만 냉각탑과 압축공기는 같다
    r = g.trace_common_upstream(["CNC-01", "CNC-03"])
    shared = ids(r["shared_upstream"])
    assert shared[0] == "ADR-01"            # 둘 다 바로 받는 것
    assert "CT-01" in shared and "TR-1" in shared
    assert "CLT-01" not in shared and "CLT-02" not in shared


def test_common_upstream_needs_two(g):
    with pytest.raises(DataError):
        g.trace_common_upstream(["CNC-01"])


# ── 데이터 검사 ────────────────────────────────────────────────────

def test_unknown_id_in_connections(tmp_path):
    d = write_plant(tmp_path, "equipment_id,name,type\nA,에이,기계\n", "from_id,to_id,kind\nB,A,전원\n")
    with pytest.raises(DataError, match="B"):
        FactoryGraph.from_dir(d)


def test_missing_column(tmp_path):
    d = write_plant(tmp_path, "equipment_id,name\nA,에이\n", "from_id,to_id,kind\n")
    with pytest.raises(DataError, match="type"):
        FactoryGraph.from_dir(d)


def test_duplicate_id(tmp_path):
    d = write_plant(tmp_path, "equipment_id,name,type\nA,에이,기계\nA,에이2,기계\n", "from_id,to_id,kind\nA,A,전원\n")
    with pytest.raises(DataError, match="두 번"):
        FactoryGraph.from_dir(d)


# ── MCP 서버로 불러 보기 ────────────────────────────────────────────

def test_tools_over_mcp(g):
    from mcp import Client

    async def run():
        async with Client(build_server(g)) as c:
            tools = {t.name: t for t in (await c.list_tools()).tools}
            assert set(tools) == {"find_equipment", "get_equipment", "trace_upstream",
                                  "trace_common_upstream", "describe_plant"}
            assert all(t.annotations.read_only_hint for t in tools.values())
            res = await c.call_tool("trace_common_upstream", {"equipment_ids": ["CNC-01", "CNC-02"]})
            assert not res.is_error
            body = res.structured_content or json.loads(res.content[0].text)
            assert "CLT-01" in json.dumps(body, ensure_ascii=False)

    asyncio.run(run())


def test_tool_schemas_are_complete(g):
    """모든 인자에 설명이 있고, 모든 도구에 출력 스키마가 있다(디렉터리 품질 점수의 근거)."""
    from mcp import Client

    async def run():
        async with Client(build_server(g)) as c:
            for t in (await c.list_tools()).tools:
                assert t.description and len(t.description) > 40, t.name
                assert t.output_schema, f"{t.name} 출력 스키마 없음"
                for name, prop in t.input_schema.get("properties", {}).items():
                    assert prop.get("description"), f"{t.name}.{name} 설명 없음"
            bad = await c.call_tool("trace_common_upstream", {"equipment_ids": ["1호기"]})
            assert bad.is_error
            ok = await c.call_tool("describe_plant", {})
            assert ok.structured_content["equipment"] == 13

    asyncio.run(run())
