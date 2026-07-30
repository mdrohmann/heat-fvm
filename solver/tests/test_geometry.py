import pytest

from solver.geometry import (
    HeatSource,
    Room,
    WallElement,
    WallElementType,
    build_room_mesh,
)


def test_room_rejects_overlapping_elements():
    with pytest.raises(ValueError, match="overlapping"):
        Room(
            width_m=4.0,
            height_m=3.0,
            walls={
                "north": [],
                "south": [
                    WallElement(WallElementType.WINDOW, offset_m=0.0, length_m=2.0),
                    WallElement(WallElementType.DOOR, offset_m=1.5, length_m=1.0),
                ],
                "east": [],
                "west": [],
            },
        )


def test_room_rejects_element_past_wall_end():
    with pytest.raises(ValueError, match="past wall end"):
        Room(
            width_m=4.0,
            height_m=3.0,
            walls={
                "north": [],
                "south": [WallElement(WallElementType.DOOR, offset_m=3.5, length_m=1.0)],
                "east": [],
                "west": [],
            },
        )


def test_build_room_mesh_tags_boundary_faces_by_wall_element():
    # A 4m x 3m room with a 2m-wide door centered on the south wall (offset 1-3m).
    room = Room(
        width_m=4.0,
        height_m=3.0,
        walls={
            "north": [],
            "south": [WallElement(WallElementType.DOOR, offset_m=1.0, length_m=2.0)],
            "east": [],
            "west": [],
        },
    )
    heat_source = HeatSource(x_m=2.0, y_m=1.5, max_power_w=1500.0)
    room_mesh = build_room_mesh(room, heat_source, nx=8, ny=6)

    south_faces = [f for f in room_mesh.boundary_faces if f.side == "south"]
    assert len(south_faces) == 8  # one boundary face per column along the south wall

    centers = room_mesh.mesh.cell_centers_m()
    door_faces = [f for f in south_faces if 1.0 < centers[f.cell_index][0] < 3.0]
    wall_faces = [f for f in south_faces if f not in door_faces]

    assert door_faces, "expected at least one south-wall face under the door"
    assert wall_faces, "expected at least one south-wall face outside the door"
    assert all(f.element_type == WallElementType.DOOR for f in door_faces)
    assert all(f.element_type == WallElementType.WALL for f in wall_faces)


def test_build_room_mesh_places_heat_source_at_nearest_cell():
    room = Room(width_m=4.0, height_m=3.0)
    heat_source = HeatSource(x_m=3.7, y_m=0.2, max_power_w=1000.0)
    room_mesh = build_room_mesh(room, heat_source, nx=4, ny=3)

    centers = room_mesh.mesh.cell_centers_m()
    hx, hy = centers[room_mesh.heat_source_cell]
    # Cells are 1m x 1m here; the source at (3.7, 0.2) should land in the
    # southeast-corner cell centered at (3.5, 0.5).
    assert hx == pytest.approx(3.5)
    assert hy == pytest.approx(0.5)


def test_mesh_cell_count_and_measure():
    room = Room(width_m=4.0, height_m=2.0)
    heat_source = HeatSource(x_m=2.0, y_m=1.0, max_power_w=1000.0)
    room_mesh = build_room_mesh(room, heat_source, nx=8, ny=4)

    assert room_mesh.mesh.n_cells == 32
    assert room_mesh.mesh.cell_measure_m2 == pytest.approx(0.5 * 0.5)
