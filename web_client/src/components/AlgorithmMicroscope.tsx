import { useEffect, useRef } from 'react';
import type { Core } from 'cytoscape';
import type { AlgorithmCompareDTO, PathDTO, RouteSubgraphDTO } from '../types';

const clamp = (n: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, n));

function Metric({ label, value }: { label: string; value: number | string }) {
  return <div className="metric"><span>{label}</span><b>{value}</b></div>;
}

export default function AlgorithmMicroscope({
  subgraph,
  compare,
  activeTrace,
}: {
  subgraph: RouteSubgraphDTO | null;
  compare: AlgorithmCompareDTO | null;
  activeTrace: PathDTO | null;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const cyRef = useRef<Core | null>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container || !subgraph || subgraph.nodes.length === 0) return;
    let cancelled = false;
    const xs = subgraph.nodes.map((node) => node.x);
    const ys = subgraph.nodes.map((node) => node.y);
    const minX = Math.min(...xs);
    const maxX = Math.max(...xs);
    const minY = Math.min(...ys);
    const maxY = Math.max(...ys);
    const width = Math.max(1, maxX - minX);
    const height = Math.max(1, maxY - minY);
    const elements = [
      ...subgraph.nodes.map((node) => ({
        data: { id: String(node.id), label: String(node.id), isPath: Boolean(node.is_path) },
        position: {
          x: ((node.x - minX) / width) * 300 + 18,
          y: ((node.y - minY) / height) * 180 + 18,
        },
      })),
      ...subgraph.edges.map((edge) => ({
        data: {
          id: `${edge.u}-${edge.v}`,
          source: String(edge.u),
          target: String(edge.v),
          isPath: Boolean(edge.is_path),
          level: edge.level,
        },
      })),
    ];

    void import('cytoscape').then((module) => {
      if (cancelled) return;
      cyRef.current?.destroy();
      cyRef.current = module.default({
        container,
        elements,
        layout: { name: 'preset', fit: true, padding: 12 },
        userZoomingEnabled: false,
        userPanningEnabled: false,
        boxSelectionEnabled: false,
        style: [
          { selector: 'node', style: { width: 6, height: 6, 'background-color': '#94a3b8', 'border-width': 0 } },
          {
            selector: 'node[isPath]',
            style: {
              width: 9,
              height: 9,
              'background-color': '#2563eb',
              'border-color': '#ffffff',
              'border-width': 2,
            },
          },
          { selector: 'edge', style: { width: 1.2, 'line-color': '#cbd5e1', opacity: 0.55 } },
          { selector: 'edge[isPath]', style: { width: 3, 'line-color': '#7c3aed', opacity: 0.95 } },
          { selector: 'edge[level >= 2]', style: { 'line-color': '#f97316', opacity: 0.85 } },
        ],
      });
    });
    return () => {
      cancelled = true;
      cyRef.current?.destroy();
      cyRef.current = null;
    };
  }, [subgraph]);

  return (
    <section className="panel microscope-panel">
      <div className="panel-title">算法显微镜</div>
      <div className="microscope-metrics">
        <Metric label="子图节点" value={subgraph?.nodes.length ?? 0} />
        <Metric label="子图道路" value={subgraph?.edges.length ?? 0} />
        <Metric label="当前轨迹" value={activeTrace ? activeTrace.algorithm.toUpperCase() : '—'} />
      </div>
      <div ref={containerRef} className="cyto-view">
        {!subgraph && <span>运行路径或竞速后显示局部搜索子图</span>}
      </div>
      {compare && (
        <div className="compare-strip">
          <span>A* {compare.astar.nodes_visited}</span>
          <i style={{ width: `${clamp(compare.visit_reduction_percent, 0, 100)}%` }} />
          <span>Dijkstra {compare.dijkstra.nodes_visited}</span>
        </div>
      )}
      {subgraph?.truncated && <div className="warn">子图已裁剪，仅显示路线附近最重要节点</div>}
    </section>
  );
}
