# 主应用核心包

`core/jingxu/` 是炳恒快速混剪的 Python 主应用包；项目配置在仓库根目录 `pyproject.toml`。

从仓库根目录运行：

```powershell
python -m pip install -e ".[dev,download]"
python -m jingxu
python -m pytest
```

主应用以 `jingxu` 作为稳定导入包名。选品爬虫是独立扩展，源码位于 `extensions/spider/`，打包时复制至 `runtime/spider/`。
