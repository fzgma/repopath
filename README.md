# RepoPath

RepoPath 是一个无第三方依赖的 Python demo，用于快速生成陌生代码仓库的 Markdown 概览。

## 运行

在仓库根目录执行：

```powershell
.\.venv\Scripts\python.exe repopath.py . -o REPOPATH_REPORT.md
```

也支持模块形式：

```powershell
.\.venv\Scripts\python.exe -m repopath . -o REPOPATH_REPORT.md
```

## 当前能力

- 统计文件数量、非空行数、语言分布和主要目录
- 用 Python AST 提取 import，不执行被分析项目代码
- 根据代码规模和本地引用关系列出核心模块候选
- 识别常见 Python 入口和 `__name__ == "__main__"` 主程序入口
- 统计 Git 提交、贡献者、最近提交和高频修改路径
- 生成可直接阅读的 Markdown 报告

## Demo 结构

核心实现集中在根目录的 `repopath.py`：CLI 负责参数和输出，扫描器负责文件数据，Git 采集器负责历史数据，报告渲染器负责 Markdown。`.git`、`.venv`、缓存和构建目录会被跳过，输出报告自身也不会被重复统计。
