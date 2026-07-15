import { PageHeader } from "../../../components/page-header";
import { funnelData } from "../../../lib/demo-data";

export const metadata = { title: "匹配与推荐" };

const breakdown = [
  { label: "技能匹配", value: 91 },
  { label: "语言匹配", value: 96 },
  { label: "地区与时区", value: 88 },
  { label: "薪资匹配", value: 82 },
  { label: "用户偏好", value: 76 },
  { label: "新鲜度与质量", value: 93 },
];

export default function MatchesPage() {
  return (
    <>
      <PageHeader eyebrow="Matching engine" title="先硬过滤，再做可解释排序" description="地区、时区、语言、薪资和授权任一不满足都会被排除；进入排序的职位按版本化权重生成匹配理由。" action={<button className="button">运行候选人匹配</button>} />
      <div className="split-grid">
        <section className="panel"><div className="panel-header"><div><h2 className="panel-title">处理转化</h2><p className="panel-subtitle">过去 24 小时的职位处理链路</p></div></div><div className="panel-body funnel">{funnelData.map((item) => <div className="funnel-row" key={item.label}><span>{item.label}</span><div className="funnel-track"><div className="funnel-fill" style={{ width: `${item.width}%` }} /></div><span className="funnel-value">{item.value}</span></div>)}</div></section>
        <section className="panel"><div className="panel-header"><div><h2 className="panel-title">示例匹配 · 87%</h2><p className="panel-subtitle">AI Evaluation Specialist × candidate_demo_001</p></div></div><div className="panel-body funnel">{breakdown.map((item) => <div className="funnel-row" key={item.label}><span>{item.label}</span><div className="bar-track"><div className="bar-fill" style={{ width: `${item.value}%` }} /></div><span className="funnel-value">{item.value}%</span></div>)}</div></section>
      </div>
      <section className="panel" style={{ marginTop: 16 }}><div className="panel-header"><div><h2 className="panel-title">推荐理由预览</h2><p className="panel-subtitle">候选人收到的是规则结果的可读解释，而不是不可追溯的模型判断</p></div><span className="status-badge approved">hard filter passed</span></div><div className="panel-body"><div className="tag-list"><span className="tag">技能与职位要求高度匹配</span><span className="tag">地区与工作时区满足要求</span><span className="tag">薪资达到最低期望</span><span className="tag">职位类别符合偏好</span></div></div></section>
    </>
  );
}
