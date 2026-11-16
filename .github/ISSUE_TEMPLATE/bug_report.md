---
name: Bug 报告
about: 签到不成功、接口报错、程序崩溃
title: "[Bug] "
labels: bug
---

## 现象

<!-- 一句话说清楚：什么场景、期望什么、实际什么 -->

## 复现步骤

1.
2.
3.

## 环境

| 项 | 值 |
|---|---|
| 系统 | <!-- Windows 11 / Ubuntu 24.04 / ... --> |
| Python | <!-- python -V --> |
| 部署方式 | <!-- docker / pip install -e / 直接跑 --> |
| 版本 | <!-- cxsign --help 顶部或 git rev-parse HEAD --> |

## 日志

<!-- 用 `python -m cxsign.tools diag` 的输出最有帮助 -->

```
粘贴 data/logs/cxsign.log 相关片段
```

## 自检清单

- [ ] 已跑 `python -m cxsign.tools diag`，确认 cookie 里有 `_uid` / `fid` / `vc3`
- [ ] 已跑 `python -m cxsign.tools probe`，确认接口路径还活着
- [ ] 已确认不是"当前没有签到活动"
- [ ] 日志已脱敏（**不要贴真实 cookie、密码、姓名、手机号**）

## 签到类型

<!-- 普通 / 手势 / 位置 / 拍照 / 签到码 / 二维码 / 群聊 -->
