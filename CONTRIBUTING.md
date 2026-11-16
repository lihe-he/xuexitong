# 贡献指南

## 最短路径

```bash
git clone <repo> && cd cxsign
pip install -e ".[dev,qr]"
pytest tests -q          # 必须全绿
ruff check .             # 必须干净
```

不需要学习通账号 —— 端到端测试用的是**本地假服务端**（`tests/conftest.py`）。

## 提交前

1. `pytest tests -q` 全绿
2. `ruff check .` 无告警
3. 涉及协议变更的，同步更新 `docs/protocol.md`
4. 涉及新接口的，在 `cxsign/endpoints.py` 里标注可信度（`[稳]/[验]/[推]/[✗]`）

## 最有价值的贡献

按优先级：

| 优先级 | 类型 | 说明 |
|---|---|---|
| ⭐⭐⭐ | **接口变更修复** | 学习通改版后 `activelist` / `signajax` 参数变了，这是最高频的 issue |
| ⭐⭐⭐ | **真实环境验证记录** | 跑通某个签到类型后，把实测报文补进 `tests/test_live_payloads.py` |
| ⭐⭐ | 新的推送通道 | Bark、Gotify、企业微信机器人，写一个函数注册进 `notify.CHANNELS` |
| ⭐⭐ | 群聊签到接入 monitor | `chat.py` 目前只有库，没接监听 |
| ⭐ | i18n | 英文 README |
| ⭐ | 文档纠错 | 尤其是坐标系和类型判定 |

## 代码约定

* **协议层与业务层严格分离**：URL 只在 `endpoints.py`，不要在业务代码里硬编码
* **异常语义要准**：`AuthExpired` = 该重登了，`TooFrequent` = 该退避了，`ApiError` = 真的坏了
* **纯函数优先**：能写成纯函数的（如 `classify`、`parse_reply`）就别碰网络，方便单测
* **注释写"为什么"**，不写"是什么" —— 代码已经说了是什么

## 加一个签到类型

1. `activity.py` 加 `SignKind` 成员 + 判定规则
2. `signer/` 下加模块，实现 `sign_xxx(session, activity, opts)`
3. `signer/__init__.py` 的分发器加一个 case
4. `tests/test_e2e_sign.py` 加一条用例（假服务端会记账）
5. `docs/protocol.md` 补参数表

## 跑真实环境验证

```bash
python -m cxsign.tools live --user <手机号> --password <密码>
python -m cxsign.tools diag        # 哪个域不通、缺哪个 cookie
python -m cxsign.tools probe       # 接口还活着吗
```

**不要把真实账号密码、cookie、抓到的页面 HTML 提交进仓库。**

## 不做什么

见 [docs/roadmap.md](docs/roadmap.md#明确不做)：伪造签到活动、人脸绕过、打码平台。
提这类 PR 会被关掉 —— 不是道德问题，是它们会让项目背上持续对抗风控的成本。
