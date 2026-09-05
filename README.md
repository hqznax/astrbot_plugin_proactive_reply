# 主动回复（随机版）

让 AI 伴侣「像真人」一样主动找你，不是固定时间点，而是两种主动方式：

1. **随机主动（突然想你了）**：在 30-60 分钟（可配置）随机一个时间抽签，随机决定是否突然想念主人、主动找他聊天/分享/撒娇。
2. **群聊触发（群里有人找我）**：群里有人 @机器人、用唤醒词叫她、或提到她名字时，主动把这事分享给主人。

## 原理

- 随机主动：注册一个 basic job，每次到点「抽签」，抽中后再注册一个 run_once 的 active_agent 任务唤醒主 agent。
- 群聊触发：事件 handler 监听群消息，命中条件后唤醒主 agent。
- 主 agent 按人格和记忆生成内容，用 `send_message_to_user` 工具发给主人，不是死模板。

## 配置项（WebUI 插件配置里改）

| 配置 | 默认 | 说明 |
| --- | --- | --- |
| random_enabled | true | 随机主动开关 |
| random_interval_min_minutes | 30 | 随机主动最短间隔（分钟） |
| random_interval_max_minutes | 60 | 随机主动最长间隔（分钟） |
| random_probability | 0.35 | 每次到点触发概率（0~1，调 1 则每次到点都发） |
| random_note | 见默认值 | 随机主动的唤醒指令 |
| quiet_enabled | true | 睡觉免打扰开关 |
| quiet_start / quiet_end | 02:00 / 09:00 | 免打扰时段 |
| group_enabled | true | 群聊触发开关 |
| group_ids | [] | 监听群号，空=所有群 |
| group_cooldown_seconds | 300 | 同群触发冷却（秒） |
| wake_names | [] | 触发名字，填你自己的名字/昵称 |
| group_note | 见默认值 | 群聊触发的唤醒指令，支持 {group_id}/{sender_name}/{message} |
| target_session | （空） | 目标会话，格式 platform_id:message_type:session_id |
| sender_id | （空） | 接收人 QQ 号 |

## 用法

1. 安装后先在插件配置里填好 `target_session` 和 `sender_id`（要接收主动消息的会话和 QQ 号）。
2. 按需调概率、间隔、免打扰时段、唤醒名字。
3. 重启/重载插件生效。

## 注意

- 插件重载时会自动清理同名旧任务，避免重复注册。
- 禁用插件会删除已注册的抽签任务。
- 随机主动的触发是概率性的，不是精确时间，所以会有「突然想你」的感觉。
