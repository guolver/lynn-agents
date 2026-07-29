"""文件解析沙箱服务入口。

独立部署的 FastAPI 服务，在隔离容器中运行。
"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .config import SUPPORTED_FORMATS, ParserConfig, get_config
from .parsers import PARSER_REGISTRY, get_parser
from .security import FileValidationError, validate_file

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)


class ParseResponse(BaseModel):
    """解析响应"""

    success: bool
    data: dict[str, Any] | None = None
    error: dict[str, str] | None = None


class HealthResponse(BaseModel):
    """健康检查响应"""

    status: str
    version: str


class FormatInfo(BaseModel):
    """格式信息"""

    extension: str
    mime_type: str
    max_size_mb: int


class FormatsResponse(BaseModel):
    """支持格式列表响应"""

    formats: list[FormatInfo]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    logger.info("File parser sandbox starting...")
    logger.info(f"Supported formats: {list(PARSER_REGISTRY.keys())}")
    yield
    logger.info("File parser sandbox shutting down...")


app = FastAPI(
    title="File Parser Sandbox",
    description="Isolated file parsing service with security protections",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health", response_model=HealthResponse)
async def health():
    """健康检查"""
    return HealthResponse(status="healthy", version="1.0.0")


@app.get("/formats", response_model=FormatsResponse)
async def list_formats():
    """返回支持的文件格式列表"""
    formats = []
    for mime, info in SUPPORTED_FORMATS.items():
        for ext in info["extensions"]:
            formats.append(
                FormatInfo(
                    extension=ext,
                    mime_type=mime,
                    max_size_mb=info["max_size_mb"],
                )
            )
    return FormatsResponse(formats=formats)


@app.post("/parse", response_model=ParseResponse)
async def parse_file(
    file: UploadFile = File(...),
    options: str = Form(default="{}"),
):
    """
    解析上传的文件。

    - 验证文件类型和大小
    - 使用对应解析器提取文本
    - 返回结构化结果
    """
    start_time = time.time()
    config = get_config()

    try:
        # 读取文件内容
        file_bytes = await file.read()
        filename = file.filename or "unknown"

        logger.info(f"Parsing file: {filename}, size: {len(file_bytes)} bytes")

        # 验证文件
        file_info = validate_file(file_bytes, filename, config)

        logger.info(
            f"File validated: mime={file_info.mime_type}, parser={file_info.parser_name}"
        )

        # 获取解析器
        parser_cls = get_parser(file_info.parser_name)
        parser = parser_cls(config)

        # 解析文件
        result = parser.parse(file_bytes, filename)

        # 添加解析时间
        parse_time_ms = int((time.time() - start_time) * 1000)
        result.metadata["parse_time_ms"] = parse_time_ms

        logger.info(
            f"Parse completed: {filename}, "
            f"chunks={len(result.chunks)}, "
            f"time={parse_time_ms}ms"
        )

        return ParseResponse(
            success=True,
            data=result.to_dict(),
        )

    except FileValidationError as e:
        logger.warning(f"File validation failed: {e.code} - {e.message}")
        return JSONResponse(
            status_code=400,
            content=ParseResponse(
                success=False,
                error={"code": e.code, "message": e.message},
            ).model_dump(),
        )

    except ValueError as e:
        logger.warning(f"Parse error: {e}")
        return JSONResponse(
            status_code=400,
            content=ParseResponse(
                success=False,
                error={"code": "PARSE_ERROR", "message": str(e)},
            ).model_dump(),
        )

    except Exception as e:
        logger.exception(f"Unexpected error parsing file: {e}")
        return JSONResponse(
            status_code=500,
            content=ParseResponse(
                success=False,
                error={"code": "INTERNAL_ERROR", "message": "Internal parsing error"},
            ).model_dump(),
        )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8001)
