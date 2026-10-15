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
* **C++**：源码与头文件结构、include 解析、函数、类/结构体、命名空间和入口候选
* **依赖分析**：统一依赖图、循环依赖、孤立模块
* **阅读导航**：阅读优先级、推荐阅读顺序、入口路径
* **实验性阅读指南**：整理文档摘录、源码位置与关联线索，仅供辅助查找，CLI 与 UI 均可开启
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
| `deep` | 全部常规分析，包括统一依赖图、阅读顺序、模块评分和变更关注；实验性阅读指南单独开启 |

`standard` 不运行统一依赖图和洞察分析。如需完整阅读导航，使用 `--profile deep`。

### 实验性阅读指南

**阅读指南永久作为实验性功能提供，默认关闭。** 它仅按静态规则整理文档和源码线索，不能可靠回答“项目做什么”“架构如何组成”或“最值得读什么”。

阅读指南单独开启，不要求依赖图或 Git 历史成功。CLI 源码运行与打包程序使用同一个选项：

```powershell
python -m repopath . --reading-guide -o guide.md
repopath.exe . --reading-guide --format json -o guide.json
```

Streamlit 中在“高级配置”勾选“实验性阅读指南”，分析后进入“阅读指南（实验）”视图。两端使用相同的选项、分析结果和报告内容，UI 也能下载同一份 JSON / Markdown 报告。

报告分为**项目说明摘录、组成线索、阅读线索**，列出来源、提取依据和可返回原文核对的内容。CLI 使用 `--detail full` 查看依据与片段；UI 展开“依据与片段”或“分析说明”，下载 Markdown 时也可选择“摘要 / 完整”。

使用时需要了解以下限制：

* **文档依赖较强**：说明主要来自 README、项目清单和源码注释，内容可能过时、偏题或缺失。“在线体验”等段落也可能被摘出，不能将摘录当作经过理解的用途介绍。
* **结构不等于架构**：目录、包和依赖只能提供组成线索，无法可靠推断业务职责，也不能还原完整运行流程。
* **有来源不代表值得读**：入口、`__all__` 导出列表或调用片段的存在，不足以证明其重要性。列出依据只解释为什么被规则选中，不承诺阅读收益。
* **关系和覆盖范围有限**：动态绑定、宏、生成代码及扫描上限都可能造成遗漏；候选关联需要返回源码核对，列表顺序不代表执行顺序。

功能不使用 LLM，不构建或执行目标仓库。Python 支持最多四层唯一顶层导入的重导出追踪，遇到动态绑定、歧义或循环停止。各语言分析深度取决于已启用能力，其他语言主要提供文档、清单和链接线索。

也可在 `.repopath.toml` 中设置 `[analyzers]` 下的 `reading = true`。CLI 的 `--no-reading-guide` 可覆盖配置关闭指南；切换分析模式不会取消显式开启的指南。`fast` 模式只提供文档和清单等证据，Python/C++ 结构增强仍取决于语言开关。

开启后旧的规模/引用榜单在 CLI 和 UI 中标为结构统计，JSON 保留原字段。测试验证来源记录、失败隔离和两端一致性，不代表报告足以帮助读者理解项目。

指南的采集目前最多读取 512 个文件、合计 8 MiB，单文件上限 256 KiB；项目说明与明确入口优先读取。组成最多列出 20 项，清单预读最多 64 份。每个文件最多保留 64 个候选，全局最多 2000 个，再选出不超过 `reading_limit` 的线索，不要求填满数量。分析超预算会记录缺口，正常选择少量线索不标为分析截断。JSON 保存本次选中的线索及已保留依据，不包含未入选候选的完整列表。

### GitHub

```powershell
python -m repopath owner/repository
python -m repopath owner/repository --ref main
```

GitHub 分析会固定到提交 SHA 后下载快照进行静态分析，**不会克隆仓库或执行目标代码**。

### 文件扫描

文件数、行数、语言和目录统计仅包含成功读取的文本文件。扫描按内容检查常见二进制文件头、NUL 字符和密集控制字符，跳过识别出的图片、SQLite、压缩包等二进制数据。识别不依赖扩展名：改成 `.py` 的二进制仍会跳过，SVG、无扩展名脚本和使用 `.db` 后缀的真实文本仍可统计。

支持 UTF-8，以及带 BOM 的 UTF-8、UTF-16 和 UTF-32，严格解码后统一换行。GBK、Latin-1 等不受支持的编码不再用替换乱码的方式强行读取，暂时跳过。空文本文件保留，行数为零。

默认单文件大小上限为 2 MiB，可通过 `max_file_size` 调整。非文本、编码不支持、超限或不可读文件会汇总为一条跳过提示，不逐个将图片等资源报成读取失败。CLI、Streamlit 和 Markdown/JSON 使用同一份扫描结果。

### C++ 源码静态分析

直接扫描项目中的源码和头文件即可分析 C++，无需安装编译器、SDK 或额外分析依赖，也无需提供编译数据库、构建或运行目标项目。源码运行沿用上面的 CLI 命令；使用 Release 中的可执行文件无需安装 Python。

include 解析只在本次扫描的项目文件中查找。对于 `#include "path/header.hpp"`，依次尝试包含它的源文件所在目录、仓库根目录，再按完整 include 路径的后缀查找候选；`#include <path/header.hpp>` 从仓库根目录开始查找。只有得到唯一目标时才建立依赖边，不会把 `a/header.hpp` 猜成只有文件名相同的 `b/header.hpp`。

存在多个候选、找不到项目文件或使用宏形式的 include 都会保留在报告中，供继续核查；这些不确定关系不进入依赖图。注释和字符串中的伪 include 会被忽略。报告也记录 include 所在的预处理条件，但不求值或选择当前构建分支，因此图中可能同时出现互斥条件下的依赖。

函数、类/结构体和命名空间用于辅助阅读导航，`main`、`wmain`、`WinMain`、`wWinMain` 作为入口候选，并保留所在的预处理条件。分析不进行宏展开、类型检查、重载解析或完整调用关系推导；结果描述源码结构与项目内 include 关系，不代表完整的 C++ 编译语义。

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

C++ 报告提供基础符号与入口候选。JSON 的 `cpp.include_details` 保留每处 include 的源码位置、形式、解析结果、目标或候选文件，以及预处理条件；`cpp.entry_points` 提供候选入口的文件、名称、行号和条件。原有 `cpp.includes`、`cpp.symbols` 和 `cpp.dependencies` 分别保留 include 计数、基础符号和已匹配的依赖关系。JSON 保存全部结果，Markdown 展示匹配统计并按报告数量设置限量列出记录。

依赖图只采用解析到唯一项目文件的 include；找不到目标不代表源码有错，也可能是系统头文件、扫描范围外的依赖或尚未生成的文件。图中汇总了源码各分支的路径关系，不表示某次构建的实际依赖或函数调用关系。

报告明确记录 Analyzer 状态：`not_run`（未运行）、`completed`（完成）、`failed`（失败）。
JSON 的 `analysis.analyzers` 提供各分析器的状态、原因、警告和错误；Python、C++、Git、统一依赖图和洞察章节也提供 `status` 与 `reason`。
Markdown 在对应章节显示状态与原因。未运行不等于分析后没有结果；上游分析失败时，下游会跳过并说明原因。

JSON Schema 0.7 的 `reading_guide` 保留 `experimental: true`。其中 `purpose` 为项目说明摘录，`structure` 为结构章节摘录，`components` 为目录、包或子项目记录；`steps` 中的 `reason`、`learn` 和 `goal` 分别表示列出依据、可核对内容与线索类别。字段名称保持兼容，不代表已理解用途或确认阅读价值。`analysis.analyzers.reading` 记录独立执行状态；完成但没有线索不等于项目没有值得阅读的内容。

概览计数在对应分析未完成时为 `null`，包括文件/行数/语言、Python/C++ 入口和 `dependency_nodes`、`dependency_edges`、`cycle_count`；完成后才输出数量（包括零）。Markdown 和 UI 在对应位置显示未运行或失败，入口候选分别注明 Python 与 C++ 的状态。
Git Analyzer 完成表示已检查 Git 可用性，历史是否可用还需查看 `git.available` 和 `git.error`。

静态阅读推荐不依赖 Git 历史。`insights.change_attention_analysis` 单独提供变更关注的 `status` 与 `reason`：洞察未运行/失败时继承其状态；洞察完成但 Git 未运行、失败或历史不可用时为 `not_run`，并说明原因。此时 `change_attention` 为空，模块评分中的 `git_changes`、`recent_changes`、`scores.git` 和 `scores.change_attention_score` 为 `null`，Markdown/UI 显示“未计算”；静态阅读优先级与阅读路径仍可使用。

## 6. 限制

* GitHub 仅支持公开仓库。
* 文件扫描采用内容规则识别二进制，无法保证覆盖所有格式；不支持的文本编码也会跳过。文件数不是磁盘上的全部文件数量，详见[文件扫描](#文件扫描)。
* C++ 分析基于源码静态识别；include 搜索不读取编译参数，无法还原实际构建中的头文件搜索顺序。入口和符号均为阅读候选，不代表完整 C++ 程序语义。
* Python 不执行目标仓库代码。
* 动态 import、宏展开和生成文件可能无法准确识别。
* GitHub 快照不包含 `.git`，因此无法分析远程 Git 历史。
* 阅读优先级和变更关注度仅用于辅助导航，不代表代码质量或缺陷概率。
* [实验性阅读指南](#实验性阅读指南) 永久保留实验性定位；依赖文档与静态规则，摘录可能偏题，不能可靠解释业务用途、完整架构或阅读价值。

## 7. 开发与验收

CLI（包括打包程序）与 Streamlit UI 共用核心分析和报告模型。新增分析能力、开关、来源依据和失败状态须同时在两端提供；显示方式可以不同，功能不能只在一端可用。确有特殊例外时须先经维护者批准。

CI 在 Windows/Linux、Python 3.11–3.14 上运行测试，其中包含真实 Streamlit 页面与 CLI 报告的一致性检查。发行流程还会搬移可执行文件，在没有构建工具和目标依赖的环境中检查 C++ 分析与阅读指南。开发回归样例用于检查机制，不替代按项目家族隔离的未见仓库和独立读者验收。

## 8. 开源协议

[Apache License 2.0](LICENSE)
