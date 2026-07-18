import { PageHeader } from "../../../components/page-header";
import { SkillGraphExplorer } from "../../../components/skill-graph-explorer";
import { getSkillGraph } from "../../../lib/agent-hub";

export const metadata = { title: "技能图谱" };

export default async function SkillsPage() {
  const data = await getSkillGraph();
  return (
    <>
      <PageHeader
        eyebrow="Skill knowledge graph"
        title="技能知识图谱"
        description="可视化技能分类、别名归一化和上下位关系。点击节点查看详情。"
      />
      <SkillGraphExplorer data={data} />
    </>
  );
}
