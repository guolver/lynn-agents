import Link from 'next/link';

export default function Home() {
  return (
    <div className="home-page">
      <div className="home-container">
        {/* Brand */}
        <div className="home-brand">
          <div className="home-brand-mark">AH</div>
          <h1 className="home-title">Agent Hub</h1>
          <p className="home-subtitle">可扩展的 Agent 平台，为你提供智能化的职业发展支持</p>
        </div>

        {/* Agent Cards */}
        <div className="home-cards">
          <Link href="/jobs" className="home-card">
            <div className="home-card-icon">
              <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                <circle cx="12" cy="12" r="10" />
                <path d="M2 12h20M12 2a15.3 15.3 0 014 10 15.3 15.3 0 01-4 10 15.3 15.3 0 01-4-10 15.3 15.3 0 014-10z" />
              </svg>
            </div>
            <h2 className="home-card-title">Remote 岗位</h2>
            <p className="home-card-desc">探索全球远程工作机会，AI 智能匹配你的技能与岗位需求</p>
            <div className="home-card-tags">
              <span className="tag">远程优先</span>
              <span className="tag">全球岗位</span>
              <span className="tag">智能匹配</span>
            </div>
            <span className="home-card-arrow">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M5 12h14M12 5l7 7-7 7" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </span>
          </Link>

          <Link href="/interview" className="home-card">
            <div className="home-card-icon">
              <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                <path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z" />
                <path d="M8 9h8M8 13h6" strokeLinecap="round" />
              </svg>
            </div>
            <h2 className="home-card-title">模拟面试</h2>
            <p className="home-card-desc">与 AI 面试官进行真实场景演练，获得即时反馈与改进建议</p>
            <div className="home-card-tags">
              <span className="tag">AI 面试官</span>
              <span className="tag">实时反馈</span>
              <span className="tag">评估报告</span>
            </div>
            <span className="home-card-arrow">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M5 12h14M12 5l7 7-7 7" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </span>
          </Link>

          <Link href="/manage" className="home-card">
            <div className="home-card-icon">
              <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                <path d="M12 15a3 3 0 100-6 3 3 0 000 6z" />
                <path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83 2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-2 2 2 2 0 01-2-2v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83 0 2 2 0 010-2.83l.06-.06a1.65 1.65 0 00.33-1.82 1.65 1.65 0 00-1.51-1H3a2 2 0 01-2-2 2 2 0 012-2h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 010-2.83 2 2 0 012.83 0l.06.06a1.65 1.65 0 001.82.33H9a1.65 1.65 0 001-1.51V3a2 2 0 012-2 2 2 0 012 2v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 0 2 2 0 010 2.83l-.06.06a1.65 1.65 0 00-.33 1.82V9a1.65 1.65 0 001.51 1H21a2 2 0 012 2 2 2 0 01-2 2h-.09a1.65 1.65 0 00-1.51 1z" />
              </svg>
            </div>
            <h2 className="home-card-title">管理中心</h2>
            <p className="home-card-desc">管理岗位数据、数据来源和知识库，维护平台核心内容</p>
            <div className="home-card-tags">
              <span className="tag">岗位大厅</span>
              <span className="tag">数据来源</span>
              <span className="tag">知识库</span>
            </div>
            <span className="home-card-arrow">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M5 12h14M12 5l7 7-7 7" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </span>
          </Link>
        </div>

        {/* Quick link to chat */}
        <div className="home-footer">
          <Link href="/chat" className="home-chat-link">
            或者直接与 <strong>AI 助手</strong> 对话
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M5 12h14M12 5l7 7-7 7" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </Link>
        </div>
      </div>
    </div>
  );
}
