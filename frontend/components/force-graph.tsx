"use client";

import * as d3 from "d3";
import { useCallback, useEffect, useRef } from "react";
import type { SkillGraphData, SkillGraphNode } from "../lib/types";

type SimNode = SkillGraphNode & d3.SimulationNodeDatum;
type SimLink = d3.SimulationLinkDatum<SimNode> & { type: string };

const NODE_RADIUS: Record<string, number> = { category: 24, skill: 14, alias: 8 };
const NODE_COLOR: Record<string, string> = {
  "前端开发": "#326cb0",
  "后端开发": "#176b4d",
  "数据库": "#bc7423",
  "容器与云": "#6b4da0",
  "移动开发": "#b54842",
  "数据与AI": "#2a7a8c",
};

function skillColor(node: SimNode, links: SimLink[]): string {
  if (node.type === "category") return NODE_COLOR[node.id] ?? "#176b4d";
  const parentLink = links.find(
    (l) =>
      ((l.source as SimNode).id === node.id || (typeof l.source === "string" && l.source === node.id)) &&
      l.type === "CHILD_OF",
  );
  if (parentLink) {
    const targetId = typeof parentLink.target === "string" ? parentLink.target : (parentLink.target as SimNode).id;
    return NODE_COLOR[targetId] ?? "#176b4d";
  }
  const aliasLink = links.find(
    (l) =>
      ((l.source as SimNode).id === node.id || (typeof l.source === "string" && l.source === node.id)) &&
      l.type === "ALIAS_OF",
  );
  if (aliasLink) {
    const canonicalId = typeof aliasLink.target === "string" ? aliasLink.target : (aliasLink.target as SimNode).id;
    const canonical = links.find(
      (l) =>
        ((l.source as SimNode).id === canonicalId || (typeof l.source === "string" && l.source === canonicalId)) &&
        l.type === "CHILD_OF",
    );
    if (canonical) {
      const catId = typeof canonical.target === "string" ? canonical.target : (canonical.target as SimNode).id;
      return NODE_COLOR[catId] ?? "#176b4d";
    }
  }
  return "#176b4d";
}

export function ForceGraph({
  data,
  onNodeClick,
  selectedId,
}: {
  data: SkillGraphData;
  onNodeClick?: (node: SkillGraphNode) => void;
  selectedId?: string | null;
}) {
  const svgRef = useRef<SVGSVGElement>(null);
  const simulationRef = useRef<d3.Simulation<SimNode, SimLink> | null>(null);

  const handleNodeClick = useCallback(
    (node: SimNode) => {
      onNodeClick?.({ id: node.id, type: node.type });
    },
    [onNodeClick],
  );

  useEffect(() => {
    const svg = d3.select(svgRef.current);
    const width = svgRef.current?.clientWidth ?? 800;
    const height = svgRef.current?.clientHeight ?? 600;

    svg.selectAll("*").remove();

    const nodes: SimNode[] = data.nodes.map((n) => ({ ...n }));
    const links: SimLink[] = data.links.map((l) => ({ source: l.source, target: l.target, type: l.type }));

    const g = svg.append("g");

    const zoom = d3
      .zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.3, 4])
      .on("zoom", (event) => g.attr("transform", event.transform));
    svg.call(zoom);

    const simulation = d3
      .forceSimulation<SimNode>(nodes)
      .force(
        "link",
        d3
          .forceLink<SimNode, SimLink>(links)
          .id((d) => d.id)
          .distance((l) => (l.type === "ALIAS_OF" ? 40 : 80)),
      )
      .force("charge", d3.forceManyBody().strength(-200))
      .force("center", d3.forceCenter(width / 2, height / 2))
      .force(
        "collision",
        d3.forceCollide<SimNode>().radius((d) => (NODE_RADIUS[d.type] ?? 14) + 4),
      );

    simulationRef.current = simulation;

    const link = g
      .append("g")
      .attr("class", "graph-links")
      .selectAll("line")
      .data(links)
      .join("line")
      .attr("stroke", "#c5d0c8")
      .attr("stroke-width", 1.2)
      .attr("stroke-dasharray", (d) => (d.type === "ALIAS_OF" ? "4 3" : "none"));

    const nodeGroup = g
      .append("g")
      .attr("class", "graph-nodes")
      .selectAll<SVGGElement, SimNode>("g")
      .data(nodes)
      .join("g")
      .attr("cursor", "pointer")
      .on("click", (_event, d) => handleNodeClick(d));

    nodeGroup
      .append("circle")
      .attr("r", (d) => NODE_RADIUS[d.type] ?? 14)
      .attr("fill", (d) => skillColor(d, links))
      .attr("fill-opacity", (d) => (d.type === "alias" ? 0.5 : 0.85))
      .attr("stroke", "#fff")
      .attr("stroke-width", (d) => (d.type === "category" ? 2.5 : 1.5));

    nodeGroup
      .filter((d) => d.type !== "alias")
      .append("text")
      .text((d) => d.id)
      .attr("text-anchor", "middle")
      .attr("dy", (d) => (NODE_RADIUS[d.type] ?? 14) + 13)
      .attr("fill", "#526159")
      .attr("font-size", (d) => (d.type === "category" ? "11px" : "9px"))
      .attr("font-weight", (d) => (d.type === "category" ? "700" : "500"));

    const drag = d3
      .drag<SVGGElement, SimNode>()
      .on("start", (event, d) => {
        if (!event.active) simulation.alphaTarget(0.3).restart();
        d.fx = d.x;
        d.fy = d.y;
      })
      .on("drag", (event, d) => {
        d.fx = event.x;
        d.fy = event.y;
      })
      .on("end", (event, d) => {
        if (!event.active) simulation.alphaTarget(0);
        d.fx = null;
        d.fy = null;
      });

    nodeGroup.call(drag);

    simulation.on("tick", () => {
      link
        .attr("x1", (d) => (d.source as SimNode).x!)
        .attr("y1", (d) => (d.source as SimNode).y!)
        .attr("x2", (d) => (d.target as SimNode).x!)
        .attr("y2", (d) => (d.target as SimNode).y!);

      nodeGroup.attr("transform", (d) => `translate(${d.x},${d.y})`);
    });

    return () => {
      simulation.stop();
    };
  }, [data, handleNodeClick]);

  useEffect(() => {
    const svg = d3.select(svgRef.current);
    svg.selectAll<SVGCircleElement, SimNode>("circle").attr("stroke", (d) =>
      d.id === selectedId ? "#176b4d" : "#fff",
    ).attr("stroke-width", (d) =>
      d.id === selectedId ? 3 : d.type === "category" ? 2.5 : 1.5,
    );
  }, [selectedId]);

  return <svg ref={svgRef} className="force-graph-svg" />;
}
