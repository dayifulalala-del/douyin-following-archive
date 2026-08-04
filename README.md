# 抖音关注珍藏（本地开源版）

一个在本机运行的 Chrome 扩展，用来同步当前抖音账号的关注列表，并按作者备份公开作品。项目不设置人为的作者人数上限，下载记录保存在本地，可避免重复保存已经归档的作品。

> 本项目仅供个人备份自己有权保存的内容。请遵守抖音服务条款、版权规则和所在地法律，不要用于批量转载、商业分发或规避平台安全措施。

## 主要功能

- 每次打开“关注的人下载”都会先重新同步关注列表。
- 按作者选择并下载公开作品，没有人为的 50 位作者限制。
- 支持导入旧“抖珍藏”归档记录，已有视频不会因为迁移而重新下载。
- 支持点赞、收藏作品备份。
- 使用系统文件夹选择器指定保存位置。
- Cookie 只发送到本机服务 `127.0.0.1:8766`，不会上传到第三方服务器。
- 下载历史使用本地 SQLite 数据库去重。

## 环境要求

- Windows 10 或 Windows 11
- Google Chrome
- Python 3.9 以上（推荐 Python 3.12）
- 已登录抖音网页版的账号

## 快速开始

1. 下载或克隆本仓库。
2. 双击 `启动浏览器扩展服务.cmd`。首次运行会自动创建 Python 环境并安装依赖。
3. 在 Chrome 地址栏打开 `chrome://extensions/`。
4. 打开右上角“开发者模式”，点击“加载已解压的扩展程序”。
5. 选择本项目中的 `chrome-extension` 文件夹。
6. 打开并登录 `https://www.douyin.com/`，点击工具栏里的“抖音关注珍藏”。
7. 选择归档文件夹，然后进入“关注的人下载”。扩展会先同步最新关注列表，再显示作者选择页面。

如果以前使用过抖珍藏，可在扩展中选择原归档文件夹并执行一次旧记录导入。导入只登记作品 ID，不会移动或删除原视频。

## 隐私与本地数据

以下内容默认被 `.gitignore` 排除，不应提交到 GitHub：

- `.cookies.json`、`config/cookies.json`：抖音登录 Cookie
- `config.yml`：个人运行配置
- `state/`：关注列表、下载历史数据库和任务状态
- `Downloaded*`、视频、音频：下载内容
- 抖珍藏的 `data/` 和 `本地库.html`

如果你准备 fork 或公开仓库，请再次确认这些文件没有被手动强制加入 Git。

## 开发与测试

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[browser]"
.\.venv\Scripts\python.exe -m pytest tests\test_local_bridge.py tests\test_following_sync.py tests\test_following_batch.py tests\test_import_douzhencang.py
.\.venv\Scripts\ruff.exe check local_bridge.py tests\test_local_bridge.py
```

浏览器扩展版本位于 `chrome-extension/manifest.json`。

## 开源来源与许可证

本项目基于 [jiji262/douyin-downloader](https://github.com/jiji262/douyin-downloader) 的 MIT 许可代码扩展而来，并保留原项目的版权声明和 `LICENSE`。原项目说明见 [UPSTREAM_README.md](UPSTREAM_README.md) 和 [UPSTREAM_README.zh-CN.md](UPSTREAM_README.zh-CN.md)。

本项目与抖音、字节跳动及原“抖珍藏”扩展无隶属或官方合作关系。
