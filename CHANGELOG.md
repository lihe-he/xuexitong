# Changelog

本项目遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### Changed
- README 去掉与同类项目的对比表述，改为只讲本项目的设计取舍
- `docs/experience.md` 从"拆解点评"改为"参考项目与借鉴"，只记采用了什么做法

### 计划
- 真实活动验证：六种签到逐个跑通
- 授权页（代签 C 档，一次性 grant token）
- 位置坐标自动逼近

## [0.2.1] — 2026-11-16

### Added
- **端到端回放测试**：`tests/conftest.py` 起一个可编程的假学习通服务端，
  26 条用例真发 HTTP 请求，覆盖六种签到的参数拼装、回执解析、上报链、未登录识别
- **运维工具收敛**：14 个散落脚本合并为 `python -m cxsign.tools <子命令>`
  （`status` / `live` / `diag` / `probe` / `qr` / `browser` / `catcher`）
- **诊断命令**：`diag` 能定位"哪个域不通、缺哪个关键 cookie"
- 接口探测支持 `--qr`，专测二维码相关路径
- CI（GitHub Actions）：3 个 Python 版本 + 可选 QR 依赖单独跑
- `CONTRIBUTING.md`、issue 模板、CHANGELOG

### Fixed
- **`httpx.Client()` 初始化 1.04 秒**（Windows 每次重建 SSL 上下文），
  共享上下文后 0.03 秒；全量测试 100s → 6.8s，多账号启动开销同步下降
- 姓名解析：`id="messageName"` 元素已不存在，改用 `p.fr.colorBlue` 行 +
  实名认证行兜底
- 课程列表解析：全局正则会把 A 课的 classId 和 B 课的 courseId 串到一起，
  改为按 `<div class="course clearfix` 切块
- `log.setup()` 漏 `global` 声明导致监听启动即崩
- 多账号时 CLI 卡在选账号上；新增 `cxsign rm` 删除账号
- `QrPayload` 缺 `enc` 字段导致 `/api/qr/decode` 500

### Changed
- Web UI 拆成 `index.html` + `app.css` + `app.js`，通过 `/static` 挂载
- 签到提交不再重试 5xx（重试会把有效 enc 拖到过期）

## [0.2.0] — 2026-11-16

### Added
- **身份隔离层**：一账号一份 `deviceCode` + UA + 出口 IP，按账号稳定派生
- **行为抖动**：发现签到后随机等 3~25 秒；多账号签同一活动额外错峰
- **凭据加密**：Fernet 静态加密，主密钥三级回退（env → 文件 → 报错）
- **全局令牌桶**：跨账号共享总出口速率（默认 8 次/秒）
- **指数退避**：`TooFrequent` → 30s → 60s → 120s，上限 600s，账号级隔离
- **Cookie 托管**（代签 B 档）：`import_cookies()`，不保存密码
- **审计闭环**：`delegations` 表 + `sign_logs.delegation_id` + `logs_with_operator()`
- **二维码图片解码**：可选 `opencv-python-headless`，Web UI 直接传截图
- **二维码抢签**：`qr_race`，截图监听 + 目标缓存（定位 0ms）+ enc 池复用
- 日志轮转（5MB × 5 份）
- 老库自动升级：明文密码就地加密、缺列自动补

## [0.1.0] — 2026-11-16

首个可用版本。

### Added
- 手机号密码登录（AES-CBC 主用 / DES-ECB 兼容），Cookie 持久化
- 登录态校验 + 自动重登
- 课程列表、活动列表、活动详情
- 类型判定：`otherId` + `ifphoto` + `activeSort` 三重兜底
- 反作弊上报链：`preSign → analysis → analysis2`
- 六种签到：普通 / 手势 / 位置 / 拍照 / 签到码 / 二维码
- 位置签到 BD-09 + 随机抖动 + 距离解析
- 拍照签到云盘上传 / 复用 `0.jpg`
- 群聊签到（无课程活动）
- 轮询监听 + 内存 / DB 双层去重
- 推送：Server酱 / PushPlus / Telegram / Webhook
- FastAPI + Web UI，CLI，Docker
