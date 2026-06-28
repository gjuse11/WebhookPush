# WebhookPush - 群消息 Webhook 推送

外部系统按以下格式配置即可向相关群组推送消息。

## 填写模板（对照配置界面）

| 配置项 | 填写内容 |
|--------|----------|
| **请求方法** | `POST`（也支持 `GET`） |
| **接口地址** | `http://127.0.0.1/api/webhook/<token>` |
| **请求头 [header]** | 见下方 JSON |
| **请求体 [body]** | 见下方 JSON（POST 时） |

### 请求体示例（POST）

**方式 A：api_key 放在请求头（推荐）**

请求头：
```json
{
  "api_key": "",
  "Content-Type": "application/json"
}
```

请求体：
```json
{
  "content": "CI 构建成功",
  "from": "GitHub Actions"
}
```

**方式 B：api_key 放在请求体（CUSTOM_HTTP 等平台常用）**

请求头：
```json
{
  "Content-Type": "application/json"
}
```

请求体：
```json
{
  "api_key": "",
  "content": "{{CONTENT}}",
  "from": "{{FROM}}"
}
```

如果发送方字段名只能写 `api`，也可以这样：

```json
{
  "api": "",
  "content": "{{CONTENT}}",
  "from": "{{FROM}}"
}
```
- **content**：消息正文（必填）
- **from**：来源标识（选填），会显示为 `[来源] 消息正文`

## 插件配置

编辑 `config.toml`：

```toml
[WebhookPush]
enable = true

[[webhooks]]
name = "开发群"
token = ""
group_wxid = ""
api_key = ""
```

- **token**：接口地址 URL 最后一段
- **api_key**：鉴权密钥（留空则不校验）。发送方可用 `api_key`，也可用 `api`
- **group_wxid**：群 ID，管理后台「联系人 → 群列表」获取

## 调用示例

**POST：**

```bash
curl -X POST "http://127.0.0.1/api/webhook/dev-group-secret-token-change-me" \
  -H "Content-Type: application/json" \
  -H "api_key: " \
  -d "{\"content\":\"CI 构建成功\",\"from\":\"Jenkins\"}"
```

**GET：**

```bash
curl -G "http://127.0.0.1/api/webhook/alert-group-secret-token-change-me" \
  --data-urlencode "content=磁盘告警" \
  --data-urlencode "from=监控系统"
```

成功响应：

```json
{ "code": 0, "msg": "success" }
```

## 错误码

| code  | 说明 |
|-------|------|
| 0     | 成功 |
| 19001 | token 无效 |
| 19002 | 机器人未就绪 |
| 19004 | 请求过于频繁 |
| 19005 | 插件已禁用 |
| 19006 | JSON 格式错误 |
| 19007 | content 为空 |
| 19008 | 发送失败 |
| 19009 | 缺少 api_key |
| 19010 | api_key 无效 |
| 19012 | 不支持该请求方法 |

## 常见问题

**Q：一直返回 `19009 api_key required`，但我明明填了 api_key？**

最常见原因是前置了 Nginx 反向代理（用域名访问时）。Nginx 默认会丢弃 header 名里带下划线 `_` 的请求头，导致 `api_key` 这个头被丢掉。解决办法任选其一：

1. header 名改用中划线 `api-key`（推荐）
2. 把密钥放进请求体：`{"api_key": "...", "content": "..."}`
3. 把密钥放进 URL：`...?api_key=你的密钥`

判断技巧：失败响应里的 `debug.header_keys` 如果出现 `x-real-ip`、`x-forwarded-for`，说明走了反向代理，基本就是这个原因。

**Q：header 里填 `{{API_KEY}}` 报错或鉴权失败？**

`{{API_KEY}}` 是推送平台的变量占位符，必须在平台里给它赋真实值，否则会是空或被替换成消息内容。最简单是直接写死真实密钥，不用变量。

## 注意事项

- 修改配置后需重载插件或重启 AllBot
- 鉴权字段名兼容：`api-key` / `api_key` / `apikey` / `x-api-key` / `api`（header、body、URL 均可）
