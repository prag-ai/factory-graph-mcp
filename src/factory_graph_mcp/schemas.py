"""도구가 돌려주는 값의 모양. MCP 클라이언트에 출력 스키마(outputSchema)로 알려진다.

graph.py 가 만드는 dict 와 필드가 같아야 한다(tests/test_graph.py 가 확인한다).
"""

from __future__ import annotations

from typing import Optional

from typing_extensions import TypedDict  # Python 3.10 에서 pydantic 이 읽으려면 typing_extensions 쪽


class Equipment(TypedDict):
    equipment_id: str
    """설비 번호. 다른 도구에 넘길 때 이 값을 쓴다. 예: CNC-01"""
    name: str
    """설비 이름. 예: 머시닝 센터 1호기"""
    type: str
    """설비 종류. 예: 절삭유 칠러"""
    aliases: list[str]
    """현장에서 부르는 이름. 예: ["1호기", "머시닝1"]"""
    location: str
    """위치. 없으면 빈 문자열"""
    note: str
    """메모. 없으면 빈 문자열"""


class Connection(TypedDict):
    from_id: str
    """공급하는 설비 번호"""
    to_id: str
    """공급받는 설비 번호"""
    kind: str
    """무엇을 공급하는가. 예: 전원, 냉각수, 압축공기"""
    note: str
    """메모. 없으면 빈 문자열"""


class EquipmentDetail(Equipment):
    receives_from: list[Connection]
    """이 설비가 공급받는 연결(바로 위 상류)"""
    supplies_to: list[Connection]
    """이 설비가 공급하는 연결(바로 아래 하류)"""


class UpstreamEquipment(Equipment):
    depth: int
    """출발 설비에서 몇 단계 위인가. 1 = 바로 공급하는 설비"""
    supplies: str
    """이 설비가 아래 설비에 보내는 것(연결 종류)"""
    path: str
    """이 설비에서 출발 설비까지 흘러오는 길. 예: CT-01 —냉각수→ CLT-01 —절삭유 냉각수→ CNC-01"""


class UpstreamResult(TypedDict):
    start: Equipment
    """출발 설비"""
    max_depth: int
    """따라 올라간 최대 단계"""
    kinds: Optional[list[str]]
    """좁힌 연결 종류. 좁히지 않았으면 null"""
    upstream: list[UpstreamEquipment]
    """상류 설비. 가까운 것(depth 가 작은 것)부터"""
    cycles_skipped: list[str]
    """서로 주고받는 연결이라 다시 따라가지 않은 곳. 예: CNC-01 → TCU-01 (전원)"""


class SharedUpstream(Equipment):
    covers: list[str]
    """이 상류를 함께 쓰는 설비 번호(준 설비 중)"""
    covers_all: bool
    """준 설비 전부가 이 상류를 쓰면 true"""
    nearest_depth: int
    """준 설비 중 가장 가까운 것에서 몇 단계 위인가"""


class CommonUpstreamResult(TypedDict):
    equipment_ids: list[str]
    """설비 번호로 바꾼 입력 설비"""
    max_depth: int
    """따라 올라간 최대 단계"""
    shared_upstream: list[SharedUpstream]
    """두 대 이상이 함께 쓰는 상류. 많이 덮을수록, 가까울수록 앞"""


class PlantSummary(TypedDict):
    equipment: int
    """설비 수"""
    connections: int
    """연결 수"""
    equipment_types: dict[str, int]
    """설비 종류별 대수"""
    connection_kinds: dict[str, int]
    """연결 종류별 개수. trace_upstream·trace_common_upstream 의 kinds 에 넣을 수 있는 값"""
