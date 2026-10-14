# RepoPath

> 帮助开发者和编程 Agent 快速理解陌生代码仓库的本地多语言分析工具。

RepoPath 扫描本地目录或公开 GitHub 仓库，分析代码结构、模块依赖和 Git 历史，生成**阅读优先级、推荐阅读顺序、变更关注度和 Markdown / JSON 报告**。

Release 中的版本为纯CLI版。如需使用UI，请先clone项目或点击以下链接体验

## 🚀立即体验

无需本地部署，点击链接即可使用：

 ### [Repopath](https://repopath.streamlit.app)


## 1. 功能

* **代码分析**：文件结构、代码规模、语言分布
* **Python**：AST、函数、类、import、入口和模块依赖
* **C++**：include、函数、类/结构体、命名空间和入口；可选语义分析 PoC 支持跨文件定义与直接调用
* **依赖分析**：统一依赖图、循环依赖、孤立模块
* **阅读导航**：阅读优先级、推荐阅读顺序、入口路径
* **变更关注**：结合依赖关系和 Git 活跃度定位重点模块
* **Git 分析**：提交趋势、churn、热点文件、共同修改和贡献者
* **GitHub**：支持公开仓库、分支、标签和提交 SHA
* **报告**：Markdown / JSON
* **UI**：Streamlit 可视化分析工作台

## 2. 快速开始

要求 **Python 3.11+**。

### CLI

核心 CLI 无需第三方依赖：

```powershell
python -m repopath .
python -m repopath . -o report.md
python -m repopath . --format json -o report.json
```

查看帮助：

```powershell
python -m repopath -h
```

### Streamlit

```powershell
python -m pip install -r requirements.txt
python run_streamlit.py
```

支持 `fast`、`standard`、`deep` 三种分析模式。

| 模式 | 分析范围 |
| --- | --- |
| `fast` | 文件扫描、语言和目录统计 |
| `standard` | 文件统计、Python/C++ 结构与局部依赖、Git 历史 |
| `deep` | 全部分析，包括统一依赖图、阅读顺序、模块评分和变更关注 |

`standard` 不运行统一依赖图和洞察分析。如需完整阅读导航，使用 `--profile deep`。

### GitHub

```powershell
python -m repopath owner/repository
python -m repopath owner/repository --ref main
```

GitHub 分析会固定到提交 SHA 后下载快照进行静态分析，**不会克隆仓库或执行目标代码**。

### C++ 语义分析（PoC）

默认 `basic` 模式保持原有基础分析，无需安装额外依赖。当前分支提供可选的 `libclang` 模式，用于本地仓库的跨文件符号定位和直接调用分析；这不表示已发布版本具备该能力。

原有发布流程仍生成基础 CLI；独立 PoC 打包流程验证包含 libclang 的可执行文件。使用已打包的可执行文件无需 Python/pip；下面的依赖安装步骤仅用于源码运行。

PoC 的 CI 覆盖 Windows/Linux 与 Python 3.11–3.14，并用 Python 3.13 验证目录版和单文件版。两个平台都会搬移产物并隐藏安装环境中的 libclang 后，检查实际分析结果。

Windows 会把 libclang 和所需 C++ 运行库一起打包，用户无需额外安装运行库。CI 先运行 `scripts/prepare_windows_runtime.py`，下载固定版本的微软官方包并校验文件内容，仅解包，不安装系统组件；随后用 `scripts/prepare_cpp_package.py --runtime-dir build/windows-runtime-source/x64` 收集 DLL 和许可。本地也可省略 `--runtime-dir`，从 Visual Studio 的可再分发目录收集。

运行库缺失或版本过旧时停止构建；验收会核对随包 DLL 的依赖和文件哈希，并检查单文件启动入口不依赖外部 C++ 运行库。两种构建都需要读取 `repopath.nuitka-package.config.yml` 和准备步骤生成的 `build/cpp-runtime.nuitka-package.config.yml`；完整命令见 `.github/workflows/cpp-poc.yml`。

Linux 本轮以 Ubuntu 22.04/x64 为基线。固定版本 libclang 的 Linux x64 包已静态包含 C++ 运行库，仍依赖系统 glibc；完整程序的系统要求以最终产物检查为准。

源码运行时，先安装配套依赖，再提供项目的 `compile_commands.json`：

```powershell
python -m pip install -r requirements-cpp.txt
python -m repopath . --cpp-backend libclang --compile-commands build/compile_commands.json --format json -o report.json
python -m repopath . --cpp-backend libclang --detail full -o report.md
```

也可以运行 `python scripts/check_cpp_semantics.py --mode source`，自动准备不依赖系统头文件的小型跨文件样例并检查语义结果。请仅安装配套的 `libclang` 依赖，不要再混装另一份 `clang` Python 包。

未指定 `--compile-commands` 时，依次查找仓库根目录和 `build/`。相对路径按被分析仓库解析。数据库需要记录源文件、工作目录和编译参数；建议使用 `arguments` 数组。RepoPath 只读取这些参数，不执行编译或构建命令。

PoC 目前接受 GCC/Clang 风格参数。Windows 必须使用 `arguments` 数组，暂不支持 `command` 字符串、MSVC/clang-cl 参数、编译器 wrapper、响应文件或同一源文件的多套编译配置；POSIX 上只接受不带 shell 展开的简单 `command`。因此常见构建工具导出的数据库也可能需要调整。依赖中的 Clang 库不会替项目补齐标准库、SDK、Clang 内置头文件资源目录或生成头文件，这些文件仍须能按编译参数找到。

未找到依赖、数据库或可解析条目时，会生成带原因的失败报告并返回非零退出码，不会悄悄退回 `basic`。编译器诊断可能造成部分覆盖：报告标记 `partial` 并列出问题文件，不采纳有错误编译单元的符号和调用；此时 CLI 保留报告并提示部分覆盖。若只需基础扫描，可显式使用 `--cpp-backend basic`。

语义结果目前在 JSON 和 Markdown 中展示：跨文件声明/定义按符号身份归并，直接调用保留调用方、目标与源码位置。它不等于完整运行时调用图；函数指针、虚调用、lambda 内部调用和内部链接符号等尚不提供完整关系。调用关系单独输出，不混入现有 include 依赖图和阅读评分。

## 3. 配置

在仓库根目录创建 `.repopath.toml`：

```toml
[scan]
profile = "deep"
max_file_size = 2097152
exclude = ["generated/*", "*.min.js"]

[git]
period = "all"

[cpp]
backend = "basic"
# 使用 libclang 时可指定；省略则查找根目录和 build/
# compile_commands = "build/compile_commands.json"

[github]
archive_max_mb = 100
file_limit = 10000

[report]
limit = 50
reading_limit = 10
include_file_list = false
```

配置优先级：

```text
CLI > .repopath.toml > 默认值
```

## 4. 项目结构

```text
.
├── app.py
├── repopath.py
├── run_streamlit.py
├── repopath/
│   ├── analyzer/       # 文件、Python、C++、Git、依赖和洞察分析
│   ├── core/           # Pipeline 和核心服务
│   ├── interface/      # CLI / Streamlit
│   ├── model/          # 数据模型
│   ├── provider/       # 文件系统、Git、GitHub
│   └── renderer/       # Markdown / JSON
├── tests/
├── requirements.txt
└── requirements-dev.txt
```

## 5. 报告

Markdown 默认提供仓库概览、入口、推荐阅读、依赖和变更关注等摘要。

生成完整 Markdown：

```powershell
python -m repopath . --detail full -o report.md
```

JSON 始终输出完整结构，适合脚本、CI/CD 和 Agent 集成。

C++ 语义报告新增 `backend`、`analysis_level`、`semantic_status`、`coverage` 和 `diagnostics`。`semantic_symbols` 提供按 USR（Clang 符号身份）归并的声明与定义，`direct_calls` 提供已确定目标的直接调用；原有 `cpp.symbols` 保持基础符号列表格式。`completed` 表示分析阶段运行完成，是否完整覆盖仍需查看 `semantic_status`、编译单元状态与未覆盖文件。JSON 保存全部结果，Markdown 的语义列表按报告数量设置限量展示。

报告明确记录 Analyzer 状态：`not_run`（未运行）、`completed`（完成）、`failed`（失败）。
JSON 的 `analysis.analyzers` 提供各分析器的状态、原因、警告和错误；Python、C++、Git、统一依赖图和洞察章节也提供 `status` 与 `reason`。
Markdown 在对应章节显示状态与原因。未运行不等于分析后没有结果；上游分析失败时，下游会跳过并说明原因。

JSON Schema 0.5 中，概览计数在对应分析未完成时为 `null`，包括文件/行数/语言、Python/C++ 入口和 `dependency_nodes`、`dependency_edges`、`cycle_count`；完成后才输出数量（包括零）。Markdown 和 UI 在对应位置显示未运行或失败，入口候选分别注明 Python 与 C++ 的状态。
Git Analyzer 完成表示已检查 Git 可用性，历史是否可用还需查看 `git.available` 和 `git.error`。

静态阅读推荐不依赖 Git 历史。`insights.change_attention_analysis` 单独提供变更关注的 `status` 与 `reason`：洞察未运行/失败时继承其状态；洞察完成但 Git 未运行、失败或历史不可用时为 `not_run`，并说明原因。此时 `change_attention` 为空，模块评分中的 `git_changes`、`recent_changes`、`scores.git` 和 `scores.change_attention_score` 为 `null`，Markdown/UI 显示“未计算”；静态阅读优先级与阅读路径仍可使用。

## 6. 限制

* GitHub 仅支持公开仓库。
* 默认 C++ 分析为基础文本识别；可选 libclang PoC 的能力和覆盖受编译配置限制，不代表完整 C++ 程序语义。
* Python 不执行目标仓库代码。
* 动态 import、宏展开和生成文件可能无法准确识别。
* GitHub 快照不包含 `.git`，因此无法分析远程 Git 历史。
* 阅读优先级和变更关注度仅用于辅助导航，不代表代码质量或缺陷概率。

## 7. 开源协议

[Apache License 2.0](LICENSE)
