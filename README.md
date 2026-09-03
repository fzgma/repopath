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

支持 `quick`、`standard`、`deep` 三种分析模式。

### GitHub

```powershell
python -m repopath owner/repository
python -m repopath owner/repository --ref main
```

GitHub 分析会固定到提交 SHA 后下载快照进行静态分析，**不会克隆仓库或执行目标代码**。

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

## 6. 限制

* GitHub 仅支持公开仓库。
* C++ 使用基础静态分析，不替代完整 C++ AST。
* Python 不执行目标仓库代码。
* 动态 import、宏展开和生成文件可能无法准确识别。
* GitHub 快照不包含 `.git`，因此无法分析远程 Git 历史。
* 阅读优先级和变更关注度仅用于辅助导航，不代表代码质量或缺陷概率。

## 7. 开源协议

[Apache License 2.0](LICENSE)
