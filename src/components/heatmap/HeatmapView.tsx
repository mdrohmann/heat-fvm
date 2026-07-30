"use client";

import { useEffect, useRef } from "react";
import * as THREE from "three";

interface HeatmapViewProps {
  nx: number;
  ny: number;
  temperatureC: number[];
  widthM: number;
  heightM: number;
}

// A diverging cold->hot ramp (blue - pale - red), evaluated on the CPU and
// uploaded as a texture. Swapping this for a GPU colormap shader later is a
// drop-in change -- the scene/camera/plane setup below doesn't need to move to
// support that, or a future 3D volume-rendering upgrade.
const COLOR_STOPS: [number, [number, number, number]][] = [
  [0.0, [33, 102, 172]],
  [0.25, [146, 197, 222]],
  [0.5, [247, 247, 247]],
  [0.75, [244, 165, 130]],
  [1.0, [178, 24, 43]],
];

function colormap(t: number): [number, number, number] {
  const clamped = Math.max(0, Math.min(1, t));
  for (let i = 0; i < COLOR_STOPS.length - 1; i++) {
    const [t0, c0] = COLOR_STOPS[i];
    const [t1, c1] = COLOR_STOPS[i + 1];
    if (clamped >= t0 && clamped <= t1) {
      const f = t1 === t0 ? 0 : (clamped - t0) / (t1 - t0);
      return [
        Math.round(c0[0] + f * (c1[0] - c0[0])),
        Math.round(c0[1] + f * (c1[1] - c0[1])),
        Math.round(c0[2] + f * (c1[2] - c0[2])),
      ];
    }
  }
  return COLOR_STOPS[COLOR_STOPS.length - 1][1];
}

export function HeatmapView({ nx, ny, temperatureC, widthM, heightM }: HeatmapViewProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const sceneRef = useRef<{
    renderer: THREE.WebGLRenderer;
    scene: THREE.Scene;
    camera: THREE.OrthographicCamera;
    texture: THREE.DataTexture;
  } | null>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const width = container.clientWidth || 400;
    const height = (width * heightM) / widthM;

    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setSize(width, height);
    container.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    const camera = new THREE.OrthographicCamera(-widthM / 2, widthM / 2, heightM / 2, -heightM / 2, 0.1, 10);
    camera.position.z = 1;

    const data = new Uint8Array(Math.max(nx, 1) * Math.max(ny, 1) * 4);
    const texture = new THREE.DataTexture(data, nx, ny, THREE.RGBAFormat);
    texture.magFilter = THREE.LinearFilter;
    texture.minFilter = THREE.LinearFilter;
    texture.flipY = true;

    const geometry = new THREE.PlaneGeometry(widthM, heightM);
    const material = new THREE.MeshBasicMaterial({ map: texture });
    const mesh = new THREE.Mesh(geometry, material);
    scene.add(mesh);

    renderer.render(scene, camera);
    sceneRef.current = { renderer, scene, camera, texture };

    return () => {
      renderer.dispose();
      geometry.dispose();
      material.dispose();
      texture.dispose();
      container.removeChild(renderer.domElement);
      sceneRef.current = null;
    };
  }, [nx, ny, widthM, heightM]);

  useEffect(() => {
    const current = sceneRef.current;
    if (!current || temperatureC.length !== nx * ny) return;

    let minTemp = Infinity;
    let maxTemp = -Infinity;
    for (const t of temperatureC) {
      if (t < minTemp) minTemp = t;
      if (t > maxTemp) maxTemp = t;
    }
    const range = maxTemp - minTemp || 1;

    const data = current.texture.image.data as Uint8Array;
    // solver cell index for (i, j) on an (nx, ny) mesh is i * ny + j (row-major,
    // see solver/geometry.py Mesh.cell_index) -- match that here.
    for (let j = 0; j < ny; j++) {
      for (let i = 0; i < nx; i++) {
        const cellIndex = i * ny + j;
        const temp = temperatureC[cellIndex];
        const [r, g, b] = colormap((temp - minTemp) / range);
        const pixelIndex = (j * nx + i) * 4;
        data[pixelIndex] = r;
        data[pixelIndex + 1] = g;
        data[pixelIndex + 2] = b;
        data[pixelIndex + 3] = 255;
      }
    }
    current.texture.needsUpdate = true;
    current.renderer.render(current.scene, current.camera);
  }, [temperatureC, nx, ny]);

  return <div ref={containerRef} className="w-full" />;
}
