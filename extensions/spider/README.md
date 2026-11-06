# 🎬 抖音 & 快手多账号短视频带货商品爬取与共性保留分析系统

## 每日定时抓取（1.1.1）

主工作台选品页点击「定时抓取」，勾选启用并设置每天开始时间，然后保存。任务使用当前已保存的启用账号、三项筛选报表和浏览器设置，完成后自动保存报表和最近结果。软件可关闭，电脑需保持开机、当前 Windows 账号登录并联网，站点 Cookie 需有效。

已有手动或定时抓取运行时跳过新任务，同一天不重复执行。Windows 任务允许长时间运行，不设置整体时长截止。任务状态和日志可在选品页查看；停用每日任务不会禁用手动抓取。后台入口为主程序 `--scheduled-spider`，仅执行匹配已启用任务标识的配置。

## 独立浏览器与 Cookie 保存（1.1.0）

程序使用 Chrome/Edge 内核显式创建新的独立浏览器进程。每次启动或更换环境使用一个新的 `browser_profile/environments/env-*` 临时档案，不接管任何已打开的本机浏览器。连接前通过浏览器调试接口验证进程归属，关闭或取消只处理本程序创建的进程树。

登录 Cookie 单独保存在 `browser_profile/cookies.json`；默认位置为 `%LOCALAPPDATA%/JingXu/Spider/browser_profile/cookies.json`。扫码期间自动保存，点击「我已登录」时再次保存；普通抓取和周期切换会保存最新 Cookie。新的浏览器只恢复登录 Cookie，缓存和网站本地存储均从空环境开始。短期环境标识、验证 Cookie 不会带入下一个环境。

默认每 **300 秒或累计 10 页**更换环境，任一条件满足即在抓取检查点切换。工作台选品页可调整分钟数和页数；CLI 支持 `--rotate-seconds`、`--rotate-pages`，`--session-dir` 指定 Cookie 与临时环境目录（兼容原 `--profile-dir`）。SDK 构造器支持 `browser_rotate_seconds`、`browser_rotate_pages`，扫码结束可调用 `finish_login()`。

切换后使用已保存的翻页游标继续，阶段结果保留并合并去重。快手新网页的 REST 请求会在新环境中重新取得，使用当前环境的请求字段和保存的游标继续。登录窗口在扫码期间不自动更换环境；保存后关闭登录进程，再启动新的抓取环境。普通浏览器个人资料目录会被拒绝。

Cookie 内容不会写入运行日志、分析报表或安装包。未变化的 `cookies-import.json` 不会覆盖后续登录更新；失效 Cookie 仍需要重新扫码。Cookie 保存失败时保留上次 Cookie 和当前环境资料，正常周期切换会停止并报告问题。

## 主工作台选品报表

主工作台可单独选择「按点赞量」「按总频次」「按跨账号数」，或勾选「同时生成多个筛选报表」。每项有独立门槛和时间范围，支持近 3 / 7 / 15 / 30 / 60 / 90 / 180 / 365 天、自定天数和日期范围。

按点赞量先筛掉未达点赞门槛的视频，再清洗合并商品；总频次按不同视频统计，跨账号数按不同账号身份统计。每张结果表均选用本表范围内点赞最高的视频作为示例，链接、点赞数与日期来自同一条视频。

抓取一次覆盖所选任务的时间范围，分别生成按筛选条件命名的抖音、快手工作表。结果页可切换报表和平台；商品主图同时显示在结果页及 Excel 中，图片无法获取时保留可打开的主图链接。两个平台的商品始终分别清洗、统计和判断门槛。

整项任务不再设置 1800 秒超时，仍可主动取消；单次浏览器和网络操作保留超时保护。异常视频会被跳过并标记部分完成，其他有效视频及账号继续处理，阶段结果继续保存。

## 异常主页恢复（1.0.9）

抓取作者主页时如出现明确的「访问异常」「异常请求」「网络环境异常」等错误页，软件会自动退出异常页面，清理当前平台 Cookie、HTTP 缓存及网站缓存，再打开当前作者主页。每个账号最多恢复两次；中途出错时从已保存的接口游标继续，已抓取结果保留并合并去重。清理失败或恢复后仍异常时标记未完成并继续其他账号。

正常抓取时在进入账号前及每五页自动清理 HTTP 缓存，正常 Cookie 保留。连续接口翻页间隔为一秒。其他平台的 Cookie、账号配置、网站登录存储及导出报表保留。清理异常平台 Cookie 后若站点要求重新登录，需要扫码；登录页和人工验证码提示本身不会触发 Cookie 清理。

## 缓存与登录资料

浏览器打开前及关闭后自动清理 HTTP、代码、GPU 缓存。Cookies、Network、Local Storage、Session Storage、IndexedDB、Service Worker、Preferences 和 Local State 均保留。活跃浏览器、无法确认占用的档案、符号链接与目录联接不会被清理。

从 Cookie Editor 导出的抖音/快手 JSON 可放在浏览器档案上一级的 `cookies-import.json`，或通过 `JINGXU_SPIDER_COOKIES` 指定本机文件。仅导入对应平台域名的有效 Cookies，文件不变时不重复覆盖浏览器随后更新的登录态；凭据不会写入日志或导出表格。

当前快手网页使用 REST 作品接口，程序监听页面自身产生的作品响应。接口要求登录或安全验证时，先在登录窗口完成平台提示后重新抓取。程序不会将上限、空响应或异常误标为抓取完成。

主应用取消会通知 CLI 停止并保存阶段结果，必要时终止自有进程树；CLI 也支持 `--cancel-file`。

专门针对短视频电商选品、竞品对标分析开发的桌面自动化工具。支持同时批量监控抖音与快手的多个带货账号，按自定义时间范围抓取挂车商品，并**按自定义出现频次与跨账号数量精准保留共同带货的爆款商品**。

---

## 🌟 核心功能特性

### 1. 🎯 自定义添加对标账号
- **多平台支持**：同时支持抖音（Douyin）与快手（Kuaishou）。
- **灵活输入格式**：支持完整主页链接（如 `https://www.douyin.com/user/...`、`https://www.kuaishou.com/profile/...`）、APP分享短链（`v.douyin.com/...`、`v.kuaishou.com/...`）或用户 Sec-UID / ID。
- **批量导入**：支持一键从剪贴板多行粘贴批量导入数十个账号，系统自动识别平台并建立列表。
- **多选开关**：表格中可随时单独勾选或取消勾选账号，支持设置账号别名备注。

### 2. ⏱️ 自定义爬取时间范围
- **快捷预设**：一键切换【近 3 天】、【近 7 天】、【近 15 天】、【近 30 天】、【全部历史】。
- **精准日期选择**：选择【自定义日期】后，可通过日历控件精确指定【起始日期】与【结束日期】。
- **智能早停**：遇到早于设定起始日期的普通视频（非置顶视频）时，自动停止向下滚动翻页，极大缩短爬取耗时并规避频繁翻页风控。

### 3. 🔍 自定义出现频次与共性商品保留（核心需求）
- **跨账号共同带货筛选（选品爆款核心）**：
  - 支持设定“保留在 `>= N` 个不同对标账号中同时带货的商品”（默认 `>= 2`）。
  - 若多个对标账号都在带某款产品，说明该产品为当下跨账号爆发的共性爆品！
- **总频次门槛**：支持设定在所有视频中累计出现 `>= M` 次。
- **过滤准则**：
  - 按视频点赞量过滤，再合并商品（按最高点赞排序）
  - 仅按跨账号数过滤（只要跨账号数 `>= N` 即保留）
  - 仅按总带货频次过滤
  - 两者均需满足（跨账号 `>= N` 且 频次 `>= M`）
- **智能去噪与相似款归并**：
  - 自动剥离电商标题中的营销词与干扰字符（如“【官方正品】”、“包邮”、“拍1发3”、“破价特惠”等）。
  - 基于字符串相似度与字符 n-gram 聚类，将同款产品不同包装规格（如“超能植翠洗衣液3kg”与“超能植翠洗衣液3kg瓶装家庭特惠”）精准识别并合并为一个商品统计组。
- **无须重新爬取的即时重筛**：
  - 爬取完成后，修改保留门槛数值，点击【🔄 重新按新阈值筛选】按钮即可瞬间重新计算并刷新表格，无需再次消耗时间爬取网页！

### 4. 🧩 模块化组件体系（全新升级）
系统现已全面**组件化**，提供三大开箱即用组件：
1. **`EcommerceCrawlerComponent` (Python SDK 组件)**：在任何 Python 脚本中 5 行代码调用完整的爬取与跨账号分析。
2. **`ProductAnalyzerComponent` (独立分析组件)**：完全脱离爬虫，直接对来自数据库/CSV/第三方平台的带货记录进行去噪、聚类与频次保留过滤。
3. **`EcommerceCrawlerWidget` (可嵌入式 UI 控件)**：标准 PySide6 复合组件，可像按钮一样直接嵌入到您已有的任何软件、管理后台或 ERP 系统中！
4. **标准 Python 包支持**：支持 `pip install -e .`，安装后可在全系统任意项目直接 `import ecommerce_spider`。

---

## 🧩 作为组件调用的代码范例

### 1. Python SDK 组件极简调用
```python
from ecommerce_spider import EcommerceCrawlerComponent

# 初始化组件
crawler = EcommerceCrawlerComponent(headless=True)

# 1. 自定义添加对标账号 (支持抖音与快手)
crawler.add_account("douyin", "https://www.douyin.com/user/...", name="达人A")
crawler.add_account("kuaishou", "https://www.kuaishou.com/profile/...", name="老铁B")

# 2. 自定义爬取时间 (如近 7 天)
crawler.set_time_filter(days=7)

# 3. 自定义相同商品出现次数去保留商品 (跨账号数 >= 2)
crawler.set_retention_rule(min_account_count=2, enable_fuzzy=True)

# 4. 执行并获取结果
retained_products, all_items = crawler.run()

# 5. 一键导出 Excel 报表
crawler.export_excel("输出结果.xlsx")
```

### 2. 独立保留分析组件使用（无需启动爬虫）
```python
from ecommerce_spider import ProductAnalyzerComponent

analyzer = ProductAnalyzerComponent(min_account_count=2, enable_fuzzy_cluster=True)

raw_data = [
    {"platform": "douyin", "account_name": "达人A", "product_name": "【官方正品】生姜防脱洗发水500ml 拍1发2", "price": "¥39.9"},
    {"platform": "kuaishou", "account_name": "老铁B", "product_name": "生姜防脱洗发水500ml家庭装", "price": "¥38.8"},
]

retained = analyzer.filter_retained(raw_data)
# 自动清洗营销词并合并：提取出跨账号爆品 "生姜防脱洗发水500ml"！
```

### 3. 可嵌入式 UI 控件（嵌入到已有桌面软件中）
```python
from PySide6.QtWidgets import QMainWindow
from ecommerce_spider import EcommerceCrawlerWidget

class MyDashboard(QMainWindow):
    def __init__(self):
        super().__init__()
        # 直接像普通控件一样无缝嵌入
        self.crawler_widget = EcommerceCrawlerWidget(parent=self)
        self.setCentralWidget(self.crawler_widget)
```

---

## 🚀 启动与使用指南

### 方法一：Windows 一键双击运行（推荐）
直接双击根目录下的 **`启动软件.bat`** 即可启动现代化桌面图形界面！

### 方法二：命令行启动 GUI 界面
```bash
python run.py
```

### 方法三：CLI 命令行自动化模式（适用于服务器或定时任务）
```bash
# 查看所有命令行参数
python cli.py --help

# 示例：爬取近7天数据，保留在>=2个账号中出现的商品，后台静默运行
python cli.py --days 7 --min-accounts 2 --headless

# 示例：打开浏览器扫码登录抖音
python cli.py --login douyin

# 示例：打开浏览器扫码登录快手
python cli.py --login kuaishou
```

---

## 📁 目录结构说明

```
extensions/spider/
├── 启动软件.bat               # Windows 双击一键启动脚本（开发用 PySide6 界面）
├── run.py                    # 主程序入口（默认启动桌面GUI）
├── cli.py                    # 命令行自动化运行工具（主程序集成入口）
├── requirements.txt          # 嵌入式 Python 运行环境依赖清单
├── config.json               # 示例配置（主程序实际使用 %LocalAppData%\JingXu\Spider\config.json）
├── README.md                 # 详细说明文档
├── core/                     # 核心引擎层
│   ├── models.py             # 账号、视频、商品与聚合数据模型
│   ├── text_utils.py         # 商品名称去噪、归一化与相似度计算
│   ├── browser_manager.py    # DrissionPage 浏览器持久化与登录会话管理
│   ├── douyin_crawler.py     # 抖音短视频带货商品拦截引擎
│   ├── kuaishou_crawler.py   # 快手短视频带货商品拦截引擎
│   ├── analyzer.py           # 跨账号相同商品聚类与阈值保留算法
│   ├── exporter.py           # 多工作表 Excel/CSV/JSON 导出模块
│   └── config.py             # 配置管理模块
├── gui/                      # 可视化桌面界面层（不随安装包分发）
│   ├── main_window.py        # PySide6 主窗口（账号管理/时间/阈值/表格/导出）
│   └── worker.py             # 后台 QThread 工作线程
├── ecommerce_spider/         # 可复用组件与 SDK
└── tests/                    # 单元测试集
    └── test_crawler.py       # 自动化单元测试脚本
```
