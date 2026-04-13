import { create } from 'zustand';
import { persist } from 'zustand/middleware';

function generateId() {
  return Math.random().toString(36).substring(2, 9);
}

// Initial predefined clusters and their locations on the infinite plane
const INITIAL_CLUSTERS = [
  { id: 'cluster_4h',  tf: '4h',  x: 6200,  y: 9500 },
  { id: 'cluster_1h',  tf: '1h',  x: 8100,  y: 9500 },
  { id: 'cluster_15m', tf: '15m', x: 10000, y: 9500 },
  { id: 'cluster_5m',  tf: '5m',  x: 11900, y: 9500 },
  { id: 'cluster_1m',  tf: '1m',  x: 13800, y: 9500 },
];

const INITIAL_NODES = INITIAL_CLUSTERS.map(c => ({
  id: `main_${c.id}`,
  clusterId: c.id,
  type: 'main', // 'main', 'fork'
  bias: 'base', // 'base', 'bullish', 'bearish', 'trap'
  relX: 0,      // relative to cluster origin
  relY: 0,
}));

export const useCanvasStore = create(
  persist(
    (set, get) => ({
      clusters: INITIAL_CLUSTERS,
      nodes: INITIAL_NODES,

      // Fork a node within a cluster
      forkNode: (clusterId, parentNodeId, bias) => {
        const { nodes } = get();
        
        // Prevent duplicate forks of the same type in the same cluster
        if (nodes.some(n => n.clusterId === clusterId && n.bias === bias && n.type === 'fork')) {
          return;
        }
        
        let relY = 95; // Bearish center (95 + 130) equals main center (225)
        if (bias === 'bullish') relY = -205; // Gap of 40px from bearish top
        else if (bias === 'bearish') relY = 95;
        else if (bias === 'trap') relY = 395; // Gap of 40px from bearish bottom

        const newNode = {
          id: generateId(),
          clusterId,
          type: 'fork',
          bias,
          parentId: parentNodeId,
          relX: 750, // Fixed 750px gap horizontally
          relY,      // Deterministic Y based on role
        };

        set(state => ({
          nodes: [...state.nodes, newNode]
        }));
      },

      removeFork: (nodeId) => {
        set(state => ({
          nodes: state.nodes.filter(n => n.id !== nodeId || n.type === 'main') // prevent deleting main
        }));
      },

      setClusterPosition: (clusterId, x, y) => {
        set(state => ({
          clusters: state.clusters.map(c => 
            c.id === clusterId ? { ...c, x, y } : c
          )
        }));
      },

    }),
    {
      name: 'canvas-storage-v7', // bumped to reset corrupted state
    }
  )
);
