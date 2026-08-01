"use client";

import { useEffect, useRef } from "react";
import * as THREE from "three";
import { type ColorDomain, colormap } from "@/lib/colormap";

interface HeatmapViewProps {
  nx: number;
  ny: number;
  temperatureC: number[];
  widthM: number;
  heightM: number;
  domain: ColorDomain;
}

export function HeatmapView({ nx, ny, temperatureC, widthM, heightM, domain }: HeatmapViewProps) {
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

    const range = domain.maxC - domain.minC || 1;
    const data = current.texture.image.data as Uint8Array;
    // solver cell index for (i, j) on an (nx, ny) mesh is i * ny + j (row-major,
    // see solver/geometry.py Mesh.cell_index) -- match that here.
    for (let j = 0; j < ny; j++) {
      for (let i = 0; i < nx; i++) {
        const cellIndex = i * ny + j;
        const temp = temperatureC[cellIndex];
        const [r, g, b] = colormap((temp - domain.minC) / range);
        const pixelIndex = (j * nx + i) * 4;
        data[pixelIndex] = r;
        data[pixelIndex + 1] = g;
        data[pixelIndex + 2] = b;
        data[pixelIndex + 3] = 255;
      }
    }
    current.texture.needsUpdate = true;
    current.renderer.render(current.scene, current.camera);
  }, [temperatureC, nx, ny, domain]);

  return <div ref={containerRef} className="w-full" />;
}
