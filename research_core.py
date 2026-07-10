from __future__ import annotations

import heapq
import itertools
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from PIL import ImageGrab

from hcb import Box, cont, get_hex_neighbors, getids, ids, memo, name_mapping, recognize


class ConfigError(ValueError):
    pass


class ScanError(RuntimeError):
    pass


@dataclass(frozen=True)
class GridSpec:
    x: float
    y: float
    horizontal_spacing: float
    horizontal_count: int
    vertical_spacing: float
    vertical_count: int
    box_size: int

    @classmethod
    def from_values(cls, values: Sequence[float], line_number: int) -> "GridSpec":
        if len(values) != 7:
            raise ConfigError(f"第 {line_number} 行必须包含 7 个数字")
        horizontal_count = int(values[3])
        vertical_count = int(values[5])
        box_size = round(values[6])
        if values[3] != horizontal_count or values[5] != vertical_count:
            raise ConfigError(f"第 {line_number} 行的横向、纵向数量必须是整数")
        if horizontal_count <= 0 or vertical_count <= 0 or box_size <= 0:
            raise ConfigError(f"第 {line_number} 行的数量和方框大小必须大于 0")
        if values[2] <= 0 or values[4] <= 0:
            raise ConfigError(f"第 {line_number} 行的格子间距必须大于 0")
        return cls(
            x=values[0],
            y=values[1],
            horizontal_spacing=values[2],
            horizontal_count=horizontal_count,
            vertical_spacing=values[4],
            vertical_count=vertical_count,
            box_size=box_size,
        )

    def as_values(self) -> Tuple[float, ...]:
        return (
            self.x,
            self.y,
            self.horizontal_spacing,
            self.horizontal_count,
            self.vertical_spacing,
            self.vertical_count,
            self.box_size,
        )


@dataclass(frozen=True)
class ResearchConfig:
    grids: Tuple[GridSpec, GridSpec, GridSpec, GridSpec]

    @classmethod
    def from_text(cls, text: str) -> "ResearchConfig":
        rows = []
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                values = [float(part.strip()) for part in line.split(",")]
            except ValueError as exc:
                raise ConfigError(f"第 {len(rows) + 1} 行存在非数字内容") from exc
            rows.append(GridSpec.from_values(values, len(rows) + 1))
        if len(rows) != 4:
            raise ConfigError(f"坐标配置必须正好包含 4 行，当前为 {len(rows)} 行")
        return cls(tuple(rows))

    @classmethod
    def load(cls, path: Path) -> "ResearchConfig":
        try:
            return cls.from_text(path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise ConfigError(f"无法读取坐标配置：{path}") from exc

    def to_text(self) -> str:
        def render(value: float) -> str:
            return f"{value:g}"

        return "\n".join(",".join(render(value) for value in grid.as_values()) for grid in self.grids) + "\n"

    def save(self, path: Path) -> None:
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(self.to_text(), encoding="utf-8")
        temporary.replace(path)

    def create_boxes(self) -> Tuple[List[Box], List[Box]]:
        research_boxes: List[Box] = []
        source_boxes: List[Box] = []
        for layer, spec in enumerate(self.grids):
            for row_index in range(spec.vertical_count):
                for column_index in range(spec.horizontal_count):
                    x = round(
                        spec.x
                        + column_index * spec.horizontal_spacing
                        - spec.box_size / 2
                        + 32
                    )
                    y = round(
                        spec.y
                        + row_index * spec.vertical_spacing
                        - spec.box_size / 2
                        + 32
                    )
                    if layer == 0:
                        box = Box(x, y, spec.box_size, row_index * 2 + 1, column_index * 2)
                        research_boxes.append(box)
                    elif layer == 1:
                        box = Box(x, y, spec.box_size, row_index * 2, column_index * 2 + 1)
                        research_boxes.append(box)
                    else:
                        source_boxes.append(Box(x, y, spec.box_size))
        return research_boxes, source_boxes


@dataclass(frozen=True)
class Placement:
    aspect_id: int
    source: Box
    target: Box


@dataclass
class ScanResult:
    research_boxes: List[Box]
    source_boxes: List[Box]
    node_boxes: List[Box]
    connections: List[Tuple[List[int], List[int]]]
    placements: List[Placement]
    fixed_count: int
    missing_aspects: List[int] = field(default_factory=list)
    unknown_colors: List[Tuple[int, int, int]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def aspect_name(self, aspect_id: int) -> str:
        internal_name = ids.get(aspect_id, str(aspect_id))
        return name_mapping.get(internal_name, internal_name)


class ResearchScanner:
    def __init__(self, max_path_length: int = 40):
        self.max_path_length = max_path_length
        self.blank_id = getids.get("lj", 1)

    def capture_and_scan(
        self,
        config: ResearchConfig,
        screen_bbox: Optional[Tuple[int, int, int, int]] = None,
    ) -> ScanResult:
        research_boxes, source_boxes = config.create_boxes()
        if screen_bbox is None:
            screen = ImageGrab.grab()
        else:
            try:
                screen = ImageGrab.grab(bbox=screen_bbox, all_screens=True)
            except TypeError:
                screen = ImageGrab.grab(bbox=screen_bbox)
        self._validate_box_bounds(research_boxes + source_boxes, screen.size)

        node_boxes: List[Box] = []
        node_by_position: Dict[Tuple[int, int], int] = {}
        fixed_nodes: List[int] = []
        original_labels: Dict[int, int] = {}
        unknown_colors: Set[Tuple[int, int, int]] = set()

        for box in research_boxes:
            recognition = recognize(self._crop(screen, box))
            box.label = recognition.class_id
            if recognition.unknown and recognition.sampled_color is not None:
                unknown_colors.add(recognition.sampled_color)
            if recognition.class_id == 0:
                continue
            node_id = len(node_boxes)
            node_boxes.append(box)
            node_by_position[(box.row, box.col)] = node_id
            original_labels[node_id] = recognition.class_id
            if recognition.class_id != self.blank_id:
                fixed_nodes.append(node_id)

        available_sources: Dict[int, Box] = {}
        for box in source_boxes:
            recognition = recognize(self._crop(screen, box))
            box.label = recognition.class_id
            if recognition.unknown and recognition.sampled_color is not None:
                unknown_colors.add(recognition.sampled_color)
            if recognition.class_id > self.blank_id:
                available_sources[recognition.class_id] = box

        if not node_boxes:
            raise ScanError("没有识别到研究格，请检查坐标、GUI 缩放和材质包")
        if not fixed_nodes:
            raise ScanError("没有识别到研究盘上的固定要素")

        adjacency = self._build_adjacency(node_boxes, node_by_position)
        warnings: List[str] = []
        if len(fixed_nodes) == 1:
            connections: List[Tuple[List[int], List[int]]] = []
            warnings.append("研究盘上只有一个固定要素，无需连线")
        else:
            try:
                connections = self._plan_connections(original_labels, adjacency, fixed_nodes)
            except ScanError as exc:
                diagnostic = (
                    f"识别到 {len(node_boxes)} 个可用格、{len(fixed_nodes)} 个固定要素、"
                    f"{len(unknown_colors)} 种未知颜色"
                )
                raise ScanError(f"{exc}；{diagnostic}。请先用坐标设置检查绿框是否居中") from exc

        required_by_node: Dict[int, int] = {}
        for grid_path, aspect_path in connections:
            for node_id, aspect_id in zip(grid_path, aspect_path):
                if original_labels[node_id] == self.blank_id:
                    required_by_node.setdefault(node_id, aspect_id)

        missing_aspects = sorted(
            {aspect_id for aspect_id in required_by_node.values() if aspect_id not in available_sources}
        )
        placements = [
            Placement(aspect_id, available_sources[aspect_id], node_boxes[node_id])
            for node_id, aspect_id in required_by_node.items()
            if aspect_id in available_sources
        ]

        if unknown_colors:
            color_samples = "、".join(str(color) for color in sorted(unknown_colors)[:4])
            suffix = "……" if len(unknown_colors) > 4 else ""
            warnings.append(
                f"发现 {len(unknown_colors)} 种未匹配颜色：{color_samples}{suffix}"
            )

        return ScanResult(
            research_boxes=research_boxes,
            source_boxes=source_boxes,
            node_boxes=node_boxes,
            connections=connections,
            placements=placements,
            fixed_count=len(fixed_nodes),
            missing_aspects=missing_aspects,
            unknown_colors=sorted(unknown_colors),
            warnings=warnings,
        )

    @staticmethod
    def _crop(screen, box: Box):
        return screen.crop((box.x, box.y, box.x + box.size, box.y + box.size)).convert("RGB")

    @staticmethod
    def _validate_box_bounds(boxes: Iterable[Box], screen_size: Tuple[int, int]) -> None:
        width, height = screen_size
        invalid = [
            box
            for box in boxes
            if box.x < 0 or box.y < 0 or box.x + box.size > width or box.y + box.size > height
        ]
        if invalid:
            raise ScanError(f"有 {len(invalid)} 个识别框超出屏幕范围，请重新校准坐标")

    @staticmethod
    def _build_adjacency(
        node_boxes: Sequence[Box], node_by_position: Dict[Tuple[int, int], int]
    ) -> List[Set[int]]:
        adjacency: List[Set[int]] = [set() for _ in node_boxes]
        for node_id, box in enumerate(node_boxes):
            for neighbor_position in get_hex_neighbors(box.row, box.col):
                neighbor_id = node_by_position.get(neighbor_position)
                if neighbor_id is not None:
                    adjacency[node_id].add(neighbor_id)
                    adjacency[neighbor_id].add(node_id)
        return adjacency

    def _plan_connections(
        self,
        original_labels: Dict[int, int],
        adjacency: Sequence[Set[int]],
        fixed_nodes: Sequence[int],
    ) -> List[Tuple[List[int], List[int]]]:
        seeds = sorted(fixed_nodes, key=lambda node_id: (len(adjacency[node_id]), node_id))
        last_error = None
        for priority in ("constrained", "cost"):
            for first_node in seeds:
                try:
                    return self._plan_connections_attempt(
                        original_labels,
                        adjacency,
                        fixed_nodes,
                        first_node,
                        priority,
                    )
                except ScanError as exc:
                    last_error = exc
        raise last_error or ScanError("无法生成完整连接方案")

    def _plan_connections_attempt(
        self,
        original_labels: Dict[int, int],
        adjacency: Sequence[Set[int]],
        fixed_nodes: Sequence[int],
        first_node: int,
        priority: str,
    ) -> List[Tuple[List[int], List[int]]]:
        current_labels = dict(original_labels)
        connected: Set[int] = {first_node}
        remaining = set(fixed_nodes) - {first_node}
        connections: List[Tuple[List[int], List[int]]] = []

        while remaining:
            candidates = []
            for target in sorted(remaining):
                connection = self._find_next_connection(
                    connected, target, current_labels, adjacency
                )
                if connection is None:
                    continue
                cost, grid_path, aspect_path = connection
                free_neighbors = sum(
                    neighbor not in connected for neighbor in adjacency[target]
                )
                if priority == "constrained":
                    sort_key = (free_neighbors, cost, len(grid_path), target)
                else:
                    sort_key = (cost, free_neighbors, len(grid_path), target)
                candidates.append(
                    (sort_key, target, grid_path, aspect_path)
                )

            if not candidates:
                unresolved = ", ".join(
                    self._aspect_name(original_labels[node_id]) for node_id in sorted(remaining)
                )
                raise ScanError(f"无法生成完整连接方案，未连接要素：{unresolved}")

            _, target, grid_path, aspect_path = min(candidates)
            connections.append((grid_path, aspect_path))
            for node_id, aspect_id in zip(grid_path, aspect_path):
                if current_labels[node_id] == self.blank_id:
                    current_labels[node_id] = aspect_id
                connected.add(node_id)
            remaining.remove(target)

        return connections

    def _find_next_connection(
        self,
        connected: Set[int],
        target: int,
        current_labels: Dict[int, int],
        adjacency: Sequence[Set[int]],
    ) -> Optional[Tuple[float, List[int], List[int]]]:
        """在格子和要素的联合状态上搜索到指定固定要素的最低消耗连接。"""
        serial = itertools.count()
        queue = []
        best: Dict[Tuple[int, int], Tuple[float, int]] = {}

        for start in sorted(connected):
            aspect_id = current_labels[start]
            state = (start, aspect_id)
            best[state] = (0.0, 0)
            heapq.heappush(
                queue,
                (0.0, 0, next(serial), start, aspect_id, [start], [aspect_id]),
            )

        while queue:
            cost, steps, _, node_id, aspect_id, grid_path, aspect_path = heapq.heappop(queue)
            if (cost, steps) != best.get((node_id, aspect_id)):
                continue
            if steps >= self.max_path_length:
                continue

            for neighbor in sorted(adjacency[node_id]):
                if neighbor in connected or neighbor in grid_path:
                    continue

                neighbor_label = current_labels[neighbor]
                if neighbor_label != self.blank_id:
                    if neighbor == target and neighbor_label in cont.get(aspect_id, set()):
                        return cost, grid_path + [neighbor], aspect_path + [neighbor_label]
                    continue

                for next_aspect in sorted(cont.get(aspect_id, set())):
                    material_cost = memo.get(next_aspect, math.inf)
                    if math.isinf(material_cost):
                        continue
                    next_cost = cost + material_cost
                    next_steps = steps + 1
                    state = (neighbor, next_aspect)
                    metric = (next_cost, next_steps)
                    if metric >= best.get(state, (math.inf, self.max_path_length + 1)):
                        continue
                    best[state] = metric
                    heapq.heappush(
                        queue,
                        (
                            next_cost,
                            next_steps,
                            next(serial),
                            neighbor,
                            next_aspect,
                            grid_path + [neighbor],
                            aspect_path + [next_aspect],
                        ),
                    )
        return None

    @staticmethod
    def _aspect_name(aspect_id: int) -> str:
        internal_name = ids.get(aspect_id, str(aspect_id))
        return name_mapping.get(internal_name, internal_name)
