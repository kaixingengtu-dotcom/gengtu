# 每日热门表情包采集器（低成本版）

一个使用 **GitHub Actions + Python 标准库** 的每日中文热门表情包采集器。

- **不调用任何 AI/LLM API**，因此没有 Token 费用。
- **不下载原图入库**，只生成 Markdown/JSON 外链清单，GitHub 存储占用极小。
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
├── scripts/
│   ├── collect.py                      # 采集 + 生成日报（Actions 中运行）
│   └── download_selected.py            # 本地按需下载图片（手动运行）
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
- `docs/2025-01-01.html` ← 某一天的完整表情墙，图片一排排展示

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

## 当前数据源

| 源 | 方式 | 说明 |
| --- | --- | --- |
| 微博 | 移动端搜索 JSON | 搜“表情包”，按互动量给热度分，尽量取新内容 |
| 发表情 | 热门列表页解析 | 图片外链 |
| 斗图啦 | 文章/图片列表页解析 | 图片外链 |
| 贴吧 | “表情包”吧帖子列表 | 目前可能没有封面图，后续可增强 |
| 逗逼表情包 | 公开搜索接口 | 尽力而为 |
| Reddit（可选） | r/memes hot.json | 默认不启用；GitHub 官方 runner 访问国内源失败时可作外网兜底 |

某些站点有反爬/改版风险。如果某天某个源失败，脚本会自动跳过，不影响日报生成。

> **地域提示**：GitHub 官方 runner 通常位于美国/欧洲，访问部分国内站点（微博、贴吧等）可能较慢或被风控拦截。
> 如果日报经常为空，可以在你本地电脑直接运行 `python scripts/collect.py` 测试；
> 或者改用更稳定的公开 API 源，也可以考虑在能访问国内网络的机器上部署自托管 runner（会带来额外维护成本）。

## 自定义

- 改抓取数量：编辑 workflow 中 `--top 30`。
- 改保留天数：编辑 `--keep-days 30`。
- 禁用不稳定的源：
  ```bash
  python scripts/collect.py --sources weibo,fabiaoqing
  ```
- 启用 Reddit 外网兜底：
  ```bash
  python scripts/collect.py --sources weibo,fabiaoqing,doutu,tieba,dbbqb,reddit
  ```
  如需在 GitHub Actions 中也启用，可修改 workflow 里的命令：
  ```bash
  python scripts/collect.py --top 30 --keep-days 30 --sources weibo,fabiaoqing,doutu,tieba,dbbqb,reddit
  ```
- 新增数据源：在 `scripts/collect.py` 的 `SOURCES` 字典里加一个函数即可。

## 注意事项

- 本项目只做**外链聚合**，不生产、不复制原图。
- 表情包仍可能受版权/平台规则保护，个人自用一般没问题；若用于公众号、视频、商业用途，请确认来源授权或使用可商用素材。
- 抓取第三方网站请遵守其 `robots.txt` 和服务条款；优先使用官方/公开接口。
