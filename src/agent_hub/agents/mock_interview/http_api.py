"""面试 Agent REST API。"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from ...core.security import Principal, Role, require_roles

router = APIRouter(prefix="/api/v1/interview", tags=["interview"])


# -------------------------------------------------------------------------
# 依赖注入
# -------------------------------------------------------------------------


def get_interview_service(request: Request, principal: Principal = require_roles(Role.USER)):
    """为每个请求创建租户隔离的 InterviewService。"""
    from sqlalchemy.orm import sessionmaker

    from .repository import InterviewRepository
    from .service import InterviewService

    repo = request.app.state.part_time_repository
    # 创建会话工厂
    session_factory = sessionmaker(bind=repo._engine)

    # 创建租户隔离的仓储
    interview_repo = InterviewRepository(session_factory, principal.tenant_id)

    # 获取 embedding 函数
    embed_fn = getattr(request.app.state, "embed_fn", None)

    return InterviewService(interview_repo, embed_fn=embed_fn)


# -------------------------------------------------------------------------
# 请求/响应模型
# -------------------------------------------------------------------------


class KnowledgeUpdate(BaseModel):
    title: str | None = None
    content: str | None = None
    category: str | None = None


class SessionCreate(BaseModel):
    target_role: str
    difficulty: str = "medium"
    category: str | None = None


class MessageCreate(BaseModel):
    content: str


# -------------------------------------------------------------------------
# 知识库 API
# -------------------------------------------------------------------------


@router.get("/knowledge")
def list_knowledge(
    category: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    service=Depends(get_interview_service),
) -> list[dict[str, Any]]:
    """列出知识库文档。"""
    return service.list_knowledge(category=category, limit=limit)


@router.get("/knowledge/{knowledge_id}")
def get_knowledge(
    knowledge_id: str,
    service=Depends(get_interview_service),
):
    """获取单条知识库文档。"""
    result = service.get_knowledge(knowledge_id)
    if not result:
        return JSONResponse(status_code=404, content={"detail": "Knowledge not found"})
    return result


@router.post("/knowledge")
async def upload_knowledge(
    file: UploadFile = File(...),
    category: str = Form(...),
    title: str | None = Form(None),
    service=Depends(get_interview_service),
):
    """上传知识库文件。"""
    content = await file.read()
    try:
        results = service.upload_knowledge(
            file_content=content,
            text_content=None,
            filename=file.filename or "unknown.txt",
            category=category,
            title=title,
        )
        return {"created": len(results), "items": results}
    except ValueError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    except Exception as exc:
        return JSONResponse(status_code=500, content={"detail": str(exc)})


@router.put("/knowledge/{knowledge_id}")
def update_knowledge(
    knowledge_id: str,
    body: KnowledgeUpdate,
    service=Depends(get_interview_service),
):
    """更新知识库文档。"""
    result = service.update_knowledge(
        knowledge_id,
        title=body.title,
        content=body.content,
        category=body.category,
    )
    if not result:
        return JSONResponse(status_code=404, content={"detail": "Knowledge not found"})
    return result


@router.delete("/knowledge/{knowledge_id}")
def delete_knowledge(
    knowledge_id: str,
    service=Depends(get_interview_service),
):
    """删除知识库文档。"""
    if service.delete_knowledge(knowledge_id):
        return {"status": "deleted"}
    return JSONResponse(status_code=404, content={"detail": "Knowledge not found"})


# -------------------------------------------------------------------------
# 会话 API
# -------------------------------------------------------------------------


@router.get("/sessions")
def list_sessions(
    limit: int = Query(50, ge=1, le=100),
    service=Depends(get_interview_service),
) -> list[dict[str, Any]]:
    """列出面试会话。"""
    return service.list_sessions(limit=limit)


@router.post("/sessions")
def create_session(
    body: SessionCreate,
    service=Depends(get_interview_service),
    principal: Principal = require_roles(Role.USER),
):
    """创建新面试会话。"""
    return service.create_session(
        target_role=body.target_role,
        difficulty=body.difficulty,
        actor=principal.actor_id,
        category=body.category,
    )


@router.get("/sessions/{session_id}")
def get_session(
    session_id: str,
    service=Depends(get_interview_service),
):
    """获取会话详情及消息。"""
    result = service.get_session(session_id)
    if not result:
        return JSONResponse(status_code=404, content={"detail": "Session not found"})
    return result


@router.delete("/sessions/{session_id}")
def delete_session(
    session_id: str,
    service=Depends(get_interview_service),
):
    """删除会话。"""
    if service.delete_session(session_id):
        return {"status": "deleted"}
    return JSONResponse(status_code=404, content={"detail": "Session not found"})


@router.post("/sessions/{session_id}/messages")
def send_message(
    session_id: str,
    body: MessageCreate,
    service=Depends(get_interview_service),
):
    """发送消息并获取面试官回复（SSE 流式）。"""

    def generate():
        for event in service.stream_response(session_id, body.content):
            event_type = event["event"]
            data = json.dumps(event["data"], ensure_ascii=False)
            yield f"event: {event_type}\ndata: {data}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/sessions/{session_id}/end")
def end_session(
    session_id: str,
    service=Depends(get_interview_service),
):
    """结束面试并生成综合评价。"""
    result = service.end_session(session_id)
    if not result:
        return JSONResponse(status_code=404, content={"detail": "Session not found"})
    return result


# -------------------------------------------------------------------------
# 知识库分类
# -------------------------------------------------------------------------


@router.get("/categories")
def list_categories() -> list[dict[str, str]]:
    """列出支持的知识库分类。"""
    return [
        {"id": "algorithm", "name": "算法与数据结构"},
        {"id": "system_design", "name": "系统设计"},
        {"id": "database", "name": "数据库"},
        {"id": "network", "name": "网络"},
        {"id": "os", "name": "操作系统"},
        {"id": "language", "name": "编程语言"},
        {"id": "framework", "name": "框架"},
        {"id": "devops", "name": "DevOps"},
    ]
