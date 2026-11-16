# 代签：把"能不能"拆成三个工程问题

## 结论先说

**能。** 而且代码里已经有 90% 了 —— `engine` 从一开始就按 `account_id` 隔离 `Session`，
一个进程托管 N 个账号和托管 1 个账号走的是完全相同的路径。

真正需要新写的是三件事：

| 问题 | 工作量 | 风险 |
|---|---|---|
| 授权与撤销 | 中 | 纠纷（"我什么时候让你签了"） |
| 身份隔离 | **大** | 技术（工具本身被识别） |
| 审计 | 小 | 同上 |

代码路径不变，所以本文只谈这三件事，不谈签到本身。

---

## 一、授权模型

代签的本质是**凭证托管**。按托管粒度从粗到细，三档：

### A. 密码托管（最省事，最难做干净）

对方把手机号+密码给你，你存进 `accounts.password`。

```
优点：永不过期，能自动重登（本项目的 ensure_session 就是为这个设计的）
缺点：你的库里有别人明文密码；对方改密码你就废了；一出事说不清
```

工程上必须补的：密码加密存储（现在默认明文，`v0.2` 会加 `cryptography.Fernet`）、
授权记录、随时可撤销。

### B. Cookie 托管（推荐）

对方在自己的手机上登录一次，导出 Cookie（`_uid` / `fid` / `_d` / `vc3`），把这一串给你。

```
优点：你拿不到密码；对方随时可以改密码踢你下线（天然撤销）
缺点：Cookie 会过期（几天到几周），过期后需要重新走一次
```

本项目的 `accounts.cookies` 就是为这个设计的，`password` 留空即可 ——
`ensure_session()` 会走到"无密码无法重登"的分支并抛 `AuthExpired`，然后在 UI 上提示重新授权。

### C. 一次一码授权（最干净，要开发）

你生成一个一次性的授权链接/短码，对方点开 → 在学习通登录页授权 → 回跳时带一个
只有一次有效、7 天过期的 grant token → 你用这个 token 换 Cookie。

```
优点：可撤销、可审计、无需密码
缺点：要自己写授权页 + 回调 + token 表，等于一个小型 OAuth
```

### 落地建议

先做 **B**，预留 **C** 的表结构。`delegations` 表已经建好了：

```sql
CREATE TABLE delegations (
    id, account_id, operator, grant_note, revoked, created_at, revoked_at
);
```

* `operator` —— 谁在代签（你的标识 / 子账号名）
* `grant_note` —— 授权凭据的**摘要**，不存原文
* `revoked=1` —— 撤销后 `engine.scan()` 跳过该账号，Cookie 立即失效

对应方法：`store.add_delegation()` / `revoke_delegation()` / `active_delegation()`。

### B 档已实现（v0.2）

```python
# 导入：只存 Cookie，密码字段清空
engine.import_cookies(
    username="13800000009",
    raw="_uid=111; fid=2222; _d=xyz; vc3=abc",   # 也吃 JSON / Cookie: 前缀 / 换行分隔
    operator="TA-01",
    note="口头授权，有效期到期末",
)
```

HTTP 对应 `POST /api/accounts/import`，Web UI 有独立的「Cookie 托管」卡片。

行为细节：

| 项 | 实现 |
|---|---|
| 凭证 | 只存 Cookie，`accounts.password` 置空 |
| 身份 | 导入时立即固化 `deviceCode` / UA / 出口 IP |
| 授权记录 | `operator` 非空则写一条 `delegations` |
| 登录态失效 | 抛 `AuthExpired` 提示"重新导入 Cookie"，**不会**尝试用空密码重登 |
| 撤销 | `POST /api/delegations/{id}/revoke` |
| 审计 | 签到日志 `delegation_id` 指回授权记录，UI 显示授权人 |

---

## 二、身份隔离（真正的工程量）

代签能被识别，靠的不是"你用了一台服务器"，而是**关联特征扎堆**。下面每一条都能单独把人串起来：

| 特征 | 服务端怎么看到 | 本项目对策 |
|---|---|---|
| 出口 IP | TCP 源地址 | `proxy_pool` + `identity.pick_proxy()`，按 `account_id` 取模，池够大时**零重复** |
| `User-Agent` | 请求头 | `UA_POOL` 12 个真实安卓机型，按账号稳定分配 |
| `deviceCode` | 签到接口参数 | `identity.make_device_code()`，32 位 hex，一账号一份，落库固定 |
| 提交时间 | 服务端收包时刻 | `sign_delay_min..max` 随机 3~25s，多账号再叠 `multi_account_spread` 递增错峰 |
| 坐标 | 位置签到参数 | `location_jitter_m`，默认 8 米随机偏移 |
| `_d` / `vc3` | Cookie | 服务端下发，天然按账号不同，不用管 |
| 请求节奏 | 时序特征 | `net._pace()`，每个 Session 独立限速，不会被识别成同一个客户端 |

### 已经实现的（本次提交）

```toml
isolate_identity = true          # 关掉就退化为全局统一 UA / 代理

proxy_pool = [                   # 出口 IP 池，按 account_id 取模分配
  "http://127.0.0.1:7891",
  "http://127.0.0.1:7892",
  "socks5://127.0.0.1:7893",
]

sign_delay_min = 3.0             # 发现签到后最少等 3 秒
sign_delay_max = 25.0            # 最多等 25 秒
multi_account_spread = 4.0       # 同活动多账号时，相邻账号再错开 4 秒
```

实测（4 账号 / 4 代理）：

```
13800000001  device=b2638445…  proxy=:7892  ua=SM-S9110
13800000002  device=3cb7ffe7…  proxy=:7893  ua=Redmi K50
13800000003  device=d76e30a3…  proxy=:7894  ua=OPPO Find X6
13800000004  device=ce5aa676…  proxy=:7891  ua=Pixel 7a
```

### 身份必须**稳定**，不能每次随机

这条最容易搞反。一个学号一天换三个设备，比"一直用同一台手机"可疑得多。
所以所有身份字段都是 `sha256(account_id + username)` 派生，首次生成后立刻
`store.save_identity()` 落库，之后只读不重算。

**要变的是行为**（延迟、坐标、请求间隔），**不是身份**。

### 池子不够大怎么办

`len(proxy_pool) < 账号数` 时必然共享出口。这是物理限制，只有两条路：

1. 加代理（住宅代理最像真人，机房 IP 段容易被风控标记）
2. 接受同出口，靠**时间抖动 + 不同 deviceCode + 不同 UA** 降低关联强度

不要把 `poll_interval` 压到 5 秒来"抢速度" —— 秒级聚集本身就是最强的关联信号。

---

## 三、审计

每次签到已经写进 `sign_logs`（`account_id` / `active_id` / `kind` / `ok` / `message` / `created_at`）。
补一条 `delegation_id` 外键就能回答"这次是谁授权签的"：

```sql
ALTER TABLE sign_logs ADD COLUMN delegation_id INTEGER NOT NULL DEFAULT 0;
```

查询示例：

```sql
-- 某个账号最近 30 天的签到记录，带授权来源
SELECT l.created_at, l.kind, l.ok, l.message, d.operator
FROM sign_logs l LEFT JOIN delegations d ON d.id = l.delegation_id
WHERE l.account_id = 7 AND l.created_at > strftime('%s','now') - 30*86400
ORDER BY l.id DESC;
```

---

## 四、还没做的

| 项 | 原因 |
|---|---|
| 授权页（C 档一次性 grant token） | 需要 UI 与回调，`v0.3` |
| 动态住宅代理池 | 现在只支持静态 `proxy_pool`，轮换要接供应商 API |
| 每账号独立 `poll_interval` | 错峰更彻底，但要重写调度器 |
| 代签配额/限速 | 防止一个 operator 拖 200 个账号把出口打爆 |

（v0.2 已完成：密码 Fernet 加密、`sign_logs.delegation_id`、全局令牌桶、账号级指数退避。）

---

## 五、一句话

代签不是一个功能，是一个**隔离问题**。
签到代码一行不用改，但如果没有 `deviceCode` / UA / 出口 IP / 时间抖动这四层隔离，
你做的不是"代签工具"，是"批量暴露名单工具"。
