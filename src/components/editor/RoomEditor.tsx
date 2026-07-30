"use client";

import { useRef } from "react";
import type { HeatSource, Room, WallElement, WallSide } from "@/lib/types";

const PX_PER_M = 80;
const WALL_THICKNESS_PX = 10;
const DEFAULT_WINDOW_LENGTH_M = 1.2;
const DEFAULT_DOOR_LENGTH_M = 0.9;

const WALL_SIDES: WallSide[] = ["north", "east", "south", "west"];

interface RoomEditorProps {
  room: Room;
  heatSource: HeatSource;
  onChangeRoom: (room: Room) => void;
  onChangeHeatSource: (heatSource: HeatSource) => void;
}

function wallLengthM(room: Room, side: WallSide): number {
  return side === "north" || side === "south" ? room.widthM : room.heightM;
}

function clampToFreeSlot(desiredOffsetM: number, lengthM: number, wallLengthM: number, others: WallElement[]): number {
  const max = wallLengthM - lengthM;
  let offset = Math.max(0, Math.min(desiredOffsetM, max));

  for (const other of others) {
    const start = other.offsetM;
    const end = other.offsetM + other.lengthM;
    const overlaps = offset < end && offset + lengthM > start;
    if (overlaps) {
      const pushLeft = Math.max(0, start - lengthM);
      const pushRight = Math.min(max, end);
      offset = Math.abs(offset - pushLeft) < Math.abs(offset - pushRight) ? pushLeft : pushRight;
    }
  }

  return offset;
}

function toModelPoint(svg: SVGSVGElement, clientX: number, clientY: number, heightM: number) {
  const point = svg.createSVGPoint();
  point.x = clientX;
  point.y = clientY;
  const screenCTM = svg.getScreenCTM();
  if (!screenCTM) return { xM: 0, yM: 0 };
  const local = point.matrixTransform(screenCTM.inverse());
  return { xM: local.x / PX_PER_M, yM: heightM - local.y / PX_PER_M };
}

export function RoomEditor({ room, heatSource, onChangeRoom, onChangeHeatSource }: RoomEditorProps) {
  const svgRef = useRef<SVGSVGElement | null>(null);

  const widthPx = room.widthM * PX_PER_M;
  const heightPx = room.heightM * PX_PER_M;

  function updateElement(side: WallSide, index: number, offsetM: number) {
    const elements = room.walls[side];
    const el = elements[index];
    const others = elements.filter((_, i) => i !== index);
    const clamped = clampToFreeSlot(offsetM, el.lengthM, wallLengthM(room, side), others);
    const next = elements.map((e, i) => (i === index ? { ...e, offsetM: clamped } : e));
    onChangeRoom({ ...room, walls: { ...room.walls, [side]: next } });
  }

  function addElement(side: WallSide, type: "window" | "door") {
    const lengthM = type === "window" ? DEFAULT_WINDOW_LENGTH_M : DEFAULT_DOOR_LENGTH_M;
    const wallLen = wallLengthM(room, side);
    const desired = Math.max(0, wallLen / 2 - lengthM / 2);
    const clamped = clampToFreeSlot(desired, lengthM, wallLen, room.walls[side]);
    const next = [...room.walls[side], { type, offsetM: clamped, lengthM }];
    onChangeRoom({ ...room, walls: { ...room.walls, [side]: next } });
  }

  function removeElement(side: WallSide, index: number) {
    const next = room.walls[side].filter((_, i) => i !== index);
    onChangeRoom({ ...room, walls: { ...room.walls, [side]: next } });
  }

  function handleWallElementPointerDown(e: React.PointerEvent<SVGRectElement>) {
    e.currentTarget.setPointerCapture(e.pointerId);
    e.stopPropagation();
  }

  function handleWallElementPointerMove(e: React.PointerEvent<SVGRectElement>, side: WallSide, index: number) {
    if (e.buttons === 0 || !svgRef.current) return;
    const { xM, yM } = toModelPoint(svgRef.current, e.clientX, e.clientY, room.heightM);
    const alongAxis = side === "north" || side === "south" ? xM : yM;
    updateElement(side, index, alongAxis);
  }

  function handleHeatSourcePointerDown(e: React.PointerEvent<SVGCircleElement>) {
    e.currentTarget.setPointerCapture(e.pointerId);
  }

  function handleHeatSourcePointerMove(e: React.PointerEvent<SVGCircleElement>) {
    if (e.buttons === 0 || !svgRef.current) return;
    const { xM, yM } = toModelPoint(svgRef.current, e.clientX, e.clientY, room.heightM);
    onChangeHeatSource({
      ...heatSource,
      xM: Math.max(0.05, Math.min(room.widthM - 0.05, xM)),
      yM: Math.max(0.05, Math.min(room.heightM - 0.05, yM)),
    });
  }

  return (
    <div className="flex flex-col gap-3">
      <svg
        ref={svgRef}
        viewBox={`0 0 ${widthPx} ${heightPx}`}
        width="100%"
        style={{ maxWidth: widthPx, aspectRatio: `${widthPx} / ${heightPx}` }}
        className="rounded bg-neutral-50 dark:bg-neutral-900"
      >
        {/* room interior */}
        <rect x={0} y={0} width={widthPx} height={heightPx} className="fill-amber-50 dark:fill-neutral-800" />

        {/* walls */}
        <rect x={-WALL_THICKNESS_PX / 2} y={-WALL_THICKNESS_PX / 2} width={widthPx + WALL_THICKNESS_PX} height={WALL_THICKNESS_PX} className="fill-neutral-700 dark:fill-neutral-400" />
        <rect x={-WALL_THICKNESS_PX / 2} y={heightPx - WALL_THICKNESS_PX / 2} width={widthPx + WALL_THICKNESS_PX} height={WALL_THICKNESS_PX} className="fill-neutral-700 dark:fill-neutral-400" />
        <rect x={-WALL_THICKNESS_PX / 2} y={-WALL_THICKNESS_PX / 2} width={WALL_THICKNESS_PX} height={heightPx + WALL_THICKNESS_PX} className="fill-neutral-700 dark:fill-neutral-400" />
        <rect x={widthPx - WALL_THICKNESS_PX / 2} y={-WALL_THICKNESS_PX / 2} width={WALL_THICKNESS_PX} height={heightPx + WALL_THICKNESS_PX} className="fill-neutral-700 dark:fill-neutral-400" />

        {/* wall elements (windows/doors) */}
        {WALL_SIDES.map((side) =>
          room.walls[side].map((el, index) => {
            const isHorizontal = side === "north" || side === "south";
            const lenPx = el.lengthM * PX_PER_M;
            const offsetPx = el.offsetM * PX_PER_M;
            const y = side === "north" ? 0 : side === "south" ? heightPx : offsetPx;
            const x = side === "west" ? 0 : side === "east" ? widthPx : offsetPx;
            const rectProps = isHorizontal
              ? { x, y: y - WALL_THICKNESS_PX / 2, width: lenPx, height: WALL_THICKNESS_PX }
              : { x: x - WALL_THICKNESS_PX / 2, y, width: WALL_THICKNESS_PX, height: lenPx };

            return (
              <g key={`${side}-${index}`}>
                <rect
                  {...rectProps}
                  className={el.type === "window" ? "fill-sky-400 cursor-move" : "fill-amber-700 cursor-move"}
                  onPointerDown={handleWallElementPointerDown}
                  onPointerMove={(e) => handleWallElementPointerMove(e, side, index)}
                />
                <text
                  x={isHorizontal ? x + lenPx / 2 : x + (side === "west" ? 14 : -14)}
                  y={isHorizontal ? y + (side === "north" ? 16 : -12) : y + lenPx / 2}
                  textAnchor="middle"
                  className="fill-red-600 cursor-pointer text-[14px] select-none"
                  onClick={() => removeElement(side, index)}
                >
                  ×
                </text>
              </g>
            );
          }),
        )}

        {/* heat source */}
        <circle
          cx={heatSource.xM * PX_PER_M}
          cy={heightPx - heatSource.yM * PX_PER_M}
          r={10}
          className="fill-red-500 cursor-move stroke-red-800"
          strokeWidth={1.5}
          onPointerDown={handleHeatSourcePointerDown}
          onPointerMove={handleHeatSourcePointerMove}
        />
      </svg>

      <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
        {WALL_SIDES.map((side) => (
          <div key={side} className="flex items-center gap-2">
            <span className="w-14 capitalize">{side}</span>
            <button type="button" className="rounded border px-2 py-0.5" onClick={() => addElement(side, "window")}>
              + window
            </button>
            <button type="button" className="rounded border px-2 py-0.5" onClick={() => addElement(side, "door")}>
              + door
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
