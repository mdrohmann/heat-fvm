"""Room/window/door/heat-source geometry and Cartesian mesh generation.

The `Mesh` class is generic over dimensionality (2D now, 3D later — see CLAUDE.md);
only the room/wall data model and boundary-face tagging below are inherently 2D,
since a room's "walls" become a different (6-face) shape in 3D.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

import numpy as np

WallSide = str  # "north" | "east" | "south" | "west"

_WALL_SIDES: tuple[WallSide, ...] = ("north", "east", "south", "west")


class WallElementType(str, Enum):
    WALL = "wall"
    WINDOW = "window"
    DOOR = "door"


@dataclass(frozen=True)
class WallElement:
    """A window or door placed on a wall. Plain wall is the implicit background —
    only openings need to be listed explicitly."""

    type: WallElementType
    offset_m: float
    length_m: float

    def __post_init__(self) -> None:
        if self.type == WallElementType.WALL:
            raise ValueError(
                "WallElement should only represent windows/doors; plain wall is "
                "implicit background, not a listed element"
            )
        if self.length_m <= 0:
            raise ValueError(f"length_m must be positive, got {self.length_m}")
        if self.offset_m < 0:
            raise ValueError(f"offset_m must be non-negative, got {self.offset_m}")


@dataclass(frozen=True)
class HeatSource:
    x_m: float
    y_m: float
    max_power_w: float


@dataclass(frozen=True)
class Room:
    """A single rectangular room. `walls` lists only the window/door openings on
    each side; the rest of each wall is plain wall by default."""

    width_m: float
    height_m: float
    walls: dict[WallSide, list[WallElement]] = field(
        default_factory=lambda: {side: [] for side in _WALL_SIDES}
    )

    def __post_init__(self) -> None:
        if self.width_m <= 0 or self.height_m <= 0:
            raise ValueError("room width_m/height_m must be positive")
        for side in _WALL_SIDES:
            if side not in self.walls:
                raise ValueError(f"walls dict missing side {side!r}")
        self._validate_side("north", self.width_m)
        self._validate_side("south", self.width_m)
        self._validate_side("east", self.height_m)
        self._validate_side("west", self.height_m)

    def _validate_side(self, side: WallSide, wall_length_m: float) -> None:
        elements = sorted(self.walls[side], key=lambda e: e.offset_m)
        prev_end = 0.0
        for el in elements:
            if el.offset_m < prev_end - 1e-9:
                raise ValueError(f"overlapping elements on {side} wall")
            if el.offset_m + el.length_m > wall_length_m + 1e-9:
                raise ValueError(
                    f"{side} wall element extends past wall end "
                    f"({el.offset_m + el.length_m:.3f}m > {wall_length_m:.3f}m)"
                )
            prev_end = el.offset_m + el.length_m


@dataclass(frozen=True)
class Mesh:
    """Uniform Cartesian grid, generic over dimensionality.

    `shape` is the cell count per axis (e.g. (nx, ny) in 2D, (nx, ny, nz) in 3D).
    Extending to 3D means constructing a Mesh with a 3-tuple shape/spacing; the
    properties below do not assume a fixed number of axes.
    """

    shape: tuple[int, ...]
    spacing_m: tuple[float, ...]

    def __post_init__(self) -> None:
        if len(self.shape) != len(self.spacing_m):
            raise ValueError("shape and spacing_m must have the same length")
        if any(n < 1 for n in self.shape):
            raise ValueError("all mesh dimensions must have at least 1 cell")
        if any(d <= 0 for d in self.spacing_m):
            raise ValueError("all spacing_m values must be positive")

    @property
    def n_dims(self) -> int:
        return len(self.shape)

    @property
    def n_cells(self) -> int:
        return int(np.prod(self.shape))

    @property
    def cell_measure_m2(self) -> float:
        """Cell area (2D) / volume (3D), per unit depth in the 2D case."""
        return float(np.prod(self.spacing_m))

    def cell_centers_m(self) -> np.ndarray:
        """Shape (n_cells, n_dims) array of cell-center coordinates."""
        axes = [(np.arange(n) + 0.5) * d for n, d in zip(self.shape, self.spacing_m)]
        grids = np.meshgrid(*axes, indexing="ij")
        return np.stack([g.ravel() for g in grids], axis=-1)

    def cell_index(self, multi_index: tuple[int, ...]) -> int:
        return int(np.ravel_multi_index(multi_index, self.shape))


@dataclass(frozen=True)
class BoundaryFace:
    cell_index: int
    side: WallSide
    element_type: WallElementType
    face_area_m2: float


@dataclass(frozen=True)
class RoomMesh:
    mesh: Mesh
    depth_m: float
    boundary_faces: list[BoundaryFace]
    heat_source_cell: int


def _position_along_wall(side: WallSide, x_m: float, y_m: float) -> float:
    return x_m if side in ("north", "south") else y_m


def _element_type_at(room: Room, side: WallSide, position_m: float) -> WallElementType:
    for el in room.walls[side]:
        if el.offset_m <= position_m < el.offset_m + el.length_m:
            return el.type
    return WallElementType.WALL


def _nearest_cell(centers_m: np.ndarray, x_m: float, y_m: float) -> int:
    dists_sq = (centers_m[:, 0] - x_m) ** 2 + (centers_m[:, 1] - y_m) ** 2
    return int(np.argmin(dists_sq))


def build_room_mesh(
    room: Room,
    heat_source: HeatSource,
    nx: int,
    ny: int,
    depth_m: float = 2.5,
) -> RoomMesh:
    """Build a 2D Cartesian mesh over `room` and tag boundary faces by wall element
    type (wall/window/door) so the FVM assembly can look up the right U-value.
    `depth_m` is the assumed room height, used to convert the 2D (per-unit-depth)
    solve into physically-scaled face areas / Watts.
    """
    dx = room.width_m / nx
    dy = room.height_m / ny
    mesh = Mesh(shape=(nx, ny), spacing_m=(dx, dy))
    centers = mesh.cell_centers_m()

    boundary_faces: list[BoundaryFace] = []
    for j in range(ny):
        for i in range(nx):
            idx = mesh.cell_index((i, j))
            x, y = centers[idx]
            if j == 0:
                side: WallSide = "south"
                pos = _position_along_wall(side, x, y)
                boundary_faces.append(
                    BoundaryFace(idx, side, _element_type_at(room, side, pos), dx * depth_m)
                )
            if j == ny - 1:
                side = "north"
                pos = _position_along_wall(side, x, y)
                boundary_faces.append(
                    BoundaryFace(idx, side, _element_type_at(room, side, pos), dx * depth_m)
                )
            if i == 0:
                side = "west"
                pos = _position_along_wall(side, x, y)
                boundary_faces.append(
                    BoundaryFace(idx, side, _element_type_at(room, side, pos), dy * depth_m)
                )
            if i == nx - 1:
                side = "east"
                pos = _position_along_wall(side, x, y)
                boundary_faces.append(
                    BoundaryFace(idx, side, _element_type_at(room, side, pos), dy * depth_m)
                )

    heat_source_cell = _nearest_cell(centers, heat_source.x_m, heat_source.y_m)

    return RoomMesh(
        mesh=mesh,
        depth_m=depth_m,
        boundary_faces=boundary_faces,
        heat_source_cell=heat_source_cell,
    )
