#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""精简的 MCP 服务器：根据 URL 查找文件功能。

核心功能：
- search_by_url: 根据 URL 字符串查找匹配的文件
- list_directory: 列出目录结构
"""

import asyncio
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Tuple
from urllib.parse import urlparse, unquote

from anthropic import AsyncAnthropic
from openai import AsyncOpenAI
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool


# =============================================================================
# 文件扫描配置
# =============================================================================

DEFAULT_IGNORE_DIRS = {".git", "node_modules", "dist", "build", "out", "venv", "mcp_venv", "__pycache__", ".idea", ".vscode"}
DEFAULT_EXTS = {".ts", ".tsx", ".js", ".jsx", ".vue", ".java", ".kt", ".go", ".py", ".dart", ".md"}


def scan_source_files(root: Path, ignore_dirs: List[str] | None = None) -> List[str]:
    """扫描 root 下的源文件，返回相对路径列表。"""
    if not root.is_dir():
        raise ValueError(f"project_path is not a directory: {root}")

    ignore = set(DEFAULT_IGNORE_DIRS)
    if ignore_dirs:
        ignore.update(ignore_dirs)

    results: List[str] = []

    for dirpath, dirnames, filenames in os.walk(root):
        # 过滤目录
        dirnames[:] = [d for d in dirnames if d not in ignore]

        for fname in filenames:
            ext = os.path.splitext(fname)[1]
            if ext not in DEFAULT_EXTS:
                continue
            full_path = Path(dirpath) / fname
            rel_path = full_path.relative_to(root)
            results.append(str(rel_path))

    return sorted(results)


# =============================================================================
# URL 匹配逻辑
# =============================================================================

def parse_url_path(url: str) -> Tuple[str, str, List[str]]:
    """解析 URL，提取路径信息。
    
    返回:
        (pathname, filename, path_segments)
    """
    try:
        parsed = urlparse(url)
        pathname = unquote(parsed.path)
        path_segments = [seg for seg in pathname.strip("/").split("/") if seg]
        filename = path_segments[-1] if path_segments else ""
        if filename and "." in filename:
            filename = os.path.splitext(filename)[0]
        return pathname, filename, path_segments
    except Exception:
        pathname = url.split("?")[0].split("#")[0]
        path_segments = [seg for seg in pathname.strip("/").split("/") if seg]
        filename = path_segments[-1] if path_segments else ""
        return pathname, filename, path_segments


def match_file_by_url(
    url: str,
    project_path: str,
    files: List[str],
    max_content_bytes: int = 5000
) -> List[Dict[str, Any]]:
    """根据 URL 匹配项目中的文件。
    
    匹配策略（按优先级）：
    1. 文件名精确匹配
    2. 路径段匹配
    3. 文件名包含匹配
    4. 文件内容匹配（路由配置等）
    """
    root = Path(project_path).expanduser().resolve()
    pathname, filename, path_segments = parse_url_path(url)
    
    matches: List[Dict[str, Any]] = []
    
    # 策略 1: 文件名精确匹配
    for file_path in files:
        file_name = Path(file_path).stem
        if file_name.lower() == filename.lower() and filename:
            matches.append({
                "file_path": file_path,
                "match_type": "exact_filename",
                "match_score": 100,
                "match_reason": f"文件名 '{file_name}' 与 URL 文件名 '{filename}' 精确匹配",
            })
    
    # 策略 2: 路径段匹配
    if path_segments:
        for file_path in files:
            file_path_lower = file_path.lower()
            matched_segments = []
            for seg in path_segments:
                if seg.lower() in file_path_lower:
                    matched_segments.append(seg)
            
            if matched_segments:
                score = len(matched_segments) * 20
                path_str = "/".join(path_segments).lower()
                if path_str in file_path_lower:
                    score += 30
                
                matches.append({
                    "file_path": file_path,
                    "match_type": "path_segment",
                    "match_score": score,
                    "match_reason": f"路径段 {matched_segments} 出现在文件路径中",
                })
    
    # 策略 3: 文件名包含匹配
    if filename:
        for file_path in files:
            file_name = Path(file_path).stem.lower()
            if filename.lower() in file_name or file_name in filename.lower():
                if not any(m["file_path"] == file_path and m["match_score"] >= 50 for m in matches):
                    matches.append({
                        "file_path": file_path,
                        "match_type": "filename_contains",
                        "match_score": 30,
                        "match_reason": f"文件名包含 URL 文件名 '{filename}'",
                    })
    
    # 策略 4: 文件内容匹配
    for file_path in files:
        try:
            full_path = root / file_path
            if not full_path.is_file():
                continue
            
            content = full_path.read_text(encoding="utf-8", errors="ignore")[:max_content_bytes]
            content_lower = content.lower()
            
            pathname_clean = pathname.strip("/").lower()
            pathname_with_slash = pathname.lower()
            
            matched_patterns = []
            if pathname_with_slash in content_lower:
                matched_patterns.append(f"完整路径 '{pathname}'")
            if pathname_clean and pathname_clean in content_lower:
                matched_patterns.append(f"路径 '{pathname_clean}'")
            for seg in path_segments:
                if seg and seg.lower() in content_lower:
                    matched_patterns.append(f"路径段 '{seg}'")
            
            if matched_patterns:
                lines = content.split("\n")
                matching_lines = []
                search_terms = [pathname.lower(), pathname_clean] + [seg.lower() for seg in path_segments if seg]
                
                for i, line in enumerate(lines[:100], 1):
                    line_lower = line.lower()
                    if any(term in line_lower for term in search_terms if term):
                        is_route_config = any(keyword in line_lower for keyword in [
                            "path", "route", "router", "url", "endpoint", "api"
                        ])
                        matching_lines.append((i, line.strip()[:200], is_route_config))
                        if len(matching_lines) >= 5:
                            break
                
                base_score = 25
                if any(is_route for _, _, is_route in matching_lines):
                    base_score = 40
                
                existing = next((m for m in matches if m["file_path"] == file_path), None)
                if existing:
                    if not existing.get("content_snippet"):
                        existing["content_snippet"] = "\n".join([f"  {num}: {line}" for num, line, _ in matching_lines])
                    existing["match_reason"] += f"；文件内容中包含 URL 路径（{', '.join(matched_patterns[:2])}）"
                    if base_score > existing["match_score"]:
                        existing["match_score"] = base_score
                else:
                    matches.append({
                        "file_path": file_path,
                        "match_type": "content_match",
                        "match_score": base_score,
                        "match_reason": f"文件内容中包含 URL 路径（{', '.join(matched_patterns[:2])}）",
                        "content_snippet": "\n".join([f"  {num}: {line}" for num, line, _ in matching_lines]) if matching_lines else None,
                    })
        except Exception:
            continue
    
    # 去重并按分数排序
    seen = set()
    unique_matches = []
    for match in sorted(matches, key=lambda x: x["match_score"], reverse=True):
        if match["file_path"] not in seen:
            seen.add(match["file_path"])
            unique_matches.append(match)
    
    return unique_matches[:10]


# =============================================================================
# 目录列表功能
# =============================================================================

def list_directory_structure(
    project_path: str,
    relative_path: str = "",
    max_depth: int = 3,
    ignore_dirs: List[str] | None = None
) -> Dict[str, Any]:
    """列出目录结构。
    
    返回目录树结构，包含文件和子目录。
    """
    root = Path(project_path).expanduser().resolve()
    target = root / relative_path if relative_path else root
    
    # 安全防护
    try:
        target_resolved = target.resolve()
    except FileNotFoundError:
        return {"error": f"路径不存在: {relative_path}"}
    
    if root not in target_resolved.parents and target_resolved != root:
        return {"error": "拒绝访问 project_path 之外的路径"}
    
    if not target_resolved.is_dir():
        return {"error": f"目标不是目录: {relative_path}"}
    
    ignore = set(DEFAULT_IGNORE_DIRS)
    if ignore_dirs:
        ignore.update(ignore_dirs)
    
    def build_tree(path: Path, depth: int = 0) -> Dict[str, Any]:
        if depth > max_depth:
            return None
        
        result: Dict[str, Any] = {
            "name": path.name,
            "type": "directory" if path.is_dir() else "file",
        }
        
        if path.is_dir():
            children = []
            try:
                items = sorted(path.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))
                for item in items:
                    if item.name.startswith(".") and item.name not in [".git", ".gitignore"]:
                        continue
                    if item.name in ignore:
                        continue
                    
                    child = build_tree(item, depth + 1)
                    if child:
                        children.append(child)
            except PermissionError:
                pass
            
            if children:
                result["children"] = children
        else:
            result["size"] = path.stat().st_size
            ext = path.suffix
            if ext in DEFAULT_EXTS:
                result["is_source_file"] = True
        
        return result
    
    tree = build_tree(target_resolved)
    
    return {
        "path": str(target_resolved.relative_to(root)) if target_resolved != root else ".",
        "structure": tree,
    }


# =============================================================================
# MCP Server 实现
# =============================================================================

class SelfMCPServer:
    """Self MCP Server（精简版）。"""

    def __init__(self) -> None:
        self.server = Server("self-mcp-server")
        # 初始化 Claude 客户端（从环境变量读取 API Key 和自定义端点）
        api_key = os.getenv("ANTHROPIC_API_KEY")
        base_url = os.getenv("ANTHROPIC_BASE_URL")  # 支持自定义 API 端点
        if api_key:
            # 如果 base_url 包含 /v1，需要去掉，因为 Anthropic SDK 会自动添加
            if base_url and base_url.endswith("/v1"):
                base_url = base_url.rstrip("/v1").rstrip("/")
            self.claude_client = AsyncAnthropic(
                api_key=api_key,
                base_url=base_url if base_url else None
            )
        else:
            self.claude_client = None
        
        # 初始化 DeepSeek 客户端（从环境变量读取 API Key 和自定义端点）
        deepseek_api_key = os.getenv("DEEPSEEK_API_KEY")
        deepseek_base_url = os.getenv("DEEPSEEK_BASE_URL")
        if deepseek_api_key:
            # 如果没有设置 base_url，使用默认值
            if not deepseek_base_url:
                deepseek_base_url = "https://api.deepseek.com/v1"
            # 确保 base_url 包含 /v1 路径
            elif not deepseek_base_url.endswith("/v1"):
                if deepseek_base_url.endswith("/"):
                    deepseek_base_url = deepseek_base_url + "v1"
                else:
                    deepseek_base_url = deepseek_base_url + "/v1"
            self.deepseek_client = AsyncOpenAI(
                api_key=deepseek_api_key,
                base_url=deepseek_base_url
            )
        else:
            self.deepseek_client = None
        
        self._register_tools()

    def _register_tools(self) -> None:
        @self.server.list_tools()
        async def list_tools() -> List[Tool]:
            return [
                Tool(
                    name="search_by_url",
                    description=(
                        "根据 URL 字符串在项目中查找匹配的文件。"
                        "支持多种匹配策略：文件名匹配、路径匹配、内容匹配等。"
                        "返回匹配的文件列表及相关信息，供 AI 分析使用。"
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "url": {
                                "type": "string",
                                "description": "要搜索的 URL 字符串（可以是完整 URL 或路径）",
                            },
                            "project_path": {
                                "type": "string",
                                "description": "项目根目录绝对路径",
                            },
                            "include_content": {
                                "type": "boolean",
                                "description": "是否包含匹配文件的内容片段（默认：true）",
                            },
                            "max_results": {
                                "type": "number",
                                "description": "最大返回结果数量（默认：10）",
                            },
                        },
                        "required": ["url", "project_path"],
                    },
                ),
                Tool(
                    name="list_directory",
                    description=(
                        "列出项目目录结构。"
                        "返回指定路径下的文件和子目录树形结构。"
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "project_path": {
                                "type": "string",
                                "description": "项目根目录绝对路径",
                            },
                            "relative_path": {
                                "type": "string",
                                "description": "要列出的目录相对路径（相对于 project_path，默认为根目录）",
                            },
                            "max_depth": {
                                "type": "number",
                                "description": "最大目录深度（默认：3）",
                            },
                            "ignore_dirs": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "可选的额外忽略目录列表",
                            },
                        },
                        "required": ["project_path"],
                    },
                ),
                Tool(
                    name="ask_claude",
                    description=(
                        "向 AI 模型提问并获取回答。"
                        "支持 Claude Sonnet 4.5、Llama3-8B-Instruct 和 OpenAI GPT OSS 20B 模型。"
                        "如果主模型不可用会自动回退到备选模型（默认：llama3-8b-instruct）。"
                        "需要设置 ANTHROPIC_API_KEY 和 ANTHROPIC_BASE_URL 环境变量。"
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "question": {
                                "type": "string",
                                "description": "要向 Claude 提问的问题",
                            },
                            "model": {
                                "type": "string",
                                "description": "模型名称（默认：claude-sonnet-4-5-20250929）。如果 Claude 模型不可用，会自动回退到 llama3-8b-instruct。",
                                "enum": [
                                    "claude-sonnet-4-5-20250929",
                                    "llama3-8b-instruct",
                                    "openai-gpt-oss-20b",
                                ],
                            },
                            "fallback_model": {
                                "type": "string",
                                "description": "当主模型失败时的回退模型（默认：llama3-8b-instruct）。如果主模型因权限等问题失败，会自动使用此模型。可选值：claude-sonnet-4-5-20250929、llama3-8b-instruct、openai-gpt-oss-20b。",
                            },
                            "max_tokens": {
                                "type": "number",
                                "description": "最大生成 token 数（默认：1024）",
                            },
                            "temperature": {
                                "type": "number",
                                "description": "温度参数，控制随机性（0-1，默认：1.0）",
                            },
                            "system_prompt": {
                                "type": "string",
                                "description": "可选的系统提示词，用于设置 AI 的行为",
                            },
                        },
                        "required": ["question"],
                    },
                ),
                Tool(
                    name="ask_deepseek",
                    description=(
                        "向 DeepSeek AI 模型提问并获取回答。"
                        "支持 DeepSeek 的各种模型，包括 deepseek-chat 和 deepseek-reasoner（思考模式）。"
                        "需要设置 DEEPSEEK_API_KEY 环境变量，可选设置 DEEPSEEK_BASE_URL 环境变量（默认：https://api.deepseek.com/v1）。"
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "question": {
                                "type": "string",
                                "description": "要向 DeepSeek 提问的问题",
                            },
                            "model": {
                                "type": "string",
                                "description": "DeepSeek 模型名称（默认：deepseek-chat）。支持 deepseek-chat、deepseek-reasoner 等模型。",
                                "enum": [
                                    "deepseek-chat",
                                    "deepseek-reasoner",
                                ],
                            },
                            "max_tokens": {
                                "type": "number",
                                "description": "最大生成 token 数（默认：2048）",
                            },
                            "temperature": {
                                "type": "number",
                                "description": "温度参数，控制随机性（0-2，默认：1.0）",
                            },
                            "system_prompt": {
                                "type": "string",
                                "description": "可选的系统提示词，用于设置 AI 的行为",
                            },
                            "enable_thinking": {
                                "type": "boolean",
                                "description": "是否启用思考模式（仅对 deepseek-reasoner 有效，默认：false）",
                            },
                        },
                        "required": ["question"],
                    },
                ),
            ]

        @self.server.call_tool()
        async def call_tool(name: str, arguments: Dict[str, Any]):
            if name == "search_by_url":
                return await self._handle_search_by_url(arguments)
            if name == "list_directory":
                return await self._handle_list_directory(arguments)
            if name == "ask_claude":
                return await self._handle_ask_claude(arguments)
            if name == "ask_deepseek":
                return await self._handle_ask_deepseek(arguments)

            raise ValueError(f"Unknown tool: {name}")

    async def _handle_search_by_url(self, args: Dict[str, Any]):
        url = args["url"]
        project_path = args["project_path"]
        include_content = args.get("include_content", True)
        max_results = int(args.get("max_results", 10))

        # 扫描项目文件
        root = Path(project_path).expanduser().resolve()
        files = scan_source_files(root)

        if not files:
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "url": url,
                            "matches": [],
                            "message": "项目中没有找到源文件",
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                )
            ]

        # 执行匹配
        matches = match_file_by_url(url, project_path, files)

        # 如果 include_content 为 true，读取匹配文件的内容片段
        if include_content:
            for match in matches:
                try:
                    file_path = root / match["file_path"]
                    if file_path.is_file():
                        content = file_path.read_text(encoding="utf-8", errors="ignore")
                        if "content_snippet" not in match or not match["content_snippet"]:
                            lines = content.split("\n")[:20]
                            match["content_snippet"] = "\n".join([f"  {i+1}: {line}" for i, line in enumerate(lines)])
                        match["file_size"] = len(content)
                        match["line_count"] = len(content.split("\n"))
                except Exception:
                    pass

        matches = matches[:max_results]

        result = {
            "url": url,
            "parsed_path": parse_url_path(url)[0],
            "match_count": len(matches),
            "matches": matches,
        }

        text = json.dumps(result, ensure_ascii=False, indent=2)
        return [TextContent(type="text", text=text)]

    async def _handle_list_directory(self, args: Dict[str, Any]):
        project_path = args["project_path"]
        relative_path = args.get("relative_path", "")
        max_depth = int(args.get("max_depth", 3))
        ignore_dirs = args.get("ignore_dirs") or []

        result = list_directory_structure(project_path, relative_path, max_depth, ignore_dirs)
        text = json.dumps(result, ensure_ascii=False, indent=2)
        return [TextContent(type="text", text=text)]

    async def _handle_ask_claude(self, args: Dict[str, Any]):
        """处理 AI 提问请求，支持模型回退机制。"""
        if not self.claude_client:
            error_msg = json.dumps(
                {
                    "error": "API 未配置",
                    "message": "请设置 ANTHROPIC_API_KEY 环境变量",
                },
                ensure_ascii=False,
                indent=2,
            )
            return [TextContent(type="text", text=error_msg)]

        question = args["question"]
        # 默认使用较新的模型，如果不可用会自动尝试其他模型
        model = args.get("model", "claude-sonnet-4-5-20250929")
        fallback_model = args.get("fallback_model", "llama3-8b-instruct")
        max_tokens = int(args.get("max_tokens", 1024))
        temperature = float(args.get("temperature", 1.0))
        system_prompt = args.get("system_prompt")

        # 构建消息
        messages = [{"role": "user", "content": question}]

        # 首先尝试使用主模型
        try:
            response = await self.claude_client.messages.create(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system_prompt if system_prompt else None,
                messages=messages,
            )

            # 提取回复内容
            answer = ""
            if response.content:
                for block in response.content:
                    if block.type == "text":
                        answer += block.text

            result = {
                "question": question,
                "answer": answer,
                "model": model,
                "used_fallback": False,
                "usage": {
                    "input_tokens": response.usage.input_tokens,
                    "output_tokens": response.usage.output_tokens,
                },
            }

            text = json.dumps(result, ensure_ascii=False, indent=2)
            return [TextContent(type="text", text=text)]

        except Exception as e:
            error_str = str(e)
            error_type = "未知错误"
            should_fallback = False
            
            # 判断是否需要回退
            if "403" in error_str or "permission" in error_str.lower():
                error_type = "权限错误"
                should_fallback = True
            elif "404" in error_str or "not found" in error_str.lower():
                error_type = "模型不存在"
                should_fallback = True
            elif "401" in error_str or "unauthorized" in error_str.lower():
                error_type = "认证失败"
                # 认证失败不应该回退，直接返回错误
            else:
                # 其他错误也尝试回退
                should_fallback = True

            # 如果需要回退且回退模型与主模型不同，尝试使用回退模型
            if should_fallback and fallback_model and fallback_model != model:
                try:
                    # 尝试使用回退模型
                    response = await self.claude_client.messages.create(
                        model=fallback_model,
                        max_tokens=max_tokens,
                        temperature=temperature,
                        system=system_prompt if system_prompt else None,
                        messages=messages,
                    )

                    # 提取回复内容
                    answer = ""
                    if response.content:
                        for block in response.content:
                            if block.type == "text":
                                answer += block.text

                    result = {
                        "question": question,
                        "answer": answer,
                        "model": fallback_model,
                        "original_model": model,
                        "used_fallback": True,
                        "fallback_reason": error_type,
                        "usage": {
                            "input_tokens": response.usage.input_tokens,
                            "output_tokens": response.usage.output_tokens,
                        },
                    }

                    text = json.dumps(result, ensure_ascii=False, indent=2)
                    return [TextContent(type="text", text=text)]

                except Exception as fallback_error:
                    # 回退模型也失败了，返回详细错误信息
                    error_msg = json.dumps(
                        {
                            "error": "调用 API 失败",
                            "error_type": error_type,
                            "message": f"主模型 '{model}' 失败，回退模型 '{fallback_model}' 也失败",
                            "original_error": error_str[:200] if len(error_str) > 200 else error_str,
                            "fallback_error": str(fallback_error)[:200],
                            "question": question,
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                    return [TextContent(type="text", text=error_msg)]
            else:
                # 不需要回退或回退失败，返回原始错误
                error_msg = json.dumps(
                    {
                        "error": "调用 API 失败",
                        "error_type": error_type,
                        "message": f"模型 '{model}' 调用失败" + (f"，已尝试回退到 '{fallback_model}'" if should_fallback else ""),
                        "model": model,
                        "question": question,
                        "raw_error": error_str[:200] if len(error_str) > 200 else error_str,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                return [TextContent(type="text", text=error_msg)]

    async def _handle_ask_deepseek(self, args: Dict[str, Any]):
        """处理 DeepSeek AI 提问请求。"""
        if not self.deepseek_client:
            error_msg = json.dumps(
                {
                    "error": "API 未配置",
                    "message": "请设置 DEEPSEEK_API_KEY 环境变量（可选设置 DEEPSEEK_BASE_URL）",
                },
                ensure_ascii=False,
                indent=2,
            )
            return [TextContent(type="text", text=error_msg)]

        question = args["question"]
        model = args.get("model", "deepseek-chat")
        max_tokens = int(args.get("max_tokens", 2048))
        temperature = float(args.get("temperature", 1.0))
        system_prompt = args.get("system_prompt")
        enable_thinking = args.get("enable_thinking", False)

        # 构建消息
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": question})

        try:
            # 准备请求参数
            request_params = {
                "model": model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
            
            # 如果启用思考模式，添加到 extra_body
            if enable_thinking and model == "deepseek-reasoner":
                request_params["extra_body"] = {"enable_thinking": True}

            response = await self.deepseek_client.chat.completions.create(**request_params)

            # 提取回复内容
            answer = ""
            if response.choices and len(response.choices) > 0:
                answer = response.choices[0].message.content or ""

            result = {
                "question": question,
                "answer": answer,
                "model": model,
                "usage": {
                    "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                    "completion_tokens": response.usage.completion_tokens if response.usage else 0,
                    "total_tokens": response.usage.total_tokens if response.usage else 0,
                },
            }

            if enable_thinking:
                result["enable_thinking"] = True

            text = json.dumps(result, ensure_ascii=False, indent=2)
            return [TextContent(type="text", text=text)]

        except Exception as e:
            error_str = str(e)
            error_msg = json.dumps(
                {
                    "error": "调用 DeepSeek API 失败",
                    "message": f"模型 '{model}' 调用失败",
                    "model": model,
                    "question": question,
                    "raw_error": error_str[:500] if len(error_str) > 500 else error_str,
                },
                ensure_ascii=False,
                indent=2,
            )
            return [TextContent(type="text", text=error_msg)]


async def main() -> None:
    server = SelfMCPServer()
    async with stdio_server() as (read_stream, write_stream):
        init_options = server.server.create_initialization_options()
        await server.server.run(
            read_stream,
            write_stream,
            initialization_options=init_options,
        )


if __name__ == "__main__":
    asyncio.run(main())
