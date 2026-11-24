"""설비 연결 그래프 — 설비 대장과 연결 테이블을 읽어 상류를 따라간다.

MCP에 의존하지 않는 순수 파이썬이다. 서버(server.py)는 이 모듈을 감싸기만 한다.

용어
  상류(upstream)   : 어떤 설비에 무언가(전원, 냉각수, 압축공기 …)를 공급하는 쪽
  하류(downstream) : 공급받는 쪽
  연결(edge)       : connections.csv 의 한 행. from_id 가 to_id 에 kind 를 공급한다
"""

from __future__ import annotations

import csv
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path


class DataError(ValueError):
    """데이터 파일이 비었거나, 열이 없거나, 없는 설비를 가리킬 때."""


@dataclass(frozen=True)
class Equipment:
    equipment_id: str
    name: str
    type: str
    aliases: tuple[str, ...] = ()
    location: str = ""
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "equipment_id": self.equipment_id,
            "name": self.name,
            "type": self.type,
            "aliases": list(self.aliases),
            "location": self.location,
            "note": self.note,
        }


@dataclass(frozen=True)
class Connection:
    from_id: str
    to_id: str
    kind: str
    note: str = ""

    def to_dict(self) -> dict:
        return {"from_id": self.from_id, "to_id": self.to_id, "kind": self.kind, "note": self.note}


@dataclass
class FactoryGraph:
    equipment: dict[str, Equipment]
    connections: list[Connection]
    _up: dict[str, list[Connection]] = field(default_factory=dict, repr=False)
    _down: dict[str, list[Connection]] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        unknown = sorted(
            {c.from_id for c in self.connections if c.from_id not in self.equipment}
            | {c.to_id for c in self.connections if c.to_id not in self.equipment}
        )
        if unknown:
            raise DataError(f"connections.csv 가 설비 대장에 없는 설비를 가리킵니다: {', '.join(unknown)}")
        for c in self.connections:
            self._up.setdefault(c.to_id, []).append(c)
            self._down.setdefault(c.from_id, []).append(c)

    # ── 읽기 ──────────────────────────────────────────────────────────
    @classmethod
    def from_dir(cls, data_dir: str | Path) -> "FactoryGraph":
        d = Path(data_dir)
        eq_rows = _read_csv(d / "equipment.csv", required=("equipment_id", "name", "type"))
        cn_rows = _read_csv(d / "connections.csv", required=("from_id", "to_id", "kind"))
        equipment: dict[str, Equipment] = {}
        for r in eq_rows:
            eid = r["equipment_id"].strip()
            if eid in equipment:
                raise DataError(f"equipment.csv 에 같은 설비 번호가 두 번 있습니다: {eid}")
            aliases = tuple(a.strip() for a in (r.get("aliases") or "").split("|") if a.strip())
            equipment[eid] = Equipment(
                eid, r["name"].strip(), r["type"].strip(), aliases,
                (r.get("location") or "").strip(), (r.get("note") or "").strip(),
            )
        connections = [
            Connection(r["from_id"].strip(), r["to_id"].strip(), r["kind"].strip(), (r.get("note") or "").strip())
            for r in cn_rows
        ]
        return cls(equipment, connections)

    # ── 조회 ──────────────────────────────────────────────────────────
    def find(self, query: str, limit: int = 10) -> list[dict]:
        """번호, 이름, 별칭, 종류에서 query 를 찾는다. 정확히 맞는 것을 앞에 둔다."""
        q = query.strip().lower()
        if not q:
            return []
        scored = []
        for e in self.equipment.values():
            fields = [e.equipment_id, e.name, *e.aliases]
            texts = [f.lower() for f in fields]
            if q in texts:
                score = 0
            elif any(q in t for t in texts):
                score = 1
            elif q in e.type.lower():
                score = 2
            else:
                continue
            scored.append((score, e.equipment_id, e))
        scored.sort(key=lambda x: (x[0], x[1]))
        return [e.to_dict() for _, _, e in scored[:limit]]

    def get(self, equipment_id: str) -> dict:
        e = self._require(equipment_id)
        return {
            **e.to_dict(),
            "receives_from": [c.to_dict() for c in self._up.get(e.equipment_id, [])],
            "supplies_to": [c.to_dict() for c in self._down.get(e.equipment_id, [])],
        }

    def upstream(self, equipment_id: str, max_depth: int = 5, kinds: list[str] | None = None) -> dict:
        """equipment_id 에서 출발해 공급하는 쪽으로 거슬러 올라간다 (너비 우선 탐색).

        이미 본 설비는 다시 올라가지 않는다. 서로 주고받는 연결(순환)이 있어도 끝난다.
        결과의 path 는 출발 설비까지 내려오는 길이다: [가장 먼 설비, …, 출발 설비].
        """
        start = self._require(equipment_id).equipment_id
        kind_set = {k.strip() for k in kinds} if kinds else None
        seen = {start}
        # (설비, 깊이, 출발 설비까지 가는 연결 목록)
        queue: deque[tuple[str, int, list[Connection]]] = deque([(start, 0, [])])
        found: list[dict] = []
        cycles: list[str] = []
        while queue:
            node, depth, via = queue.popleft()
            if depth >= max_depth:
                continue
            for c in self._up.get(node, []):
                if kind_set and c.kind not in kind_set:
                    continue
                route = [c, *via]
                if c.from_id in seen:
                    if c.from_id == start or any(v.to_id == c.from_id for v in via):
                        cycles.append(f"{c.from_id} → {node} ({c.kind})")
                    continue
                seen.add(c.from_id)
                found.append({
                    **self.equipment[c.from_id].to_dict(),
                    "depth": depth + 1,
                    "supplies": c.kind,
                    "path": _path_text(route),
                })
                queue.append((c.from_id, depth + 1, route))
        return {
            "start": self.equipment[start].to_dict(),
            "max_depth": max_depth,
            "kinds": sorted(kind_set) if kind_set else None,
            "upstream": found,
            "cycles_skipped": cycles,
        }

    def common_upstream(self, equipment_ids: list[str], max_depth: int = 5, kinds: list[str] | None = None) -> dict:
        """여러 설비에 동시에 이상이 있을 때, 그 설비들이 함께 쓰는 상류를 묶는다.

        둘 이상이 함께 쓰는 상류만 돌려주고, 많이 겹칠수록·가까울수록 앞에 둔다.
        """
        ids = list(dict.fromkeys(i.strip() for i in equipment_ids if i.strip()))
        if len(ids) < 2:
            raise DataError("설비를 두 대 이상 주세요. 한 대면 trace_upstream 을 쓰면 됩니다.")
        starts = [self._require(i).equipment_id for i in ids]
        reach: dict[str, dict[str, int]] = {}  # 상류 설비 → {출발 설비: 깊이}
        for s in starts:
            for u in self.upstream(s, max_depth, kinds)["upstream"]:
                reach.setdefault(u["equipment_id"], {})[s] = u["depth"]
        shared = []
        for uid, by_start in reach.items():
            if len(by_start) < 2:
                continue
            shared.append({
                **self.equipment[uid].to_dict(),
                "covers": sorted(by_start),
                "covers_all": len(by_start) == len(starts),
                "nearest_depth": min(by_start.values()),
            })
        shared.sort(key=lambda x: (-len(x["covers"]), x["nearest_depth"], x["equipment_id"]))
        return {"equipment_ids": starts, "max_depth": max_depth, "shared_upstream": shared}

    def summary(self) -> dict:
        kinds: dict[str, int] = {}
        for c in self.connections:
            kinds[c.kind] = kinds.get(c.kind, 0) + 1
        types: dict[str, int] = {}
        for e in self.equipment.values():
            types[e.type] = types.get(e.type, 0) + 1
        return {"equipment": len(self.equipment), "connections": len(self.connections),
                "equipment_types": types, "connection_kinds": kinds}

    def _require(self, equipment_id: str) -> Equipment:
        key = equipment_id.strip()
        if key in self.equipment:
            return self.equipment[key]
        hits = self.find(key, limit=1)
        if hits and (key in hits[0]["aliases"] or key == hits[0]["name"]):
            return self.equipment[hits[0]["equipment_id"]]
        raise DataError(f"설비를 찾을 수 없습니다: {equipment_id!r}. find_equipment 로 번호를 먼저 찾아보세요.")


def _path_text(route: list[Connection]) -> str:
    """[CT-01→CLT-01, CLT-01→CNC-01] → 'CT-01 —냉각수→ CLT-01 —절삭유 냉각수→ CNC-01'"""
    if not route:
        return ""
    parts = [route[0].from_id]
    for c in route:
        parts.append(f"—{c.kind}→ {c.to_id}")
    return " ".join(parts)


def _read_csv(path: Path, required: tuple[str, ...]) -> list[dict]:
    if not path.is_file():
        raise DataError(f"파일이 없습니다: {path}")
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        cols = set(reader.fieldnames or [])
        missing = [c for c in required if c not in cols]
        if missing:
            raise DataError(f"{path.name} 에 열이 없습니다: {', '.join(missing)}")
        rows = [r for r in reader if any((v or "").strip() for v in r.values())]
    if not rows:
        raise DataError(f"{path.name} 에 행이 없습니다.")
    return rows
