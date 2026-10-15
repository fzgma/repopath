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
* **C++**：include、函数、类/结构体、命名空间和入口
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

### 文件扫描

文件数、行数、语言和目录统计仅包含成功读取的文本文件。扫描按内容检查常见二进制文件头、NUL 字符和密集控制字符，跳过识别出的图片、SQLite、压缩包等二进制数据。识别不依赖扩展名：改成 `.py` 的二进制仍会跳过，SVG、无扩展名脚本和使用 `.db` 后缀的真实文本仍可统计。

支持 UTF-8，以及带 BOM 的 UTF-8、UTF-16 和 UTF-32，严格解码后统一换行。GBK、Latin-1 等不受支持的编码不再用替换乱码的方式强行读取，暂时跳过。空文本文件保留，行数为零。

默认单文件大小上限为 2 MiB，可通过 `max_file_size` 调整。非文本、编码不支持、超限或不可读文件会汇总为一条跳过提示。CLI、Streamlit 和 Markdown/JSON 使用同一份扫描结果。

## 3. 配置

在仓库根目录创建 `.repopath.toml`：

```toml
[scan]
profile = "deep"
max_file_size = 2097152
exclude = ["generated/*", "*.min.js"]

[git]
period = "all"

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

报告明确记录 Analyzer 状态：`not_run`（未运行）、`completed`（完成）、`failed`（失败）。
JSON 的 `analysis.analyzers` 提供各分析器的状态、原因、警告和错误；Python、C++、Git、统一依赖图和洞察章节也提供 `status` 与 `reason`。
Markdown 在对应章节显示状态与原因。未运行不等于分析后没有结果；上游分析失败时，下游会跳过并说明原因。

JSON Schema 0.5 中，概览计数在对应分析未完成时为 `null`，包括文件/行数/语言、Python/C++ 入口和 `dependency_nodes`、`dependency_edges`、`cycle_count`；完成后才输出数量（包括零）。Markdown 和 UI 在对应位置显示未运行或失败，入口候选分别注明 Python 与 C++ 的状态。
Git Analyzer 完成表示已检查 Git 可用性，历史是否可用还需查看 `git.available` 和 `git.error`。

静态阅读推荐不依赖 Git 历史。`insights.change_attention_analysis` 单独提供变更关注的 `status` 与 `reason`：洞察未运行/失败时继承其状态；洞察完成但 Git 未运行、失败或历史不可用时为 `not_run`，并说明原因。此时 `change_attention` 为空，模块评分中的 `git_changes`、`recent_changes`、`scores.git` 和 `scores.change_attention_score` 为 `null`，Markdown/UI 显示“未计算”；静态阅读优先级与阅读路径仍可使用。

## 6. 限制

* GitHub 仅支持公开仓库。
* 文件扫描采用内容规则识别二进制，无法保证覆盖所有格式；不支持的文本编码也会跳过。文件数不是磁盘上的全部文件数量，详见[文件扫描](#文件扫描)。
* C++ 使用基础静态分析，不替代完整 C++ AST。
* Python 不执行目标仓库代码。
* 动态 import、宏展开和生成文件可能无法准确识别。
* GitHub 快照不包含 `.git`，因此无法分析远程 Git 历史。
* 阅读优先级和变更关注度仅用于辅助导航，不代表代码质量或缺陷概率。

## 7. 开源协议

[Apache License 2.0](LICENSE)
