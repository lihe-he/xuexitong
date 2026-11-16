# cxsign · 超星学习通自动签到

协议复现，不刷浏览器，不装 App。一个 `httpx.Client` 把签到做完。

支持 **普通 / 手势 / 位置 / 拍照 / 签到码 / 二维码** 六种签到，多账号、监听自动签、多渠道推送、
Web UI 和 CLI 双入口，Docker 一行起。

* **身份隔离**：一账号一份 `deviceCode` + UA + 出口 IP + 时间抖动
* **凭据加密**：密码 Fernet 静态加密，主密钥支持环境变量注入
* **Cookie 托管**：代签只存 Cookie 不碰密码，改密码即天然撤销
* **二维码传图**：截屏上传直接解出 `enc`，不用手抄
* **限流退避**：全局令牌桶 + 账号级指数退避

```
┌─ 监听到签到 ──────────────────────────────────────┐
│ 10:02:31  ✅ 签到成功｜普通签到                      │
│           数据结构与算法(2024-01)                  │
│           签到  ·  success                        │
└──────────────────────────────────────────────────┘
```

---

## 设计取舍

这类工具的路线基本有两条：**驱动界面**（浏览器 / WebView / 真机自动化）和**复现协议**（直接发 HTTP）。
本项目选后者，因为签到本身只是一次表单提交，不需要渲染任何页面。

| 维度 | 本项目的选择 |
|---|---|
| 语言 | Python 3.11+，无前端构建步骤 |
| 部署 | `docker compose up -d`，镜像约 32MB |
| 协议 | 所有 URL 集中在 [`endpoints.py`](cxsign/endpoints.py)，带 `[稳]/[验]/[推]/[✗]` 可信度标注 |
| 类型判定 | `otherId` + `ifphoto` + `activeSort` 三重兜底，14 条单测 |
| 反作弊链 | `preSign → analysis → analysis2` 独立模块，可开关 |
| 去重 | 内存 set + SQLite 双层，重启不重复签到 |
| 身份隔离 | 一账号一份 `deviceCode` + UA + 出口 IP + 时间抖动 |
| 边界 | 不做伪造活动、不做人脸绕过、不接打码平台 |

这个领域的早期探索者留下的实践记录，是我做设计时的主要参考，
整理在 [docs/experience.md](docs/experience.md)。

---

## 快速开始

### 方式一：Docker（推荐）

```bash
git clone https://github.com/yourname/cxsign.git
cd cxsign
docker compose up -d
```

打开 <http://127.0.0.1:8000>，填手机号密码登录，点「同步课程」→「启动监听」。

### 方式二：本地

```bash
pip install -e .
cp config.example.toml config.toml     # 按需改
python -m cxsign.server --port 8000    # Web UI
```

或者纯命令行：

```bash
python -m cxsign login   --user 13800000000 --password '你的密码'
python -m cxsign courses --sync
python -m cxsign scan
python -m cxsign monitor
```

---

## CLI

```
cxsign login    --user <手机号> --password <密码>   登录并存 Cookie
cxsign courses  [--sync]                          列课程
cxsign scan     [--sync]                          扫进行中的签到
cxsign sign     --active <activeId> [选项]         手动签一个
cxsign monitor  [--interval 20] [--dry-run]       监听并自动签
```

手动签的各种参数：

```bash
# 签到码
cxsign sign --active 123456789 --code 4821

# 二维码（扫码后把 enc 后面的值贴进来，或整段 URL 也行）
cxsign sign --active 123456789 --enc 1D0A628CK317F44CCC378M5KD92

# 位置
cxsign sign --active 123456789 --lat 34.817038 --lon 113.516288 \
            --address "河南省郑州市高新区科学大道100号"

# 拍照（本地图片会自动上传云盘）
cxsign sign --active 123456789 --photo ./me.jpg
```

多账号用 `--account 13800000000` 指定。

---

## 配置

复制 `config.example.toml` 为 `config.toml`。重点几项：

```toml
poll_interval = 20          # 轮询间隔，15~25 秒足够
activity_ttl  = 150         # 活动开始超过这么久就不重试了

default_lat = "34.817038"   # 位置签到默认点位（必须是 BD-09 百度坐标）
default_lon = "113.516288"
default_address = "河南省郑州市…"
location_jitter_m = 8.0     # 每次签到随机抖动 8 米

global_rate = 8.0           # 全进程总出口速率（次/秒）
backoff_base = 30.0         # 被限流后退避 30s，之后翻倍，上限 600s
```

也可用环境变量覆盖：`CXSIGN_DATA`、`CXSIGN_POLL`、`CXSIGN_PROXY`、`CXSIGN_TIMEOUT`、
`CXSIGN_INTERVAL`、`CXSIGN_RETRIES`、`CXSIGN_ACTIVITY_TTL`、`CXSIGN_CONFIG`、
`CXSIGN_SECRET`（加密主密钥）。

### 主密钥

密码用 Fernet 加密后落库。主密钥按这个顺序取：

1. 环境变量 `CXSIGN_SECRET`（44 字节 base64 Fernet key，容器部署推荐）
2. `<data_dir>/secret.key`（首次启动自动生成）
3. 都没有就报错，**不会**静默降级成明文

```bash
# 生成一把
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

⚠️ 换主密钥会导致旧密码解不开（会提示重新登录），换之前先备份。

推送支持 Server酱、PushPlus、Telegram、通用 Webhook，可同时开多个：

```toml
[notify.serverchan]
enabled = true
sendkey = "SCTxxxxx"
```

---

## 多账号与代签

代码路径和多账号完全一样（`engine` 从一开始就按 `account_id` 隔离 Session），
但**能不能做干净，取决于隔离层**。本项目已实现：

```toml
isolate_identity = true
proxy_pool = ["http://127.0.0.1:7891", "socks5://127.0.0.1:7892"]
sign_delay_min = 3.0
sign_delay_max = 25.0
multi_account_spread = 4.0
```

一账号一份稳定身份（`sha256(account_id:username)` 派生，首次生成后落库不再漂移）：

```
13800000001  device=b2638445…  proxy=:7891  ua=Samsung SM-S9110
13800000002  device=3cb7ffe7…  proxy=:7892  ua=Redmi K50
13800000003  device=d76e30a3…  proxy=:7891  ua=OPPO Find X6
```

**两种托管模式**：

| 模式 | 入口 | 存什么 | 撤销方式 |
|---|---|---|---|
| 密码登录 | Web UI「密码登录」/ `cxsign login` | 加密后的密码 + Cookie | 对方改密码 |
| Cookie 托管 | Web UI「Cookie 托管」/ `POST /api/accounts/import` | 只存 Cookie | 对方改密码即失效，或 `POST /api/delegations/{id}/revoke` |

配合 `delegations` 表 + `sign_logs.delegation_id`，签到记录能显示"这次是谁授权签的"。
完整设计（三种授权模型、风控特征表、池子不够大怎么办）：[docs/delegation.md](docs/delegation.md)。

> 关键提醒：**身份要保持稳定，行为要有抖动**。一个学号一天换三台设备，比一直用同一台更可疑。

---

## 关于三种"难签"的类型

**二维码签到**：`enc` 只存在于老师屏幕的动态二维码里，约 30 秒轮换，纯服务端拿不到。
三种输入方式：

1. Web UI 点「传图」→ 选一张二维码截图 → 服务端本地解码出 `enc`
2. 粘扫码文本（整段 URL 也行，`extract_enc()` 自动抠）
3. CLI `--enc` 直接给值

解码走本地 `opencv`（`pip install -e ".[qr]"`），**不接任何在线打码平台** —— 那会把 enc
和你的账号关联到第三方。

**位置签到**：坐标必须是 **BD-09**（百度坐标系），不是 GPS 的 WGS-84，传错会偏 300~600 米。
失败时接口会回你「距离签到位置 N 米」，这个数字就是最好的自检信号 —— 本项目会把它直接
写进错误提示。点位从 [百度坐标拾取](https://api.map.baidu.com/lbsapi/getpoint/index.html) 取。

**拍照签到**：先把图传到超星云盘。两条路：手工传到根目录命名 `0.jpg`，或 `--photo` 传本地图
自动上传。注意「普通签到」和「拍照签到」在协议上是同一个 `otherId=0`，靠 `ifphoto` 区分，
本项目会自动读详情纠正。

---

## 项目结构

```
cxsign/
├── endpoints.py   全部 URL ← 协议变更只改这里
├── net.py         Session：Cookie / 限速 / 重试 / 302 判定 / SSL 复用
├── ratelimit.py   全局令牌桶（跨账号总出口速率）
├── crypto.py      AES-CBC + DES-ECB 密码加密（传输用）
├── security.py    Fernet 静态加密（落库用）+ 主密钥管理
├── identity.py    设备人格：deviceCode / UA / 出口 IP
├── auth.py        登录 / 校验 / 自动重登 / 姓名 / 学校
├── course.py      课程列表 + Cookie 解析
├── activity.py    活动列表 + classify() 类型判定 + 未登录识别
├── presign.py     preSign → analysis → analysis2
├── signer/        六种签到实现
├── qrdecode.py    二维码截图解码（可选 opencv）
├── monitor.py     轮询监听 + 抖动 + 退避
├── notify.py      推送扇出
├── store.py       SQLite（含 delegations 审计表）
├── runtime.py     装配：settings + 密钥 + store + engine + bucket
├── log.py         日志（轮转）
├── server/        FastAPI + UI（index.html / app.css / app.js）
└── tools/         运维诊断（status / live / diag / probe / qr / browser / catcher）
```

完整目录树与"改代码前先看哪三处"见 [docs/structure.md](docs/structure.md)。

---

## 运维与诊断

```bash
python -m cxsign.tools status                    # 账号 / 课程 / 配置 / 近期签到
python -m cxsign.tools live --user U --password P # 登录 + 只读链路验证
python -m cxsign.tools diag                      # 哪个域不通、缺哪个 cookie
python -m cxsign.tools probe [--qr]              # 接口还活着吗（无需登录）
python -m cxsign.tools qr --dir data/qr          # 二维码抢签
python -m cxsign.tools browser --scan            # 从浏览器 profile 导 cookie
python -m cxsign.tools catcher                   # 本地 cookie 接收器（带粘贴框）
```

出问题的排查顺序：`diag` → `probe` → `live`。
前者告诉你"账号还是协议的问题"，后者告诉你"接口还活着吗"。

* 架构与设计取舍：[docs/design.md](docs/design.md)
* 接口协议速查：[docs/protocol.md](docs/protocol.md)
* 参考项目与借鉴：[docs/experience.md](docs/experience.md)
* 多账号 / 代签的授权与隔离：[docs/delegation.md](docs/delegation.md)
* 目录结构与改动指引：[docs/structure.md](docs/structure.md)
* 路线图：[docs/roadmap.md](docs/roadmap.md)
* 变更记录：[CHANGELOG.md](CHANGELOG.md)
* 贡献指南：[CONTRIBUTING.md](CONTRIBUTING.md)

---

## FAQ

**Q：会签到被老师发现吗？**
A：签到结果和手动签一样（同一条接口、同一个 `preSign` 上报链）。位置签到默认加了 8 米抖动，
不会出现全班坐标一模一样的情况。但**提交时间会非常准时**，这是任何自动化的共同特征。

**Q：为什么监听是 20 秒轮询，不是实时推送？**
A：学习通的推送走 App 内部 IM 协议，逆向成本高且随时变更。20 秒轮询从老师开签到到自动签上
通常也在 20 秒内，性价比最高。

**Q：Cookie 过期怎么办？**
A：项目里存了密码，`ensure_session()` 检测到 302 会自动重登并回写 Cookie。前提是登录时用的是
手机号+密码，而不是从浏览器复制 Cookie。

**Q：登录报「账号或密码错误」但密码没错？**
A：多半触发了滑块风控。换网络（4G/家宽）、隔几分钟、或用网页版手动登录一次解锁。

**Q：支持学号登录 / 统一身份认证吗？**
A：暂不支持。机构 SSO 走的是各校自己的 CAS，不通用。当前只做手机号+密码。

**Q：密码怎么存的？**
A：Fernet（AES-128-CBC + HMAC）静态加密后落库，主密钥走环境变量或 `data/secret.key`。
老库里如果有明文，启动时自动就地加密。要上公网请务必用 `CXSIGN_SECRET` 注入密钥，
而不是让程序生成文件。

**Q：能部署到公网吗？**
A：技术上可以，但 **不建议**。UI 没有登录认证。要上公网至少加：反向代理 + Basic Auth、
`CXSIGN_SECRET` 注入、把 `data/` 挂到加密卷。

---

## 免责声明

本项目仅供**学习 HTTP 协议、Cookie 鉴权与接口逆向分析**使用。

* 它完成的是"本来该你自己点的那一下"，不伪造签到、不绕过人脸
* 多账号/代签属于凭证托管，涉及他人账号时**请先取得对方明确授权**，并保留授权记录
* 使用者需自行承担因使用本工具导致的一切后果
* 请勿用于违反所在学校规定的场景；签到是出勤记录，长期缺席的代价远大于一次签到
* 作者不对任何账号异常、成绩影响、纪律处分负责

如果项目对你有帮助，请优先考虑：**按时去上课**。

## License

[MIT](LICENSE)
