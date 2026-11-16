# 路线图

## v0.1 — 可用

- [x] 手机号密码登录（AES 主用 / DES 兼容），Cookie 持久化
- [x] 登录态校验 + 自动重登
- [x] 课程列表、活动列表、活动详情
- [x] 类型判定（`otherId` + `ifphoto` + `activeSort`）
- [x] 反作弊上报链 `preSign → analysis → analysis2`
- [x] 六种签到：普通 / 手势 / 位置 / 拍照 / 签到码 / 二维码
- [x] 位置签到 BD-09 + 随机抖动 + 距离解析
- [x] 拍照签到云盘上传 / 复用 `0.jpg`
- [x] 轮询监听 + 内存 & DB 双层去重
- [x] 推送：Server酱 / PushPlus / Telegram / Webhook
- [x] FastAPI + 单页 Web UI
- [x] CLI、Docker

## v0.2 — 工程健壮性（已完成）

- [x] **身份隔离层**：一账号一份 `deviceCode` + UA + 出口 IP（见 [delegation.md](delegation.md)）
- [x] **行为抖动**：`sign_delay_min/max` + `multi_account_spread`
- [x] **凭据加密**：`security.py`，Fernet 静态加密 + 主密钥三级回退（env / 文件 / 报错）
- [x] **全局令牌桶**：`ratelimit.py`，跨账号共享总出口速率
- [x] **并发扫描**：多课程 `ThreadPoolExecutor`，受令牌桶约束
- [x] **指数退避**：`TooFrequent` → 30s → 60s → 120s … 上限 600s，账号级隔离
- [x] **Cookie 托管（代签 B 档）**：`engine.import_cookies()`，不保存密码
- [x] **审计闭环**：`delegations` 表 + `sign_logs.delegation_id` + `logs_with_operator()`
- [x] **二维码图片解码**：`qrdecode.py`，可选 `opencv-python-headless`，Web UI 直接传截图
- [x] **日志轮转**：`log.py`，5MB × 5 份
- [x] **老库自动升级**：明文密码就地加密、缺列自动补
- [x] **端到端回放测试**：`tests/conftest.py` 起一个可编程的假学习通，26 条用例真发 HTTP，
      覆盖六种签到的参数拼装 + 回执解析 + 上报链 + 未登录识别
- [x] **SSL 上下文共享**：`httpx.Client()` 在 Windows 上每次初始化 1.04s，
      共享上下文后 0.03s；全量测试 100s → 6.8s
- [x] 166 条单测

## v0.2.1 — 真实环境验证（进行中）

- [x] 密码登录 → 拿到 `vc3` 等 12 项 cookie
- [x] 姓名解析修正（`messageName` 已不存在）
- [x] 课程列表按块解析（全局正则会串课）
- [x] 20 门课扫描，无活动时返回空列表
- [ ] **真实签到**：等第一个活动出现，六种类型逐个验证
- [ ] `enc` 真实 TTL 打点（`enc_ttl` 目前保守取 120s）

## v0.3 — 体验与开源门面

- [ ] **tools 收敛**：14 个脚本里一半是一次性调试产物，合并成 `cxsign tools <sub>`
- [ ] **Web UI 拆分**：单文件 HTML 已 286 行，换 Vue/React
- [ ] README 加截图 / 演示 GIF（现在纯文字，开源门面太弱）
- [ ] CI（GitHub Actions）：`pytest` + `ruff`，有回放测试后完全可行
- [ ] 发布首个 release + Docker Hub 镜像
- [ ] CONTRIBUTING / issue 模板 / PR 模板
- [ ] 授权页：一次性 grant token（代签 C 档），带过期与撤销
- [ ] 课程 → 活动的时间线视图
- [ ] 规则引擎：按课程/类型/时间段配置"只签某几门""晚上不签"
- [ ] 推送模板自定义

## v0.4 — 精度提升

- [ ] 群聊签到接入 monitor（现在 `chat.py` 只有库，没有监听入口）
- [ ] 位置自动校正：拿到「距离 N 米」后按方位试探 2~3 次逼近
- [ ] 动态住宅代理池（接供应商 API，按账号轮换）
- [ ] 每账号独立 `poll_interval`，错峰更彻底
- [ ] 代签配额：一个 operator 最多托管 N 个账号
- [ ] Prometheus 指标导出

## 明确不做

| 能力 | 原因 |
|---|---|
| 伪造签到活动 | 从"完成签到"变成"制造签到"，性质不同 |
| 人脸签到绕过 / 活体伪造 | 同上，且需伪造身份 |
| 滑块验证码自动过（打码平台） | 外部依赖 + 持续对抗，收益不匹配；本项目的问卷式方案是**手动过一次** |
| 刷视频时长 / 刷章节 | 与项目定位无关 |
| 作业答案/题库 | 同上 |

> 代签**不在**这个列表里 —— 它是"多账号 + 授权模型 + 身份隔离"的工程问题，
> v0.2 已落地 B 档（Cookie 托管），设计方案见 [delegation.md](delegation.md)。

## 想贡献？优先级从高到低

1. 接口变更修复（学习通改版后 `activelist` / `signajax` 参数变化）
2. 授权页（C 档一次性 token）
3. 新的推送通道（Bark、Gotify、企业微信机器人）
4. i18n（英文 README）
5. 文档里的错误纠正（尤其是坐标系和类型判定）

提交 PR 前请：

```bash
python -m pytest tests -q      # 必须全绿（当前 82 条）
python -m cxsign --help        # CLI 不报错
```
