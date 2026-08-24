# RepoPath

RepoPath 是一个帮助开发者快速理解陌生代码仓库的 Python 分析工具。它通过静态扫描、Python AST 和 Git 历史生成项目概览，帮助贡献者和编程 Agent 在阅读源码前建立整体认知。

## 功能说明

- 分析仓库文件结构、语言分布、非空行数和主要目录
- 提取 Python import，识别本地模块依赖和核心模块候选
- 识别常见 Python 入口及 `__name__ == "__main__"` 入口
- 汇总 Git 提交、贡献者、最近提交、高频修改路径和按月提交趋势
- 生成 Markdown 或 JSON 格式的项目报告
- 提供 Streamlit 页面用于交互式查看分析结果

## 使用说明

### 命令行

在仓库根目录执行，默认生成 `REPOPATH_REPORT.md`：

```powershell
python.exe -m repopath . -o REPOPATH_REPORT.md
```

也支持根目录兼容脚本：

```powershell
python.exe repopath.py . -o REPOPATH_REPORT.md
```

生成 JSON 报告：

```powershell
python.exe -m repopath . --format json -o REPOPATH_REPORT.json
```

### Streamlit UI

CLI 核心分析不依赖第三方库。使用 UI 必须先安装 Streamlit：

```powershell
python.exe -m pip install -r requirements.txt
python.exe run_streamlit.py
```

当前固定版本：`Streamlit 1.62.0`。

## 当前能力

- 支持本地目录分析
- 支持 Python、JavaScript、TypeScript、Java、Go、Rust、C/C++、Markdown、JSON 和 YAML 的基础语言识别
- 支持文件读取失败、Python 语法错误和 Git 不可用时继续生成部分报告
- CLI 与 UI 使用同一条 Core Pipeline
- Markdown 和 JSON Renderer 使用同一份结构化分析结果

## 项目结构

```text
app.py              Streamlit 页面
run_streamlit.py    Streamlit bootstrap 启动脚本
repopath/
  analyzer/         文件、Python 和 Git 分析器
  core/             Context、Pipeline、Composer 和分析服务
  interface/        CLI 入口
  model/            结构化数据模型
  provider/         文件系统和 Git 数据来源
  renderer/         Markdown 和 JSON 输出
```

Provider 提供原始数据，Analyzer 负责分析，Core Pipeline 负责调度，Composer 合并结果，Renderer 负责输出格式。`.git`、`.venv`、缓存目录和生成报告会被跳过。
