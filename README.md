# Self MCP Server

一个最小可用的 MCP Server，用于给前端 / 后端 / 移动端项目构建“代码索引”，并通过 MCP 暴露基础能力：

- `list_files` — 列出项目中的源文件
- `read_file_content` — 读取指定源文件内容
- `rebuild_index` — 重新扫描项目并写入本地索引（当前只保存文件列表）

后续可以在此基础上扩展：依赖图 / symbol 索引 / 多语言支持等。

## 安装依赖

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

## 启动 MCP Server（用于 Claude Desktop 等客户端）

在 Claude 配置文件中增加：

```json
{
  "mcpServers": {
    "self-mcp": {
      "command": "<项目路径>/venv/bin/python3",
      "args": ["<项目路径>/server.py"]
    }
  }
}
```

> 将 `<项目路径>` 替换成你本机的实际路径即可。

然后重启 Claude Desktop。

## 手动测试（不依赖 Claude）

目前我这边不能直接在你的终端执行命令，你可以在本地终端运行：

```bash
# 进入项目目录（请替换为你的实际路径）
cd <项目路径>
source venv/bin/activate
python server.py
```

这会以 MCP stdio 模式启动 server，方便未来用 MCP SDK 写一个小 client 来调试。

## 下一步可以做什么

- 在 `build_simple_index` 基础上：
  - 针对前端项目（如 React/Vue）解析路由 / 入口文件
  - 针对后端项目（如 Spring Boot）解析 Controller / 接口
  - 针对移动端（如 Flutter/React Native）解析页面 / 路由
- 在 index JSON 里增加：
  - `dependency_graph`（nodes + edges）
  - 每个文件的语言类型 / 行数 / 导出 symbol
- 增加更多 MCP tools，例如：
  - `get_dependency_graph`
  - `query_dependencies`
  - `find_references`
