# 每日热门表情包采集器（低成本版）

一个使用 **GitHub Actions + Python 标准库** 的每日热门表情包采集器。

- **当前只采集微信公众号**：通过搜狗微信搜索公众号发的热门表情包/GIF 文章。
- **一站式主页**：打开 `http://localhost:8765/` 一个页面就能看到“最近热门梗 + 搜索框 + 最新表情墙 + 最近日报”。
- **最近热门梗**：基于最近 90 天数据识别被多个公众号反复引用的梗名，最多显示 12 个；真实热门梗不足时自动用常见热门梗关键词补足，点击梗名会自动联网搜索。
- **联网搜索**：输入关键词按回车或点“联网搜索”，实时搜索微信公众号文章，不再只搜本地旧数据。
- **老梗搜索页**：`docs/search.html` 仍保留，可单独搜索历史日报。
- **DeepSeek 风格网页**：所有页面都带 DeepSeek 品牌元素。
- **小红书、抖音暂不采集**：没有公开表情包接口，直接抓取需要登录/风控/商业 API。
- 其他表情包站（斗图啦、Reddit、微博、贴吧等）已**全部排除**，因为它们的内容偏老。

> 如果你之后能提供小红书/抖音的 Cookie 或 API，我可以再接入。

特点：

- **不调用任何 AI/LLM API**，因此没有 Token 费用。
- **不下载原图入库**，只生成 Markdown/JSON/HTML 外链清单，GitHub 和本地存储占用极小。
- **只在需要时**用本地脚本下载图片到你的电脑。
- 数据源为“最佳努力”模式：某个网站挂了/改版，不影响其他源。

## 费用

| 项目 | 费用 |
| --- | --- |
| GitHub Actions（公开仓库） | 免费，标准 Linux runner 分钟数无限 |
| GitHub Actions（私有仓库免费版） | 每月 2000 分钟，本项目约 30 天 × 2~5 分钟 ≈ 150 分钟，仍为 0 元 |
| AI API | 0 元（未使用） |
| 仓库存储 | 仅文本，极小，0 元 |

> 注意：如果以后改成“自动下载全部图片”或“调用 AI 筛选”，费用才会上升。

## 目录结构

```
.
├── .github/workflows/daily-emoji.yml   # 每天定时任务
├── server.py                           # 本地网页服务器 + 联网搜索 API
├── scripts/
│   ├── collect.py                      # 采集 + 生成日报（Actions 中运行）
│   ├── download_selected.py            # 本地按需下载图片（手动运行）
│   └── cleanup_downloads.py            # 定期清理下载的旧图片
├── data/                               # 生成的结构化 JSON
├── docs/                               # 生成的网页/日报（看这里）
├── downloads/                          # 本地下载目录（已被 gitignore）
├── 上传到GitHub.bat                     # Windows 一键推送
└── 本地运行并打开.bat                   # Windows 本地采集并打开网页
```

## 最简单使用流程（3 步）

> Windows 用户可以直接双击：
> - **`上传到GitHub.bat`**：自动把项目推送到 GitHub（需要先新建一个空仓库并复制地址）
> - **`本地运行并打开.bat`**：在本地采集一次并自动打开网页版表情墙

### 第 1 步：把项目放到 GitHub

如果你会用命令行，在 `emoji-collector` 文件夹里执行：

```bash
git init
git add .
git commit -m "init emoji collector"
git remote add origin https://github.com/你的用户名/仓库名.git
git push -u origin main
```

如果你不想用命令行，可以用 **GitHub Desktop**：
1. 安装并登录 GitHub Desktop
2. `File` → `Add Local Repository...` 选择 `C:\deepseek\emoji-collector`
3. 点 **Publish repository**，建议选 Public（公开仓库 Actions 免费额度无限）

### 第 2 步：手动跑一次，立刻出结果

推送后打开仓库网页 → **Actions** 页 → 左侧点 **Daily Hot Emoji** → 右边 **Run workflow** → 等 1~2 分钟。

之后每天会自动在北京时间 **06:10** 左右运行，不用再管。

### 第 3 步：打开网页看表情墙

运行完成后，在仓库里打开：

- **`docs/index.html`** ← 这是入口，点日期就能看当天的表情墙
- `docs/2025-01-01.html` ← 某一天的完整表情墙，最上面有“今日推荐”总结和 Top 3

如果你想更方便，可以开启 **GitHub Pages**：
1. 仓库页面 → **Settings** → **Pages**
2. Source 选 `Deploy from a branch`，Branch 选 `main`，目录选 `/docs`
3. 保存后访问：

```
https://你的用户名.github.io/仓库名/
```

以后每天自动更新，打开这个网址就是最新表情墙。

### 需要下载图片时（可选）

看到喜欢的表情包，本地运行：

```bash
# 下载当天前 5 个
python scripts/download_selected.py data/2025-01-01.json --max 5

# 指定保存目录
python scripts/download_selected.py data/2025-01-01.json --output ./downloads --max 10
```

下载的图片在 `downloads/`，不会提交到 GitHub。

## 本地访问方式

- 直接双击打开文件：`C:\deepseek\emoji-collector\docs\index.html`
- 更推荐用本地网址访问：双击 **`启动本地网页.bat`**，然后浏览器打开：
  ```
  http://localhost:8765/
  ```
  一个页面里就有：最近热门梗、搜索框、最新表情墙、最近日报。
  关闭那个黑色窗口即可停止服务。
- 老梗搜索页（备用）：
  ```
  http://localhost:8765/search.html
  ```
- **联网搜索**必须通过 `启动本地网页.bat` 启动（运行 `server.py`），直接双击 HTML 文件只能搜本地历史。

## 本地资源占用与清理

**默认情况下图片不占本地资源**：
- 日报里的图片都是**外链**，没有下载到本地，只保存文字链接。
- 只有你主动运行下载脚本后，图片才会出现在 `downloads/`。

**定期清理**：

- 日报文件（`data/`、`docs/`）会自动只保留最近 `--keep-days 180` 天，旧的自动删除。
- 下载到本地的图片可以用清理脚本删除超过 N 天的文件：
  ```bash
  # 删除 downloads/ 里超过 30 天的图片
  python scripts/cleanup_downloads.py --days 30

  # 删除超过 7 天的
  python scripts/cleanup_downloads.py --days 7
  ```

## 当前数据源

| 源 | 方式 | 说明 |
| --- | --- | --- |
| 搜狗微信 | 搜索 10 组表情包关键词 | **公众号表情文章**，每天约 60 条带图结果 |

> 已排除：斗图啦、Reddit、微博、发表情、贴吧、逗逼表情包。

**关于排序**：搜狗微信不直接提供“阅读量/点赞数”，公众号文章页也有反爬，所以拿不到真实阅读量。  
当前使用**综合热度分**从高到低排序：  
- 同一篇文章被多个关键词搜到 → 加分  
- 在搜索结果中排得越靠前 → 加分  
- 发布越新 → 加分

**关于老梗/二创**：很多热门表情包是“老梗新做”，比如“草地牛”火了很久但一直有新公众号发。  
日报会额外识别**今日热门梗**：从标题里找出被多个不同公众号反复提到的具体名字，按出现篇数展示。  
这样你能一眼看到“哪个梗今天被引用最多”，而不是只看单篇文章新旧。  
如果当天没有明显重复的梗名，会显示“暂无明显重复梗”，不会硬凑。

某些站点有反爬/改版风险。如果某天某个源失败，脚本会自动跳过，不影响日报生成。

> **地域提示**：GitHub 官方 runner 通常位于美国/欧洲，访问部分国内站点（微博、贴吧等）可能较慢或被风控拦截。
> 如果日报经常为空，可以在你本地电脑直接运行 `python scripts/collect.py` 测试；
> 或者改用更稳定的公开 API 源，也可以考虑在能访问国内网络的机器上部署自托管 runner（会带来额外维护成本）。

## 自定义

- 默认只采集：搜狗微信（微信公众号）。
- 改抓取数量：编辑 workflow 中 `--top 60`。
- 改保留天数：编辑 `--keep-days 180`。
- 过滤太旧的内容（默认不过滤，但新的会排在前面）：
  ```bash
  # 只保留最近 90 天
  python scripts/collect.py --max-age-days 90
  ```
- 如果以后想临时加回其他源：
  ```bash
  python scripts/collect.py --sources sogou_weixin,doutu
  ```
- 新增数据源：在 `scripts/collect.py` 的 `SOURCES` 字典里加一个函数即可。

## 注意事项

- 本项目只做**外链聚合**，不生产、不复制原图。
- 表情包仍可能受版权/平台规则保护，个人自用一般没问题；若用于公众号、视频、商业用途，请确认来源授权或使用可商用素材。
- 抓取第三方网站请遵守其 `robots.txt` 和服务条款；优先使用官方/公开接口。
