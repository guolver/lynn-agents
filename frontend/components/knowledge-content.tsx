'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';

type Knowledge = {
  id: string;
  category: string;
  title: string;
  content: string;
  source_file: string | null;
  source_format: string;
  has_embedding: boolean;
  created_at: string;
  updated_at: string;
};

type Category = {
  id: string;
  name: string;
};

const CATEGORIES: Category[] = [
  { id: 'algorithm', name: '算法与数据结构' },
  { id: 'system_design', name: '系统设计' },
  { id: 'database', name: '数据库' },
  { id: 'network', name: '网络' },
  { id: 'os', name: '操作系统' },
  { id: 'language', name: '编程语言' },
  { id: 'framework', name: '框架' },
  { id: 'devops', name: 'DevOps' },
];

const CATEGORY_MAP = Object.fromEntries(CATEGORIES.map((c) => [c.id, c.name]));

export function KnowledgeContent() {
  const router = useRouter();
  const [knowledge, setKnowledge] = useState<Knowledge[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filterCategory, setFilterCategory] = useState<string>('');

  // Upload modal state
  const [showUpload, setShowUpload] = useState(false);
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploadCategory, setUploadCategory] = useState('algorithm');
  const [uploadTitle, setUploadTitle] = useState('');
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);

  // Edit modal state
  const [editItem, setEditItem] = useState<Knowledge | null>(null);
  const [editTitle, setEditTitle] = useState('');
  const [editCategory, setEditCategory] = useState('');
  const [editContent, setEditContent] = useState('');
  const [saving, setSaving] = useState(false);
  const [editError, setEditError] = useState<string | null>(null);

  // Delete state
  const [deletingId, setDeletingId] = useState<string | null>(null);

  async function loadKnowledge() {
    setLoading(true);
    setError(null);
    try {
      const params = filterCategory ? `?category=${filterCategory}` : '';
      const res = await fetch(`/api/interview/knowledge${params}`);
      if (res.status === 401) {
        router.push('/login?redirect=/interview/knowledge');
        return;
      } else if (res.status === 403) {
        setError('没有访问权限');
      } else if (!res.ok) {
        setError('加载失败');
      } else {
        const data: Knowledge[] = await res.json();
        setKnowledge(data);
      }
    } catch {
      setError('API 不可用');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const params = filterCategory ? `?category=${filterCategory}` : '';
        const res = await fetch(`/api/interview/knowledge${params}`);
        if (cancelled) return;
        if (res.status === 401) {
          router.push('/login?redirect=/interview/knowledge');
          return;
        } else if (res.status === 403) {
          setError('没有访问权限');
        } else if (!res.ok) {
          setError('加载失败');
        } else {
          const data: Knowledge[] = await res.json();
          setKnowledge(data);
        }
      } catch {
        if (!cancelled) setError('API 不可用');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [filterCategory, router]);

  function openUploadModal() {
    setUploadFile(null);
    setUploadCategory('algorithm');
    setUploadTitle('');
    setUploadError(null);
    setShowUpload(true);
  }

  function closeUploadModal() {
    if (uploading) return;
    setShowUpload(false);
  }

  async function handleUpload(e: React.FormEvent) {
    e.preventDefault();
    if (!uploadFile) {
      setUploadError('请选择文件');
      return;
    }
    setUploading(true);
    setUploadError(null);
    try {
      const formData = new FormData();
      formData.append('file', uploadFile);
      formData.append('category', uploadCategory);
      if (uploadTitle.trim()) {
        formData.append('title', uploadTitle.trim());
      }

      const res = await fetch('/api/interview/knowledge', {
        method: 'POST',
        body: formData,
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setUploadError(data.detail || '上传失败');
      } else {
        setShowUpload(false);
        loadKnowledge();
      }
    } catch {
      setUploadError('API 不可用');
    } finally {
      setUploading(false);
    }
  }

  function openEditModal(item: Knowledge) {
    setEditItem(item);
    setEditTitle(item.title);
    setEditCategory(item.category);
    setEditContent(item.content);
    setEditError(null);
  }

  function closeEditModal() {
    if (saving) return;
    setEditItem(null);
  }

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    if (!editItem) return;
    setSaving(true);
    setEditError(null);
    try {
      const res = await fetch(`/api/interview/knowledge/${editItem.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title: editTitle.trim(),
          category: editCategory,
          content: editContent,
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setEditError(data.detail || '保存失败');
      } else {
        setEditItem(null);
        loadKnowledge();
      }
    } catch {
      setEditError('API 不可用');
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(id: string) {
    if (!confirm('确定要删除这条知识吗？')) return;
    setDeletingId(id);
    try {
      const res = await fetch(`/api/interview/knowledge/${id}`, { method: 'DELETE' });
      if (res.ok) {
        setKnowledge((prev) => prev.filter((k) => k.id !== id));
      }
    } finally {
      setDeletingId(null);
    }
  }

  function formatDate(dateStr: string) {
    if (!dateStr) return '—';
    return new Date(dateStr).toLocaleDateString('zh-CN', {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  }

  return (
    <div className="ik-layout">
      <div className="ik-header">
        <div>
          <h1 className="ik-title">知识库</h1>
          <p className="ik-subtitle">管理面试题目、技术知识点和参考答案</p>
        </div>
        {!error && (
          <div className="ik-header-actions">
            <button className="ik-add-btn" type="button" onClick={openUploadModal}>
              上传知识
            </button>
          </div>
        )}
      </div>

      {!error && (
        <div className="ik-filters">
          <select
            className="ik-filter-select"
            value={filterCategory}
            onChange={(e) => setFilterCategory(e.target.value)}
          >
            <option value="">全部分类</option>
            {CATEGORIES.map((cat) => (
              <option key={cat.id} value={cat.id}>
                {cat.name}
              </option>
            ))}
          </select>
        </div>
      )}

      {error ? (
        <div className="ik-empty">{error}</div>
      ) : loading ? (
        <div className="ik-empty">加载中...</div>
      ) : knowledge.length === 0 ? (
        <div className="ik-empty">暂无知识库内容，点击「上传知识」添加</div>
      ) : (
        <div className="ik-table-wrap">
          <table className="ik-table">
            <thead>
              <tr>
                <th>标题</th>
                <th>分类</th>
                <th>格式</th>
                <th>向量化</th>
                <th>更新时间</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {knowledge.map((item) => (
                <tr key={item.id}>
                  <td className="ik-title-cell" title={item.title}>
                    {item.title}
                  </td>
                  <td>
                    <span className="ik-category-badge">{CATEGORY_MAP[item.category] || item.category}</span>
                  </td>
                  <td>{item.source_format}</td>
                  <td>{item.has_embedding ? '是' : '否'}</td>
                  <td>{formatDate(item.updated_at)}</td>
                  <td className="ik-actions">
                    <button className="ik-edit-btn" onClick={() => openEditModal(item)}>
                      编辑
                    </button>
                    <button
                      className="ik-delete-btn"
                      disabled={deletingId === item.id}
                      onClick={() => handleDelete(item.id)}
                    >
                      {deletingId === item.id ? '删除中...' : '删除'}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Upload Modal */}
      {showUpload && (
        <div className="ik-modal-backdrop" onClick={closeUploadModal}>
          <div
            className="ik-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="ik-upload-title"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="ik-modal-header">
              <h2 id="ik-upload-title" className="ik-modal-title">
                上传知识
              </h2>
              <button className="ik-modal-close" type="button" aria-label="关闭" onClick={closeUploadModal}>
                ×
              </button>
            </div>
            <form className="ik-form" onSubmit={handleUpload}>
              <label className="ik-field">
                <span className="ik-field-label">选择文件</span>
                <input
                  className="ik-input"
                  type="file"
                  accept=".md,.pdf,.json,.txt"
                  onChange={(e) => setUploadFile(e.target.files?.[0] || null)}
                />
                <span className="ik-field-hint">支持 .md, .pdf, .json, .txt 格式</span>
              </label>
              <label className="ik-field">
                <span className="ik-field-label">分类</span>
                <select
                  className="ik-input"
                  value={uploadCategory}
                  onChange={(e) => setUploadCategory(e.target.value)}
                >
                  {CATEGORIES.map((cat) => (
                    <option key={cat.id} value={cat.id}>
                      {cat.name}
                    </option>
                  ))}
                </select>
              </label>
              <label className="ik-field">
                <span className="ik-field-label">标题（可选，留空则从文件提取）</span>
                <input
                  className="ik-input"
                  placeholder="例如：常见排序算法"
                  value={uploadTitle}
                  onChange={(e) => setUploadTitle(e.target.value)}
                />
              </label>
              {uploadError && <div className="ik-form-error">{uploadError}</div>}
              <div className="ik-form-actions">
                <button className="ik-cancel-btn" type="button" disabled={uploading} onClick={closeUploadModal}>
                  取消
                </button>
                <button className="ik-submit-btn" type="submit" disabled={uploading}>
                  {uploading ? '上传中...' : '上传'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Edit Modal */}
      {editItem && (
        <div className="ik-modal-backdrop" onClick={closeEditModal}>
          <div
            className="ik-modal ik-modal-lg"
            role="dialog"
            aria-modal="true"
            aria-labelledby="ik-edit-title"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="ik-modal-header">
              <h2 id="ik-edit-title" className="ik-modal-title">
                编辑知识
              </h2>
              <button className="ik-modal-close" type="button" aria-label="关闭" onClick={closeEditModal}>
                ×
              </button>
            </div>
            <form className="ik-form" onSubmit={handleSave}>
              <label className="ik-field">
                <span className="ik-field-label">标题</span>
                <input
                  className="ik-input"
                  required
                  value={editTitle}
                  onChange={(e) => setEditTitle(e.target.value)}
                />
              </label>
              <label className="ik-field">
                <span className="ik-field-label">分类</span>
                <select className="ik-input" value={editCategory} onChange={(e) => setEditCategory(e.target.value)}>
                  {CATEGORIES.map((cat) => (
                    <option key={cat.id} value={cat.id}>
                      {cat.name}
                    </option>
                  ))}
                </select>
              </label>
              <label className="ik-field">
                <span className="ik-field-label">内容</span>
                <textarea
                  className="ik-textarea"
                  rows={12}
                  required
                  value={editContent}
                  onChange={(e) => setEditContent(e.target.value)}
                />
              </label>
              {editError && <div className="ik-form-error">{editError}</div>}
              <div className="ik-form-actions">
                <button className="ik-cancel-btn" type="button" disabled={saving} onClick={closeEditModal}>
                  取消
                </button>
                <button className="ik-submit-btn" type="submit" disabled={saving}>
                  {saving ? '保存中...' : '保存'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
