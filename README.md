# 主动回复（随机版）

不是固定时间点，而是两种「像真人」的主动方式：

1. **随机主动（突然想你了）**：每隔一段时间抽一次签，随机决定是否突然想你了、主动找你聊天/分享/撒娇。
2. **群聊触发（群里有人找我）**：群里有人 @机器人、用唤醒词叫它、或提到它名字时，主动把这事分享给你。

## 原理

- 随机主动：注册一个 basic job 定时「抽签」，抽中后再注册一个 run_once 的 active_agent 任务唤醒主 agent。
- 群聊触发：事件 handler 监听群消息，命中条件后唤醒主 agent。
- 主 agent 按人格和记忆生成内容，用 `send_message_to_user` 工具发给你，不是死模板。

## 配置项（WebUI 插件配置里改）

| 配置 | 默认 | 说明 |
| --- | --- | --- |
| random_enabled | true | 随机主动开关 |
| random_interval_min_minutes | 30 | 抽签间隔下限（分钟） |
| random_interval_max_minutes | 60 | 抽签间隔上限（分钟） |
| random_probability | 0.35 | 每次抽签触发概率（0~1） |
| activity_cooldown_minutes | 10 | 互动冷却（分钟），你最近这么久内发过消息/收到过回复就跳过本次主动 |
| random_note | 见默认值 | 随机主动的唤醒指令 |
| quiet_enabled | true | 睡觉免打扰开关 |
| quiet_start | 02:00 | 免打扰开始时间 |
| quiet_end | 09:00 | 免打扰结束时间 |
| group_enabled | true | 群聊触发开关 |
| group_ids | [] | 监听群号，空=所有群 |
| group_cooldown_seconds | 300 | 同群触发冷却（秒） |
| wake_names | [] | 触发名字（改成机器人的昵称） |
| group_note | 见默认值 | 群聊触发的唤醒指令，支持 {group_id}/{sender_name}/{message} |
| target_session | default:FriendMessage:371221260 | 目标会话 |
| sender_id | 371221260 | 接收人 QQ |

## 用法

1. 安装后重启/重载插件。
2. WebUI 插件配置里按需调概率、间隔、冷却。
3. 随机主动和群聊触发各自独立开关。

## 注意

- 插件重载时会自动清理同名旧任务，避免重复注册。
- 禁用插件会删除已注册的抽签任务。
- 随机主动的触发是概率性的，不是精确时间，所以会有「突然想你」的感觉。
