from setuptools import setup, find_packages

setup(
    name="ecommerce-spider-component",
    version="1.0.0",
    description="抖音与快手短视频带货商品爬取与跨账号共性保留分析组件",
    author="Antigravity",
    packages=find_packages(include=["core*", "gui*", "ecommerce_spider*"]),
    python_requires=">=3.8",
    install_requires=[
        "DrissionPage>=4.1.0",
        "requests>=2.28.0",
        "pandas>=2.0.0",
        "openpyxl>=3.0.0",
        "tabulate>=0.9.0",
        "PySide6>=6.5.0",
    ],
    entry_points={
        "console_scripts": [
            "ecommerce-spider=cli:run_cli",
            "ecommerce-spider-gui=run:main",
        ],
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "Topic :: Internet :: WWW/HTTP :: Indexing/Search",
    ],
)
