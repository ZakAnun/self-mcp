# Self MCP Server

一个功能丰富的 MCP Server，提供项目文件搜索、目录结构查看和 AI 模型访问能力：

## 核心功能，用于给前端 / 后端 / 移动端项目构建“代码索引”，并通过 MCP 暴露基础能力：

- `search_by_url` — 根据 URL 字符串查找匹配的文件（支持文件名、路径、内容匹配）
- `list_directory` — 列出项目目录结构（树形结构）
- `ask_claude` — 向 Claude 等 AI 模型提问（支持多种模型和回退机制）
- `ask_deepseek` — 向 DeepSeek AI 模型提问（支持 deepseek-chat 和 deepseek-reasoner）

## 环境配置

### 安装依赖

```bash
# 进入项目目录（请替换为你的实际路径）
cd <项目路径>

# 创建虚拟环境（如果还没有创建）
python3 -m venv venv

# 激活虚拟环境
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt
```

### 配置 API Keys（可选）

如果需要使用 AI 模型功能，请设置相应的环境变量：

```bash
# Claude API（用于 ask_claude）
export ANTHROPIC_API_KEY='your_anthropic_api_key'
export ANTHROPIC_BASE_URL='https://your-api-endpoint.com'  # 可选，支持自定义端点

# DeepSeek API（用于 ask_deepseek）
export DEEPSEEK_API_KEY='your_deepseek_api_key'
export DEEPSEEK_BASE_URL='https://api.deepseek.com/v1'  # 可选，支持自定义端点（默认：https://api.deepseek.com/v1）
```

> 注意：如果不设置 API Keys，对应的 AI 功能将不可用，但文件搜索和目录列表功能仍然可用。

## 启动 MCP Server（用于 Claude Desktop 等客户端）

### 配置 Claude Desktop

在 Claude Desktop 配置文件中增加 MCP 服务器配置：

**配置文件位置：**
- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`

**配置内容：**

```json
{
  "mcpServers": {
    "self-mcp": {
      "command": "<项目路径>/venv/bin/python3",
      "args": ["<项目路径>/server.py"],
      "env": {
        "DEEPSEEK_API_KEY": "your_deepseek_api_key",
        "DEEPSEEK_BASE_URL": "https://api.deepseek.com/v1"
      }
    }
  }
}
```

> 将 `<项目路径>` 替换成你本机的实际路径即可。

### 让新功能生效

**重要：** 添加或修改 `ask_deepseek` 功能后，需要：

1. **完全退出并重启 Claude Desktop**
   - macOS: `Cmd + Q` 完全退出，然后重新打开
   - 或者右键 Dock 图标 → 退出，然后重新启动

2. **在 Claude Desktop 中测试**
   - 打开新对话
   - 尝试使用 `ask_deepseek` 工具

## 手动测试（不依赖 Claude）

目前我这边不能直接在你的终端执行命令，你可以在本地终端运行：

```bash
# 进入项目目录（请替换为你的实际路径）
cd <项目路径>
source venv/bin/activate
python server.py
```

这会以 MCP stdio 模式启动 server，方便未来用 MCP SDK 写一个小 client 来调试。

## 功能说明

### search_by_url

根据 URL 字符串在项目中查找匹配的文件，支持多种匹配策略：
- 文件名精确匹配
- 路径段匹配
- 文件名包含匹配
- 文件内容匹配（路由配置等）

### list_directory

列出项目的目录结构，返回树形结构，支持：
- 指定相对路径
- 控制最大深度
- 自定义忽略目录

### ask_claude

向 AI 模型提问，支持：
- Claude Sonnet 4.5 模型
- Llama3-8B-Instruct 模型
- OpenAI GPT OSS 20B 模型
- 自动回退机制（主模型失败时使用备选模型）
- 自定义系统提示词、温度、最大 token 数等参数

### ask_deepseek

向 DeepSeek AI 模型提问，支持：
- `deepseek-chat` - 标准对话模型
- `deepseek-reasoner` - 思考模式模型（支持 enable_thinking 参数）
- 自定义系统提示词、温度、最大 token 数等参数
