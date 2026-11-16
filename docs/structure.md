# 项目结构速查

```
cxsign/
├── cxsign/                     源码（5.1k 行）
│   ├── endpoints.py            全部 URL ← 协议变更只改这里
│   ├── config.py               Settings（TOML + 环境变量）
│   ├── crypto.py               AES-CBC / DES-ECB（传输用，学习通要求的）
│   ├── security.py             Fernet（落库用，主密钥自己管）
│   ├── identity.py             设备人格：deviceCode / UA / 出口 IP
│   ├── ratelimit.py            全局令牌桶
│   ├── net.py                  Session：Cookie / 限速 / 重试 / 302 判定 / SSL 复用
│   ├── auth.py                 登录 / 校验 / 姓名 / 学校
│   ├── course.py               课程列表 + Cookie 解析
│   ├── activity.py             活动列表 + classify() 类型判定 + 未登录识别
│   ├── presign.py              preSign → analysis → analysis2
│   ├── signer/                 六种签到：base / general / location / qrcode / photo
│   ├── qrdecode.py             二维码截图解码（可选 opencv）
│   ├── chat.py                 群聊签到（无课程）
│   ├── engine.py               业务编排 + 并发扫描 + 退避 + Cookie 托管
│   ├── monitor.py              轮询监听 + 反应抖动
│   ├── notify.py               推送扇出
│   ├── store.py                SQLite（accounts/courses/sign_logs/delegations/kv）
│   ├── runtime.py              装配：settings + 密钥 + store + engine + bucket
│   ├── log.py                  日志（控制台 + 5MB×5 轮转）
│   ├── cli.py                  命令行
│   ├── server/                 FastAPI + UI（main.py / cli.py / static/）
│   └── tools/                  运维诊断（status/live/diag/probe/qr/browser/catcher）
├── tests/                      166 条测试
│   ├── conftest.py             可编程假服务端（端到端回放）
│   ├── test_core.py            类型判定 / 加密 / 回执解析
│   ├── test_e2e_sign.py        六种签到端到端
│   ├── test_live_payloads.py   真实报文回归
│   ├── test_parsers.py         页面结构解析
│   ├── test_runtime.py         加密落库 / 退避 / 托管 / 审计
│   ├── test_identity.py        身份隔离
│   ├── test_enc_cache.py       enc 池
│   ├── test_log.py             日志
│   └── test_v2.py              令牌桶 / cookie 解析 / 二维码
├── docs/
│   ├── protocol.md             ★ 接口协议速查（含实测记录）
│   ├── design.md               架构与设计取舍
│   ├── experience.md           参考项目与借鉴
│   ├── delegation.md           代签的授权模型与隔离
│   └── roadmap.md              路线图 + 明确不做
├── .github/
│   ├── workflows/ci.yml        pytest + ruff，3 个 Python 版本
│   └── ISSUE_TEMPLATE/         bug / 协议变更
├── config.example.toml
├── Dockerfile / docker-compose.yml
├── CONTRIBUTING.md / CHANGELOG.md / LICENSE
└── README.md
```

## 改代码前先看这三处

| 要改什么 | 去哪 |
|---|---|
| 接口地址 / 参数 | `cxsign/endpoints.py` + `docs/protocol.md` |
| 签到类型判定 | `cxsign/activity.py::classify` + `tests/test_core.py` |
| 签到参数拼装 | `cxsign/signer/base.py::base_params` + `tests/test_e2e_sign.py` |
