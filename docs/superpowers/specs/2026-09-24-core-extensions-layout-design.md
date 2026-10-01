# Core / Extensions 项目目录重整设计

## 目标

把当前嵌套于 `src/JingXu.Workbench.Py/` 的应用项目整理为仓库根目录下清晰的 `core/` 与 `extensions/`，使项目入口、测试、配置和构建资源可直接发现，同时保持应用功能、Python 模块导入名和交付行为不变。

## 目标结构

```text
core/                         # 主应用 Python 包 jingxu/
extensions/spider/            # 选品爬虫源码（由主应用通过 CLI 子进程驱动）
tests/                        # 主应用测试；爬虫测试归入 tests/spider/
docs/
scripts/
tools/
build/                        # 构建配置与运行时清单
runtime/                      # 本地/随包第三方运行时
artifacts/                    # 构建及验收产物
pyproject.toml                # 仓库根项目配置
README.md
```

## 约束与兼容性

- Python 主包仍叫 `jingxu`，启动命令仍为 `python -m jingxu`；`pyproject.toml` 的 setuptools 搜索根改为 `core/`。
- 爬虫仍作为独立 CLI 程序运行，部署时仍复制到 `runtime/spider`；`core/jingxu/infrastructure/spider.py` 是开发环境和冻结包的路径解析适配点。
- 将主测试移至根 `tests/`，爬虫专用测试放在 `tests/spider/`；pytest 默认只发现一处测试树。
- 同步更新 PyInstaller、PowerShell 构建/运行时脚本、文档、忽略规则与测试路径假设。
- 保留已暂存/未暂存的用户变更，不重置、不提交、不覆盖已有工作。
- 迁移仅改目录和路径配置，不做业务逻辑重构。

## 验收

- 根目录可安装开发依赖并通过 pytest；主应用、选品爬虫源码定位、CLI/自检与打包资源定位正常。
- 无关键脚本或配置继续依赖已删除的 `src/JingXu.Workbench.Py`、`src/JingXu.Spider` 路径。
- `git status` 显示的用户原有变更仍在，迁移新增差异可以识别。
