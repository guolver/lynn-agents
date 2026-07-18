"use client";

import { useState } from "react";
import type { SkillGraphData, SkillGraphNode } from "../lib/types";
import { ForceGraph } from "./force-graph";

function DetailPanel({ node, data }: { node: SkillGraphNode; data: SkillGraphData }) {
  const aliases = data.links
    .filter((l) => l.type === "ALIAS_OF" && l.target === node.id)
    .map((l) => l.source);

  const parentLink = data.links.find((l) => l.type === "CHILD_OF" && l.source === node.id);
  const parentCategory = parentLink?.target ?? null;

  const childSkills = data.links
    .filter((l) => l.type === "CHILD_OF" && l.target === node.id)
    .map((l) => l.source);

  const aliasTarget = data.links.find((l) => l.type === "ALIAS_OF" && l.source === node.id);

  return (
    <div className="panel">
      <div className="panel-header">
        <div>
          <h3 className="panel-title">{node.id}</h3>
          <p className="panel-subtitle">节点详情</p>
        </div>
        <span className={`skill-type-badge skill-type-${node.type}`}>{node.type}</span>
      </div>
      <div className="panel-body">
        <dl className="detail-grid">
          <dt>节点类型</dt>
          <dd>{node.type === "category" ? "技能类别" : node.type === "skill" ? "技能" : "别名"}</dd>

          {parentCategory && (
            <>
              <dt>所属类别</dt>
              <dd>{parentCategory}</dd>
            </>
          )}

          {aliasTarget && (
            <>
              <dt>标准名称</dt>
              <dd>{aliasTarget.target}</dd>
            </>
          )}

          {aliases.length > 0 && (
            <>
              <dt>别名列表</dt>
              <dd>
                <div className="tag-list">
                  {aliases.map((a) => (
                    <span key={a} className="tag">
                      {a}
                    </span>
                  ))}
                </div>
              </dd>
            </>
          )}

          {childSkills.length > 0 && (
            <>
              <dt>包含技能</dt>
              <dd>
                <div className="tag-list">
                  {childSkills.map((s) => (
                    <span key={s} className="tag">
                      {s}
                    </span>
                  ))}
                </div>
              </dd>
            </>
          )}
        </dl>
      </div>
    </div>
  );
}

export function SkillGraphExplorer({ data }: { data: SkillGraphData }) {
  const [selected, setSelected] = useState<SkillGraphNode | null>(null);

  return (
    <div className="skill-graph-split">
      <div className="panel skill-graph-panel">
        <div className="panel-header">
          <div>
            <h3 className="panel-title">技能关系图谱</h3>
            <p className="panel-subtitle">
              {data.nodes.length} 个节点 · {data.links.length} 条关系
            </p>
          </div>
          <div className="skill-graph-legend">
            <span className="skill-legend-item">
              <span className="skill-legend-dot skill-legend-category" />
              类别
            </span>
            <span className="skill-legend-item">
              <span className="skill-legend-dot skill-legend-skill" />
              技能
            </span>
            <span className="skill-legend-item">
              <span className="skill-legend-dot skill-legend-alias" />
              别名
            </span>
          </div>
        </div>
        <ForceGraph data={data} onNodeClick={setSelected} selectedId={selected?.id} />
      </div>
      {selected && <DetailPanel node={selected} data={data} />}
    </div>
  );
}
