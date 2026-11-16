# 架构

```
                       ┌──────────────────────────────┐
                       │  Web UI  (单页 HTML + fetch)  │
                       └───────────────┬──────────────┘
                     CLI (argparse) ───┤
                                       ▼
                       ┌──────────────────────────────┐
                       │  FastAPI  (server/main.py)   │
                       └───────────────┬──────────────┘
                                       ▼
        ┌──────────────────────────────────────────────────────┐
        │  Engine (engine.py)                                  │
        │   ├── ensure_session  登录态校验 / 自动重登             │
        │   ├── sync_courses    课程缓存                          │
        │   ├── scan            多课程并发扫描进行中活动             │
        │   └── sign            类型纠正 + 分发 + 落日志            │
        └──────┬────────────────┬─────────────────┬────────────┘
               │                │                 │
        ┌──────▼─────┐   ┌──────▼──────┐   ┌──────▼──────┐
        │ activity   │   │  presign    │   │   signer    │
        │ 类型判定     │   │ 三连上报链    │   │ 六种签到实现  │
        └──────┬─────┘   └──────┬──────┘   └──────┬──────┘
               └────────────────┴─────────────────┘
                                ▼
                    ┌───────────────────────┐
                    │  net.Session          │
                    │  Cookie / 限速 / 重试  │
                    │  302→AuthExpired      │
                    └───────────┬───────────┘
                                ▼
                    ┌───────────────────────┐
                    │  endpoints.py (URL 表) │
                    └───────────────────────┘

  横切：store.py（SQLite）  notify.py（推送）  monitor.py（轮询）
```

## 关键设计决策

### 1. 一个账号 = 一个 `Session`，不是全局单例

`SessionManager` 单例是很多老项目的写法（比如把 Cookie 存进类变量），
多账号并发时会串 Cookie —— Cookie 泄露到别人的请求里，签到记到别人头上。
本项目 `Engine._sessions: dict[account_id, Session]`，每账号独立 `httpx.Client`。

### 2. 同步 IO，不是 async

签到场景的并发量是「10 个账号 × 30 门课」，瓶颈在**网络 RTT**不在 CPU。
用同步 `httpx.Client` + 线程池（FastAPI 的 `def` 路由自动走 anyio 线程池）比
`asyncio` + `aiohttp` 少一半代码，调试栈也更好读。
真要并发，瓶颈是学习通的限流，不是我们的调度器。

### 3. 登录态失效即重登，把密码当凭证

学习通 Cookie 有效期不稳定（几天到几周）。只存 Cookie 的项目一定会遇到"某天起就不签了"。
本项目同时存 Cookie + 密码，`ensure_session()` 先校验再按需重登，Cookie 回写数据库。
密码用 SQLite 明文存（本地单机场景），部署到公网请自行叠加加密。

### 4. 类型判定单独成函数，配测试

`activity.classify()` 是纯函数，覆盖 `otherId` 全值 + `ifphoto` 分支 + `activeSort` 兜底，
14 个参数化用例。改协议时先改它、跑测试，再动链路。

### 5. 签到前的上报链是独立模块

`presign.run_chain()` 可被 `skip_presign=True` 跳过 —— 这在调试时非常有用：
先用 `skip_presign` 确认参数对不对，再打开验证上报链是否必需。

### 6. 失败不标记完成，靠时间窗收敛

`monitor.tick()` 对失败的活动**不写 `handled`**，下轮会重试；
但当 `age_seconds > activity_ttl`（默认 150s）后放弃，避免对已截止活动无限重试。

### 7. 所有外部输入都能从配置注入

URL 在 `endpoints.py`，UA / 间隔 / 点位 / 推送在 `config.toml`，
环境变量可覆盖（`CXSIGN_*`）。容器里不需要改代码。

## 数据流：一次完整的自动签到

```
monitor.tick()
  → store.list_accounts(only_enabled=True)
  → engine.scan(account_id)
      → ensure_session()            # 302? → relogin
      → course.list_courses()
      → activity.list_activities()  # 每门课一次，TooFrequent 退避
  → 过滤出 status=1 且 otherId 0~5
  → 去重（内存 set + sign_logs.ok=1）
  → engine.sign()
      → get_active_info() 纠正类型（otherId=0 → 可能是拍照）
      → presign.run_chain()         # preSign → analysis → analysis2 → sleep 500ms
      → signer.sign() 按 kind 分发
          → base_params() + 类型参数
          → GET/POST stuSignajax
          → parse_reply()  →  success / 距离 N 米 / 需 enc ...
      → store.add_log()
  → notify.notify() 扇出到各通道
```

## 目录

```
cxsign/
├── config.py       Settings（TOML + 环境变量）
├── endpoints.py    全部 URL ← 协议变更只改这里
├── crypto.py       AES-CBC / DES-ECB 密码加密（**传输用**，fanyalogin）
├── security.py     Fernet 静态加密（**落库用**）+ 主密钥三级回退
├── identity.py     设备人格：deviceCode / UA / 出口 IP，按账号稳定派生
├── ratelimit.py    全局令牌桶（跨账号总出口）
├── net.py          Session：Cookie、限速、重试、302 识别
├── auth.py         login / validate / whoami / ensure_login
├── course.py       课程列表解析 + Cookie 解析
├── activity.py     activelist、活动详情、classify（类型判定）
├── presign.py      preSign → analysis → analysis2 上报链
├── signer/
│   ├── base.py     SignOptions / SignResult / parse_reply / 公共参数
│   ├── general.py  普通 / 手势 / 签到码
│   ├── location.py 位置（BD-09 + 抖动 + 距离解析）
│   ├── qrcode.py   二维码（enc 解析 + location JSON）
│   └── photo.py    拍照（云盘 token / 列表 / 上传）
├── qrdecode.py     二维码截图解码（可选 opencv）
├── chat.py         群聊签到（无课程）
├── engine.py       业务编排 + 并发扫描 + 退避 + Cookie 托管
├── monitor.py      轮询监听 + 反应时间抖动
├── notify.py       推送扇出
├── store.py        SQLite（accounts / courses / sign_logs / delegations）
├── runtime.py      装配：settings + 密钥 + store + engine + bucket
├── log.py          日志（控制台 + 5MB×5 轮转）
├── cli.py          命令行
└── server/         FastAPI + 单页 UI
```

## v0.2 新增的三条横切关注点

**1. 凭据分两层加密，别混。**

| 场景 | 模块 | 算法 | 为什么 |
|---|---|---|---|
| 发给 fanyalogin 的密码 | `crypto.py` | 学习通要求的 AES-CBC / DES-ECB | 服务端只认这个，密钥公开且固定 |
| 落在 SQLite 里的密码 | `security.py` | Fernet（AES-128-CBC + HMAC） | 主密钥自己管，可轮换 |

两者用途完全不同：前者是**协议的一部分**，后者是**存储保护**。混在一起写会很难解释漏洞。

**2. 限流分两层。**

```
Session._pace()   每账号节奏（0.4s/次）—— 防单账号被判脚本
GlobalBucket      全进程吞吐（8 次/秒）—— 防出口 IP 段被整段限流
```

并发扫描（`scan_concurrency=3`）必须在这两层的约束下跑，否则线程数一调高就自找限流。

**3. 退避是账号级的。**

`TooFrequent` 只影响**当前账号**：`engine._retry_after[account_id]` 记到什么时候能再打，
`_backoff_count` 记连续次数，`backoff_base * 2^n` 指数增长、`backoff_max` 封顶。
一个账号被限流不该拖慢其他账号。
