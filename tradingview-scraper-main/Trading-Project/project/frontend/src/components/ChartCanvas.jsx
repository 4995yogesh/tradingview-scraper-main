import React, { useRef, useEffect } from 'react';
import { renderEngine } from '../rendering/ScenarioRenderer';

const ChartCanvas = ({ data, layers }) => {
  const canvasRef = useRef(null);
  
  // Camera state detached from React tree for pure 60FPS fluid motion
  const camera = useRef({ x: window.innerWidth/2, y: 0, zoom: 1 });
  const isDragging = useRef(false);
  const lastMouse = useRef({ x: 0, y: 0 });

  useEffect(() => {
    const canvas = canvasRef.current;
    
    // Fit screen
    const resize = () => {
      canvas.width = window.innerWidth;
      canvas.height = window.innerHeight;
    };
    window.addEventListener('resize', resize);
    resize();

    let animationId;
    const loop = () => {
      // Direct pass to pure JS rendering module
      if(canvas) {
         renderEngine(canvas, canvas.getContext('2d'), data, layers, camera.current);
      }
      animationId = requestAnimationFrame(loop);
    };
    loop();

    return () => {
      window.removeEventListener('resize', resize);
      cancelAnimationFrame(animationId);
    };
  }, [data, layers]);

  const handlePointerDown = (e) => {
    isDragging.current = true;
    lastMouse.current = { x: e.clientX, y: e.clientY };
  };

  const handlePointerMove = (e) => {
    if (!isDragging.current) return;
    const dx = e.clientX - lastMouse.current.x;
    const dy = e.clientY - lastMouse.current.y;
    camera.current.x += dx;
    camera.current.y += dy;
    lastMouse.current = { x: e.clientX, y: e.clientY };
  };

  const handlePointerUp = () => {
    isDragging.current = false;
  };

  const handleWheel = (e) => {
    // Zoom logic around mouse center
    const zoomFactor = 1.05;
    const dir = e.deltaY > 0 ? (1 / zoomFactor) : zoomFactor;
    
    // Offset correction for zoom focus
    const oldZoom = camera.current.zoom;
    camera.current.zoom = Math.max(0.1, Math.min(10, camera.current.zoom * dir));
    
    const mouseXWorld = (e.clientX - camera.current.x) / oldZoom;
    const mouseYWorld = (e.clientY - camera.current.y) / oldZoom;
    
    camera.current.x = e.clientX - mouseXWorld * camera.current.zoom;
    camera.current.y = e.clientY - mouseYWorld * camera.current.zoom;
  };

  return (
    <canvas
      ref={canvasRef}
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={handlePointerUp}
      onPointerLeave={handlePointerUp}
      onWheel={handleWheel}
    />
  );
};

export default ChartCanvas;
