---
name: 协议变更 / 接口失效
about: 学习通改版，某个接口参数变了或路径没了
title: "[协议] "
labels: protocol
---

## 哪个接口

<!-- 从 cxsign/endpoints.py 里挑，例如 ACTIVE_LIST / STU_SIGN_AJAX / PRE_SIGN -->

## 现在发生了什么

<!-- 302？空 data？返回了新的错误文案？附上原始响应 -->

```
原始响应（脱敏后的前 200 字符）
```

## 你怎么发现的

- [ ] `python -m cxsign.tools probe` 显示某条不再可用
- [ ] 签到返回了没见过的文案
- [ ] 抓包对比发现参数变了
- [ ] 其它：

## 建议的修法

<!-- 有就写，没有也行 -->

## 参考

<!-- 相关 issue / 别的项目怎么处理的 / 抓包截图 -->
