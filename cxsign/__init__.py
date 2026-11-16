"""cxsign —— 超星学习通自动签到（协议复现版）。

模块分层（自下而上）：

    crypto    密码/参数加密
    net       HTTP 会话、限速、重试、登录态识别
    auth      登录、登录态校验、取真实姓名
    course    课程列表（courseId / classId）
    activity  活动列表、活动详情、签到类型判定
    presign   签到前的 preSign + analysis 反作弊上报链
    signer    按类型分发，落到 pptSign/stuSignajax
    monitor   轮询监听 + 去重 + 回调
    notify    推送通道
    store     SQLite 持久化
    server    FastAPI + Web UI
    cli       命令行入口
"""

__version__ = "0.2.1"
