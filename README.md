# RepoPath

**一个帮助开发者和编程 Agent 快速理解陌生代码仓库的本地多语言分析工具。**

## 项目说明

RepoPath 使用 Python 编写。输入本地仓库目录后，工具会扫描文件结构、代码规模、Python 模块关系、C++ 基础静态结构和 Git 历史，并生成统一依赖图、可解释核心评分、推荐阅读顺序以及 Markdown 或 JSON 报告。

项目的目标是在阅读大量源码前，先建立仓库的整体认知，辅助定位入口、核心模块、依赖关系和近期演进情况。

当前仅支持本地目录分析。远程 GitHub 仓库读取已预留后续演进方向，但尚未实现。

## 一、主要功能

### 1. 项目结构与代码统计

- 扫描仓库文件，跳过 `.git`、虚拟环境、缓存目录和指定输出文件
- 统计文件数、非空行数、注释行数、语言分布和主要目录
- 将 C++ 源文件与头文件合并为同一语言族统计

### 2. Python 分析

- 使用 AST 识别函数、类和 import
- 识别 `main.py`、`manage.py`、`__main__.py` 及 `__name__ == "__main__"` 入口
- 解析本地模块和相对导入关系
- 根据代码规模、本地引用次数和入口特征排序核心模块候选

### 3. C++ 基础静态分析

- 识别 `.cpp`、`.cc`、`.cxx`、`.h`、`.hpp`、`.hh` 和 `.hxx` 文件
- 提取 `#include`、函数、类/结构体、命名空间和 `main` 入口
- 识别仓库内可解析的本地 include 依赖

### 4. Git 历史分析

- 汇总提交数、首次和最近提交时间、主要贡献者与最近提交
- 统计文件提交次数、代码增删量、月度趋势和最近 30/90 天活跃度
- 识别共同修改文件、目录贡献者、活跃文件和长期稳定文件
- 没有可用 Git 历史时保留其他分析结果，并在报告中给出提示

### 5. 依赖图与阅读导航

- 将 Python import 和 C++ include 合并为统一依赖图
- 统计入度、出度、循环依赖、孤立模块和目录依赖
- 按代码规模、依赖中心度、入口距离和 Git 热度生成可解释评分
- 输出推荐阅读顺序、入口依赖路径和结构风险热点

### 6. 报告与界面

- 输出 Markdown 报告，便于阅读和提交到其他工具
- 输出 JSON 报告，便于后续处理和集成
- 提供 Streamlit 仓库阅读工作台，在同一条 Pipeline 上查看概览、阅读路线、依赖、Python、C++、Git 和报告
- 支持快速、标准和深度分析模式、Pipeline 阶段进度、失败建议，以及 Markdown/JSON 完整报告下载
- 支持按语言、目录、关键词筛选并排序阅读路线、依赖边和 Git 热点；可选择模块查看评分、推荐原因和双向依赖

## 二、项目结构

```text
app.py                      # Streamlit 根目录入口和依赖注入
repopath.py                 # 根目录 CLI 兼容启动脚本
run_streamlit.py            # Streamlit bootstrap 启动脚本
repopath/
  analyzer/
    file_analyzer.py        # 文件扫描和代码行统计
    python/                 # Python AST 与模块依赖分析
    cpp/                    # C++ 基础静态分析
    git_analyzer.py         # Git 历史分析
    dependency_analyzer.py  # 统一依赖图
    insight_analyzer.py     # 评分、阅读路线和风险热点
  core/                     # Context、Pipeline、Composer 和分析服务
  interface/
    cli.py                  # 命令行入口
    ui/                     # Streamlit 表单、会话状态和报告视图
  model/                    # 仓库、依赖、洞察和报告模型
  provider/                 # 文件系统和 Git 数据来源
  renderer/                 # Markdown 和 JSON 输出
tests/                      # Analyzer、依赖图、配置、Git、UI 和混合仓库测试
requirements.txt            # Streamlit UI 依赖
requirements-dev.txt        # 测试依赖
```

分析数据流如下：

```text
RepositorySource -> Provider -> Analyzer Pipeline
                                     |
                                     v
                    AnalysisResult + AnalysisArtifacts
                                     |
                                     v
          Composer -> RepositoryReport -> UI / Renderer
```

`Provider` 读取原始数据，`Analyzer` 只负责分析，`AnalysisResult` 保存执行元数据，`AnalysisArtifacts` 保存具名领域产物，`Composer` 合并统一报告。CLI 和 UI 共用同一条 Core Pipeline；UI 不直接导入 Analyzer、Provider 或 Git 命令实现。

## 三、安装与运行

### 1. Python 版本要求

最低要求：**Python 3.11**。

项目使用 `StrEnum` 等 Python 3.11 语法。CI 当前验证 Python 3.11、3.12、3.13 和 3.14。

### 2. 创建虚拟环境

Windows PowerShell：

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
```

macOS 或 Linux：

```bash
python -m venv .venv
source .venv/bin/activate
```

### 3. 安装依赖

CLI 核心功能仅依赖 Python 标准库，在项目根目录可直接运行。

使用 Streamlit UI 时安装运行依赖：

```powershell
python.exe -m pip install -r requirements.txt
```

开发和运行测试时安装开发依赖：

```powershell
python.exe -m pip install -r requirements-dev.txt
```

### 4. 生成报告

在项目根目录执行以下任一命令。两种方式调用同一个 CLI 和 Core Pipeline：

```powershell
python.exe -m repopath . -o REPOPATH_REPORT.md
python.exe repopath.py . -o REPOPATH_REPORT.md
```

生成 JSON 报告：

```powershell
python.exe -m repopath . --format json -o REPOPATH_REPORT.json
```

`-o` 用于指定输出路径；未指定时默认生成 `REPOPATH_REPORT.md`。输出文件会自动从本次扫描中排除。

常用分析参数：

```powershell
python.exe -m repopath . --profile deep --git-period 90 --result-limit 30
python.exe -m repopath . --exclude "generated/*" --max-file-size 2097152
python.exe -m repopath . --reading-limit 10 --include-file-list
python.exe -m repopath . --no-cpp --no-git
```

使用 `python.exe -m repopath --help` 查看完整参数。

### 5. 仓库配置

仓库根目录可创建 `.repopath.toml`：

```toml
[scan]
profile = "deep"
max_file_size = 2097152
follow_symlinks = false
exclude = ["generated/*", "*.min.js"]

[analyzers]
# 可选：显式覆盖 profile 中的单项开关
# cpp = false

[git]
period = "all"

[report]
limit = 50
reading_limit = 10
include_file_list = false
```

首次通过 CLI 分析仓库时，如果根目录缺少 `.repopath.toml`，RepoPath 会创建以上默认配置后再读取。UI 会在实际点击“分析仓库”时执行相同行为；仅打开页面不会写入文件。`--config` 可指定其他配置文件，缺失的显式配置文件不会自动创建。

覆盖顺序为：CLI 参数 > `.repopath.toml` > 内置默认值。配置使用 Python 标准库 `tomllib` 读取。`report.limit` 控制通用结果列表上限，`report.reading_limit` 单独控制推荐阅读和核心评分，默认展示 10 个文件；`report.include_file_list` 控制 Markdown 是否包含完整文件清单，默认关闭。

核心模块总分最高为 100 分：代码规模最高 20 分，每 25 行非空代码计 1 分；依赖分最高 35 分，每个被依赖入边计 7 分、每个主动依赖出边计 2 分；入口可达性最高 20 分，入口为 20 分且每远离入口一层减 4 分；Git 修改热度最高 25 分，由历史修改次数和近 90 天修改次数累计。推荐阅读顺序优先列出入口及入口可达模块，再按总分排序。风险分等于依赖分加 Git 分，仅将同时存在依赖关系和 Git 修改记录的模块列为风险热点。

### 6. 启动 Streamlit UI

安装 `requirements.txt` 后，在项目根目录执行：

```powershell
python.exe run_streamlit.py
```

`run_streamlit.py` 会找到根目录的 `app.py`，并通过 Streamlit bootstrap 启动。启动完成后终端会显示实际本地访问地址。

页面提供三个分析模式：

| 模式 | 执行内容 | 适用场景 |
| --- | --- | --- |
| 快速 | 文件扫描、语言识别、代码规模和目录统计 | 先确认仓库范围 |
| 标准 | 快速模式加 Python AST、C++ 基础结构和 Git 历史统计 | 了解代码组成和演进 |
| 深度 | 全部 Analyzer，包含依赖图、评分、阅读路线和 Git 热点 | 进行完整代码阅读 |

页面会先读取目标目录 `.repopath.toml` 的模式和高级配置，再应用用户在页面中选择的模式与高级参数。UI 覆盖顺序为：内置默认值 < `.repopath.toml` < 已选择模式 < UI 高级配置。高级配置可设置 Git 历史时间范围、单文件读取上限、通用页面结果数量、阅读与评分数量，以及 Markdown 文件清单开关；页面截断只影响视图，Markdown 和 JSON 下载始终保留完整 `RepositoryReport`。

## 四、使用方式

### 命令行

1. 将命令中的 `.` 替换为待分析仓库的本地路径，或在目标仓库根目录执行命令。
2. 使用 `-o` 指定 Markdown 或 JSON 输出文件。
3. 打开生成的报告，查看概览、语言统计、模块依赖、C++ 分析和 Git 历史。

例如：

```powershell
python.exe -m repopath D:\code\sample-project -o D:\reports\sample-project.md
```

### Streamlit UI

1. 启动 `run_streamlit.py`。
2. 在页面中输入本地仓库路径。
3. 选择快速、标准或深度模式；需要时在“高级配置”调整 Git 时间范围、最大文件大小、页面结果数量、阅读与评分数量，以及 Markdown 文件清单开关。
4. 点击“分析仓库”，页面按 Pipeline 阶段显示进度；重新分析会清理上一份报告，失败时展示可执行的处理建议和原始错误详情。
5. 在概览、推荐阅读、依赖关系、Python、C++、Git 和报告页签中查看结果；可按语言、目录和路径筛选并排序阅读路线、依赖边和 Git 热点。
6. 在推荐阅读页选择模块，可联动查看核心评分、推荐原因、正向依赖和反向依赖；在报告页下载完整 Markdown 或 JSON。

页面会在关键概念处提供帮助说明：核心评分综合规模、依赖、入口可达性和 Git 修改热度；风险热点结合依赖重要性与修改热度；Churn 是历史新增和删除行数总和；循环依赖表示模块间的闭环关系。小型依赖图显示为 Graphviz；大型依赖图切换为目录聚合和可筛选的边表。

## 五、报告内容

Markdown 报告包含以下主要部分：

- 概览：文件数、非空行数、注释行数和入口候选数量
- 语言统计：各语言族的文件数、非空行数与文件占比
- 项目结构：主要目录，以及可选的完整文件清单
- Python：核心模块候选、入口、import 和本地模块依赖
- C++：include、函数、类/结构体、命名空间、入口和本地 include 依赖
- 统一依赖图：正向依赖、循环依赖、孤立模块和目录聚合
- 阅读导航：核心评分明细、推荐顺序、入口路径和风险热点
- Git：提交趋势、代码增删量、文件 churn、共同修改和目录贡献者
- 运行信息：Schema、工具版本、生成时间和 Analyzer 耗时
- 分析提示：文件不可读、Python 语法错误或 Git 不可用等警告和错误

JSON 报告提供对应的结构化数据，适合后续脚本处理或接入其他工具。

## 六、测试

项目使用 pytest，覆盖 Python AST、C++、统一依赖图、阅读洞察、TOML 配置、Git 演进、Provider 契约、CLI 参数、Streamlit 页面、UI 会话状态、预设矩阵和 UI 依赖边界。

```powershell
python.exe -m pytest -q
```

GitHub Actions 会在 Python 3.11 至 3.14 上运行测试。

开发时可额外运行 Pyright：

```powershell
python.exe -m pyright
```

## 七、当前限制

1. 仅支持本地目录，不读取 GitHub 或其他远程仓库。
2. C++ 使用正则进行基础静态识别，不替代完整 C++ AST、编译数据库或类型分析。
3. Python 仅解析语法和 import，不执行目标仓库代码。
4. 本地模块依赖与 C++ include 关系是静态近似结果，动态导入、宏展开和构建系统生成文件可能无法准确反映。
5. 核心评分和阅读顺序用于辅助导航，不代表代码质量或业务重要性的绝对结论。
6. Git 热点受提交粒度、历史完整性、重命名和浅克隆影响；Git 不可用时该部分会缺失。
7. 文件共同修改统计将单次提交最多前 50 个路径用于组合，避免超大提交产生二次方开销。
8. 大型仓库的扫描时间与可读取文件数量、文件大小和 Git 历史长度相关。
9. Streamlit 页面当前使用同步分析；不提供后台任务、自动刷新或中断按钮。
10. UI 只开放本地目录输入；GitHub API、认证、缓存和 API 限流尚未实现。

## 八、开源许可

RepoPath 采用 [Apache License 2.0](LICENSE) 开源协议。该协议包含版权许可、专利许可和免责声明；完整条款请参阅 [LICENSE](LICENSE)。
