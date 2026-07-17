import Link from "next/link";
import { PageHeader } from "../../../components/page-header";
import { getJobs } from "../../../lib/agent-hub";

export const metadata = { title: "职位中心" };

export default async function JobsPage() {
  const jobs = await getJobs();
  return (
    <>
      <PageHeader eyebrow="Job intelligence" title="职位质量与风险一屏可见" description="每条职位保留来源、规范化结果、确定性风险分和质量分。中高风险内容不会绕过人工审核。" />
      <div className="toolbar"><input className="search-box" aria-label="搜索职位" placeholder="搜索职位或公司…" /><div className="filter-group"><button className="filter-chip">全部 {jobs.length}</button><button className="filter-chip">低风险 {jobs.filter((j) => j.risk_level === "low").length}</button><button className="filter-chip">待审核 {jobs.filter((j) => j.status === "pending_review").length}</button></div></div>
      <section className="panel table-wrap"><table className="data-table"><thead><tr><th>职位</th><th>工作方式</th><th>地区</th><th>薪酬</th><th>风险</th><th>质量分</th><th>状态</th></tr></thead><tbody>{jobs.map((job) => <tr key={job.id} className="clickable-row"><td><Link href={`/jobs/${job.id}`} className="cell-link"><div className="cell-primary">{job.title_original}</div><div className="cell-secondary">{job.company_name} · {job.id}</div></Link></td><td>{job.work_mode}</td><td>{job.countries_allowed.join(", ")}</td><td>{job.compensation_min ?? "?"}–{job.compensation_max ?? "?"} {job.compensation_currency ?? ""}</td><td><span className={`risk-badge ${job.risk_level}`}>{job.risk_level} · {Math.round(job.risk_score * 100)}%</span></td><td>{Math.round(job.quality_score * 100)}%</td><td><span className={`status-badge ${job.status === "active" ? "active" : job.status === "rejected" ? "rejected" : "pending"}`}>{job.status}</span></td></tr>)}</tbody></table></section>
    </>
  );
}
