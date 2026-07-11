from __future__ import annotations

import heapq
import itertools
import json
import math
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from PIL import Image, ImageGrab

from hcb import Box, cont, getids, ids, memo, name_mapping, recognize, ys


class ConfigError(ValueError):
    pass


class ScanError(RuntimeError):
    pass


@dataclass(frozen=True)
class WorkRegion:
    """相对于当前所选屏幕的工作区域。"""

    x: int
    y: int
    width: int
    height: int

    @classmethod
    def full_screen(cls, screen_size: Tuple[int, int]) -> "WorkRegion":
        return cls(0, 0, max(1, screen_size[0]), max(1, screen_size[1]))

    @classmethod
    def load(cls, path: Path, screen_size: Tuple[int, int]) -> "WorkRegion":
        if not path.exists():
            return cls.full_screen(screen_size)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            region = cls(
                int(data["x"]),
                int(data["y"]),
                int(data["width"]),
                int(data["height"]),
            )
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            raise ConfigError(f"无法读取工作区域配置：{path}") from exc
        return region.clamped(screen_size)

    def clamped(self, screen_size: Tuple[int, int]) -> "WorkRegion":
        screen_width, screen_height = screen_size
        if self.width <= 0 or self.height <= 0:
            raise ConfigError("工作区域的宽度和高度必须大于 0")
        x = min(max(0, self.x), max(0, screen_width - 1))
        y = min(max(0, self.y), max(0, screen_height - 1))
        width = min(self.width, screen_width - x)
        height = min(self.height, screen_height - y)
        if width < 240 or height < 180:
            raise ConfigError("工作区域太小，请重新拖动红框并覆盖完整研究界面")
        return WorkRegion(x, y, width, height)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(
                {
                    "x": self.x,
                    "y": self.y,
                    "width": self.width,
                    "height": self.height,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)


@dataclass(frozen=True)
class _ColorComponent:
    color: Tuple[int, int, int]
    class_id: int
    left: int
    top: int
    right: int
    bottom: int
    area: int

    @property
    def width(self) -> int:
        return self.right - self.left + 1

    @property
    def height(self) -> int:
        return self.bottom - self.top + 1

    @property
    def center(self) -> Tuple[float, float]:
        return ((self.left + self.right) / 2, (self.top + self.bottom) / 2)


@dataclass
class DetectedLayout:
    research_boxes: List[Box]
    source_boxes: List[Box]
    tile_size: int = 64
    sample_size: int = 24
    unknown_colors: List[Tuple[int, int, int]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    source_panel_count: int = 0


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
    """从截图自动定位研究盘和可用元素，并计算连接方案。"""

    def __init__(self, max_path_length: int = 40):
        self.max_path_length = max_path_length
        self.blank_id = getids.get("lj", 1)

    def capture_and_calibrate(
        self,
        region: WorkRegion,
        screen_bbox: Optional[Tuple[int, int, int, int]] = None,
    ) -> DetectedLayout:
        image, actual_region = self._capture_region(region, screen_bbox)
        return self.detect_layout(image, actual_region)

    def capture_and_scan(
        self,
        region: WorkRegion,
        screen_bbox: Optional[Tuple[int, int, int, int]] = None,
    ) -> ScanResult:
        image, actual_region = self._capture_region(region, screen_bbox)
        layout = self.detect_layout(image, actual_region)
        return self._scan_layout(layout)

    def detect_layout(
        self,
        image: Image.Image,
        region: Optional[WorkRegion] = None,
    ) -> DetectedLayout:
        """检测一张已截取图片。该入口也用于离线截图回归测试。"""
        image = image.convert("RGB")
        if region is None:
            region = WorkRegion.full_screen(image.size)
        if image.size != (region.width, region.height):
            raise ScanError("自动标定图片尺寸与工作区域不一致")

        components = self._find_known_color_components(image)
        tile_size = self._estimate_tile_size(components, image.size)
        sample_size = max(6, round(tile_size * 0.375))
        large_components = [
            component
            for component in components
            if tile_size * 0.70 <= component.width <= tile_size * 1.25
            and tile_size * 0.70 <= component.height <= tile_size * 1.25
            and component.area >= tile_size * tile_size * 0.16
        ]
        panels = self._find_source_panels(large_components, tile_size, image)
        if not panels:
            raise ScanError(
                "未识别到元素列表。请让红框覆盖完整研究界面，并确认专用材质包已启用"
            )

        source_boxes, source_unknown = self._build_source_boxes(
            image, panels, region, sample_size
        )
        research_boxes, research_unknown = self._build_research_boxes(
            image,
            components,
            large_components,
            panels,
            region,
            tile_size,
            sample_size,
        )
        if len(research_boxes) < 3:
            raise ScanError(
                "未识别到研究盘网格。请重新拖动红框，确保研究盘和左右元素列表都在框内"
            )

        warnings: List[str] = []
        if len(panels) == 1:
            warnings.append("只识别到一侧元素列表；仍会使用当前可见元素")
        known_source_count = sum(box.label is not None and box.label > self.blank_id for box in source_boxes)
        if known_source_count == 0:
            raise ScanError("元素列表已定位，但没有识别到已知元素；请检查材质包和界面缩放")

        unknown_colors = sorted(source_unknown | research_unknown)
        if unknown_colors:
            warnings.append(f"发现 {len(unknown_colors)} 种未收录颜色，新元素将被安全跳过")

        return DetectedLayout(
            research_boxes=research_boxes,
            source_boxes=source_boxes,
            tile_size=tile_size,
            sample_size=sample_size,
            unknown_colors=unknown_colors,
            warnings=warnings,
            source_panel_count=len(panels),
        )

    def _capture_region(
        self,
        region: WorkRegion,
        screen_bbox: Optional[Tuple[int, int, int, int]],
    ) -> Tuple[Image.Image, WorkRegion]:
        if screen_bbox is None:
            screen = ImageGrab.grab()
            actual_region = region.clamped(screen.size)
            crop_box = (
                actual_region.x,
                actual_region.y,
                actual_region.x + actual_region.width,
                actual_region.y + actual_region.height,
            )
            return screen.crop(crop_box).convert("RGB"), actual_region

        left, top, right, bottom = screen_bbox
        actual_region = region.clamped((right - left, bottom - top))
        absolute_bbox = (
            left + actual_region.x,
            top + actual_region.y,
            left + actual_region.x + actual_region.width,
            top + actual_region.y + actual_region.height,
        )
        try:
            screen = ImageGrab.grab(bbox=absolute_bbox, all_screens=True)
        except TypeError:
            screen = ImageGrab.grab(bbox=absolute_bbox)
        return screen.convert("RGB"), actual_region

    def _find_known_color_components(self, image: Image.Image) -> List[_ColorComponent]:
        width, height = image.size
        pixels = image.load()
        visited = bytearray(width * height)
        known_colors = set(ys)
        components: List[_ColorComponent] = []

        for y in range(height):
            row_offset = y * width
            for x in range(width):
                start_index = row_offset + x
                if visited[start_index]:
                    continue
                color = pixels[x, y]
                if color not in known_colors:
                    continue

                stack = [(x, y)]
                visited[start_index] = 1
                left = right = x
                top = bottom = y
                area = 0
                while stack:
                    current_x, current_y = stack.pop()
                    area += 1
                    left = min(left, current_x)
                    right = max(right, current_x)
                    top = min(top, current_y)
                    bottom = max(bottom, current_y)
                    for next_x, next_y in (
                        (current_x - 1, current_y),
                        (current_x + 1, current_y),
                        (current_x, current_y - 1),
                        (current_x, current_y + 1),
                    ):
                        if next_x < 0 or next_y < 0 or next_x >= width or next_y >= height:
                            continue
                        index = next_y * width + next_x
                        if visited[index] or pixels[next_x, next_y] != color:
                            continue
                        visited[index] = 1
                        stack.append((next_x, next_y))

                if area >= 8:
                    aspect_name = ys[color]
                    components.append(
                        _ColorComponent(
                            color,
                            getids.get(aspect_name, 0),
                            left,
                            top,
                            right,
                            bottom,
                            area,
                        )
                    )
        return components

    @staticmethod
    def _cluster_values(values: Iterable[float], tolerance: float = 5.0) -> List[List[float]]:
        clusters: List[List[float]] = []
        for value in sorted(values):
            if clusters and abs(value - statistics.mean(clusters[-1])) <= tolerance:
                clusters[-1].append(value)
            else:
                clusters.append([value])
        return clusters

    def _estimate_tile_size(
        self,
        components: Sequence[_ColorComponent],
        image_size: Tuple[int, int],
    ) -> int:
        """从元素底色块估算当前 Minecraft GUI 缩放后的格子尺寸。"""
        maximum = min(120, max(24, image_size[1] // 3))
        sizes = []
        for component in components:
            if not (10 <= component.width <= maximum and 10 <= component.height <= maximum):
                continue
            ratio = component.width / component.height
            size = (component.width + component.height) / 2
            if not 0.72 <= ratio <= 1.38:
                continue
            if component.area < size * size * 0.14:
                continue
            sizes.append(size)
        if not sizes:
            raise ScanError("无法估算界面缩放比例，请确认材质包已启用并扩大工作区域")

        clusters: List[List[float]] = []
        for size in sorted(sizes):
            if clusters and abs(size - statistics.mean(clusters[-1])) <= max(
                2.5, statistics.mean(clusters[-1]) * 0.10
            ):
                clusters[-1].append(size)
            else:
                clusters.append([size])
        viable = [cluster for cluster in clusters if len(cluster) >= 3]
        if not viable:
            raise ScanError("识别到的元素色块太少，无法确定界面缩放比例")
        best = max(
            viable,
            key=lambda cluster: len(cluster) * math.sqrt(statistics.median(cluster)),
        )
        return max(16, round(statistics.median(best)))

    def _find_source_panels(
        self,
        large_components: Sequence[_ColorComponent],
        tile_size: int,
        image: Image.Image,
    ) -> List[Tuple[List[int], List[int]]]:
        cluster_tolerance = max(3.0, tile_size * 0.10)
        x_clusters = self._cluster_values(
            (component.center[0] for component in large_components), cluster_tolerance
        )
        columns = []
        for cluster in x_clusters:
            center = round(statistics.mean(cluster))
            members = [
                component
                for component in large_components
                if abs(component.center[0] - center) <= cluster_tolerance + 1
            ]
            if len(members) >= 3:
                columns.append((center, members))

        column_groups: List[List[Tuple[int, List[_ColorComponent]]]] = []
        for column in columns:
            if (
                column_groups
                and tile_size * 0.68
                <= column[0] - column_groups[-1][-1][0]
                <= tile_size * 1.32
            ):
                column_groups[-1].append(column)
            else:
                column_groups.append([column])

        panels: List[Tuple[List[int], List[int]]] = []
        for group in column_groups:
            if len(group) < 2:
                continue
            if sum(len(column[1]) for column in group) < max(8, len(group) * 2):
                continue
            x_centers = [column[0] for column in group]
            y_values = [component.center[1] for _, members in group for component in members]
            y_clusters = self._cluster_values(y_values, cluster_tolerance)
            y_centers = [round(statistics.mean(cluster)) for cluster in y_clusters]
            y_centers = self._regular_centers(y_centers, tile_size)
            y_centers = self._expand_source_rows(
                image, x_centers, y_centers, tile_size
            )
            if len(y_centers) >= 3:
                panels.append((x_centers, y_centers))
        # 左右列表的行高相同。某一整行若只有自定义纹理，另一侧识别出的行仍可补齐它。
        if len(panels) >= 2:
            shared_rows = [row for _, rows in panels for row in rows]
            shared_rows = [
                round(statistics.mean(cluster))
                for cluster in self._cluster_values(shared_rows)
            ]
            shared_rows = self._regular_centers(shared_rows, tile_size)
            shared_rows = sorted(
                {
                    row
                    for columns, rows in panels
                    for row in self._expand_source_rows(
                        image, columns, shared_rows or rows, tile_size
                    )
                }
            )
            panels = [(columns, shared_rows) for columns, _ in panels]
        return panels

    @staticmethod
    def _regular_centers(values: Sequence[int], spacing: int) -> List[int]:
        """保留同一网格相位的行，并自动补齐中间缺失行。"""
        values = sorted(set(values))
        if len(values) < 2:
            return values
        tolerance = max(3.0, spacing * 0.15)
        best_anchor = values[0]
        best_values: List[int] = []
        for anchor in values:
            aligned = []
            for value in values:
                steps = round((value - anchor) / spacing)
                if abs(value - (anchor + steps * spacing)) <= tolerance:
                    aligned.append(value)
            if len(aligned) > len(best_values):
                best_anchor = anchor
                best_values = aligned
        if len(best_values) < 2:
            return values
        indices = [round((value - best_anchor) / spacing) for value in best_values]
        return [
            round(best_anchor + index * spacing)
            for index in range(min(indices), max(indices) + 1)
        ]

    def _expand_source_rows(
        self,
        image: Image.Image,
        x_centers: Sequence[int],
        rows: Sequence[int],
        spacing: int,
    ) -> List[int]:
        if not rows:
            return []
        result = sorted(set(rows))
        # 最多向两端各探索四行。它能覆盖新增元素，同时避免把界面外背景当成无限列表。
        for direction in (-1, 1):
            current = result[0] if direction < 0 else result[-1]
            additions = []
            for _ in range(4):
                candidate = current + direction * spacing
                if candidate < spacing // 3 or candidate >= image.height - spacing // 3:
                    break
                if not self._row_looks_like_source(image, x_centers, candidate, spacing):
                    break
                additions.append(candidate)
                current = candidate
            result.extend(additions)
            result.sort()
        return result

    @staticmethod
    def _row_looks_like_source(
        image: Image.Image,
        x_centers: Sequence[int],
        center_y: int,
        spacing: int,
    ) -> bool:
        radius = max(4, round(spacing * 0.34))
        active_cells = 0
        required = max(1, math.ceil(len(x_centers) * 0.45))
        for center_x in x_centers:
            crop = image.crop(
                (
                    max(0, center_x - radius),
                    max(0, center_y - radius),
                    min(image.width, center_x + radius),
                    min(image.height, center_y + radius),
                )
            ).convert("RGB")
            colors: Dict[Tuple[int, int, int], int] = {}
            total = max(1, crop.width * crop.height)
            for color in crop.getdata():
                if max(color) <= 28:
                    continue
                colors[color] = colors.get(color, 0) + 1
            dominant = max(colors.values(), default=0)
            if dominant / total >= 0.10:
                active_cells += 1
        return active_cells >= required

    @staticmethod
    def _fill_regular_centers(values: Sequence[int]) -> List[int]:
        values = sorted(set(values))
        if len(values) < 2:
            return list(values)
        gaps = [right - left for left, right in zip(values, values[1:]) if 45 <= right - left <= 80]
        if not gaps:
            return list(values)
        spacing = round(statistics.median(gaps))
        result = [values[0]]
        for value in values[1:]:
            gap = value - result[-1]
            missing = round(gap / spacing)
            if missing > 1 and abs(gap / missing - spacing) <= 5:
                result.extend(result[-1] + spacing * index for index in range(1, missing))
            result.append(value)
        return sorted(set(result))

    def _build_source_boxes(
        self,
        image: Image.Image,
        panels: Sequence[Tuple[List[int], List[int]]],
        region: WorkRegion,
        sample_size: int,
    ) -> Tuple[List[Box], Set[Tuple[int, int, int]]]:
        boxes: List[Box] = []
        unknown_colors: Set[Tuple[int, int, int]] = set()
        for x_centers, y_centers in panels:
            for y in y_centers:
                for x in x_centers:
                    local_box = self._centered_box(x, y, sample_size)
                    recognition = recognize(self._crop(image, local_box))
                    box = self._offset_box(local_box, region)
                    box.label = recognition.class_id
                    boxes.append(box)
                    if recognition.unknown and recognition.sampled_color is not None:
                        unknown_colors.add(recognition.sampled_color)
        return boxes, unknown_colors

    def _build_research_boxes(
        self,
        image: Image.Image,
        components: Sequence[_ColorComponent],
        large_components: Sequence[_ColorComponent],
        panels: Sequence[Tuple[List[int], List[int]]],
        region: WorkRegion,
        tile_size: int,
        sample_size: int,
    ) -> Tuple[List[Box], Set[Tuple[int, int, int]]]:
        panel_columns = [x for columns, _ in panels for x in columns]
        panel_edges = sorted(
            (min(columns), max(columns)) for columns, _ in panels if columns
        )
        if len(panel_edges) >= 2:
            central_left = panel_edges[0][1] + tile_size * 0.55
            central_right = panel_edges[-1][0] - tile_size * 0.55
        else:
            central_left = image.width * 0.22
            central_right = image.width * 0.78

        candidates: List[Tuple[float, float]] = []
        for component in components:
            center_x, center_y = component.center
            is_blank = (
                component.class_id == self.blank_id
                and tile_size * 0.12 <= component.width <= tile_size * 0.46
                and tile_size * 0.12 <= component.height <= tile_size * 0.46
                and component.area >= tile_size * tile_size * 0.014
            )
            is_large_aspect = component in large_components
            if not (is_blank or is_large_aspect):
                continue
            if not central_left <= center_x <= central_right:
                continue
            if any(abs(center_x - column_x) <= tile_size * 0.13 for column_x in panel_columns):
                continue
            candidates.append((center_x, center_y))

        centers = self._deduplicate_centers(candidates, max(5.0, tile_size * 0.16))
        centers = self._largest_hex_component(centers, tile_size)
        boxes: List[Box] = []
        unknown_colors: Set[Tuple[int, int, int]] = set()
        for center_x, center_y in sorted(centers, key=lambda point: (point[1], point[0])):
            local_box = self._centered_box(center_x, center_y, sample_size)
            recognition = recognize(self._crop(image, local_box))
            if recognition.class_id == 0:
                continue
            box = self._offset_box(local_box, region)
            box.label = recognition.class_id
            boxes.append(box)
            if recognition.unknown and recognition.sampled_color is not None:
                unknown_colors.add(recognition.sampled_color)
        return boxes, unknown_colors

    @staticmethod
    def _deduplicate_centers(
        points: Sequence[Tuple[float, float]], minimum_distance: float
    ) -> List[Tuple[float, float]]:
        result: List[Tuple[float, float]] = []
        for point in sorted(points, key=lambda item: (item[1], item[0])):
            if any(math.dist(point, existing) < minimum_distance for existing in result):
                continue
            result.append(point)
        return result

    @staticmethod
    def _largest_hex_component(
        points: Sequence[Tuple[float, float]], tile_size: int
    ) -> List[Tuple[float, float]]:
        if len(points) < 3:
            return list(points)
        rough_edges: List[Set[int]] = [set() for _ in points]
        neighbor_distances = []
        for left in range(len(points)):
            for right in range(left + 1, len(points)):
                distance = math.dist(points[left], points[right])
                if tile_size * 0.72 <= distance <= tile_size * 1.22:
                    rough_edges[left].add(right)
                    rough_edges[right].add(left)
                    neighbor_distances.append(distance)
        if not neighbor_distances:
            return []
        step = statistics.median(neighbor_distances)
        tolerance = max(2.0, step * 0.13)
        edges: List[Set[int]] = [set() for _ in points]
        for left in range(len(points)):
            for right in rough_edges[left]:
                if abs(math.dist(points[left], points[right]) - step) <= tolerance:
                    edges[left].add(right)

        groups: List[Set[int]] = []
        unseen = set(range(len(points)))
        while unseen:
            start = unseen.pop()
            group = {start}
            stack = [start]
            while stack:
                current = stack.pop()
                for neighbor in edges[current]:
                    if neighbor in unseen:
                        unseen.remove(neighbor)
                        group.add(neighbor)
                        stack.append(neighbor)
            groups.append(group)
        best = max(groups, key=len)
        return [points[index] for index in sorted(best)] if len(best) >= 3 else []

    def _scan_layout(self, layout: DetectedLayout) -> ScanResult:
        node_boxes = [box for box in layout.research_boxes if box.label and box.label > 0]
        fixed_nodes = [
            node_id for node_id, box in enumerate(node_boxes) if box.label != self.blank_id
        ]
        original_labels = {node_id: box.label for node_id, box in enumerate(node_boxes)}
        if not node_boxes:
            raise ScanError("没有识别到研究格，请检查红框范围、GUI 缩放和材质包")
        if not fixed_nodes:
            raise ScanError("没有识别到研究盘上的固定元素")

        available_sources: Dict[int, Box] = {}
        for box in layout.source_boxes:
            if box.label is not None and box.label > self.blank_id:
                available_sources.setdefault(box.label, box)

        adjacency = self._build_adjacency(node_boxes, layout.tile_size)
        warnings = list(layout.warnings)
        if len(fixed_nodes) == 1:
            connections: List[Tuple[List[int], List[int]]] = []
            warnings.append("研究盘上只有一个固定元素，无需连线")
        else:
            try:
                connections = self._plan_connections(original_labels, adjacency, fixed_nodes)
            except ScanError as exc:
                raise ScanError(
                    f"{exc}。自动标定识别到 {len(node_boxes)} 个研究格、"
                    f"{len(fixed_nodes)} 个固定元素，请在坐标设置中检查绿框"
                ) from exc

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
        return ScanResult(
            research_boxes=layout.research_boxes,
            source_boxes=layout.source_boxes,
            node_boxes=node_boxes,
            connections=connections,
            placements=placements,
            fixed_count=len(fixed_nodes),
            missing_aspects=missing_aspects,
            unknown_colors=layout.unknown_colors,
            warnings=warnings,
        )

    @staticmethod
    def _centered_box(center_x: float, center_y: float, sample_size: int) -> Box:
        half = sample_size // 2
        return Box(round(center_x) - half, round(center_y) - half, sample_size)

    @staticmethod
    def _offset_box(box: Box, region: WorkRegion) -> Box:
        result = Box(box.x + region.x, box.y + region.y, box.size)
        result.label = box.label
        return result

    @staticmethod
    def _crop(screen: Image.Image, box: Box) -> Image.Image:
        return screen.crop((box.x, box.y, box.x + box.size, box.y + box.size)).convert("RGB")

    @staticmethod
    def _build_adjacency(node_boxes: Sequence[Box], tile_size: int) -> List[Set[int]]:
        adjacency: List[Set[int]] = [set() for _ in node_boxes]
        nearest = []
        for node_id, box in enumerate(node_boxes):
            distances = [
                math.dist(
                    (box.center.x(), box.center.y()),
                    (other.center.x(), other.center.y()),
                )
                for other_id, other in enumerate(node_boxes)
                if other_id != node_id
            ]
            eligible = [
                distance
                for distance in distances
                if tile_size * 0.55 <= distance <= tile_size * 1.45
            ]
            if eligible:
                nearest.append(min(eligible))
        if not nearest:
            return adjacency
        step = statistics.median(nearest)
        tolerance = max(2.5, step * 0.14)
        for left in range(len(node_boxes)):
            left_center = (node_boxes[left].center.x(), node_boxes[left].center.y())
            for right in range(left + 1, len(node_boxes)):
                right_center = (node_boxes[right].center.x(), node_boxes[right].center.y())
                if abs(math.dist(left_center, right_center) - step) <= tolerance:
                    adjacency[left].add(right)
                    adjacency[right].add(left)
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
                        original_labels, adjacency, fixed_nodes, first_node, priority
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
                connection = self._find_next_connection(connected, target, current_labels, adjacency)
                if connection is None:
                    continue
                cost, grid_path, aspect_path = connection
                free_neighbors = sum(neighbor not in connected for neighbor in adjacency[target])
                if priority == "constrained":
                    sort_key = (free_neighbors, cost, len(grid_path), target)
                else:
                    sort_key = (cost, free_neighbors, len(grid_path), target)
                candidates.append((sort_key, target, grid_path, aspect_path))
            if not candidates:
                unresolved = "、".join(
                    self._aspect_name(original_labels[node_id]) for node_id in sorted(remaining)
                )
                raise ScanError(f"无法生成完整连接方案，未连接元素：{unresolved}")
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
        serial = itertools.count()
        queue = []
        best: Dict[Tuple[int, int], Tuple[float, int]] = {}
        for start in sorted(connected):
            aspect_id = current_labels[start]
            state = (start, aspect_id)
            best[state] = (0.0, 0)
            heapq.heappush(queue, (0.0, 0, next(serial), start, aspect_id, [start], [aspect_id]))
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
