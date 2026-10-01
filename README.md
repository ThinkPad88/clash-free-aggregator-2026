# Clash Free Aggregator 2026 — OpenClash / Mihomo

这是一个运行在 **GitHub Actions** 上的免费 Clash 节点聚合器。你的 OpenWrt/OpenClash **不运行 Python 聚合器**，只需要订阅本项目生成的固定 URL。

## 架构

```text
Public sources
   ├─ Au1rxx
   ├─ Zhuhai
   ├─ Pawdroid
   └─ steam-100
          │
          ▼
   GitHub Actions（每小时）
          │
          ├─ 下载
          ├─ Clash YAML / Base64 解析
          ├─ URI 解析
          ├─ 去重
          ├─ 协议过滤
          └─ 生成 Mihomo/OpenClash YAML
          │
          ▼
   dist/openclash.yaml
          │
          ▼
   OpenClash / Mihomo
          │
          ├─ Auto url-test
          ├─ YouTube
          ├─ Google
          └─ 地区 Auto
```

## 固定订阅 URL

上传到自己的 GitHub 后，固定 URL 为：

```text
https://raw.githubusercontent.com/<你的用户名>/clash-free-aggregator-2026/main/dist/openclash.yaml
```

也可以使用：

```text
https://raw.githubusercontent.com/<你的用户名>/clash-free-aggregator-2026/main/dist/clash.yaml
```

两个文件内容相同。

## OpenClash 使用

OpenClash → 配置文件 → 添加订阅 → 输入上面的固定 URL。

建议 OpenClash 自己设置订阅更新时间，例如每 1～6 小时；GitHub Actions 默认每小时生成一次。

### 重要：谁负责测速？

GitHub Actions 负责维护“节点池”；**OpenClash/Mihomo 负责本地实时测速和选节点**。这样比在 GitHub Actions 中强制连接所有 VLESS/Reality/Hysteria2 节点更可靠。

生成配置包含：

* `Auto`
* `Hong Kong Auto`
* `Taiwan Auto`
* `Japan Auto`
* `Singapore Auto`
* `United States Auto`
* `Netherlands Auto`
* `France Auto`
* `Germany Auto`
* `United Kingdom Auto`
* `South Korea Auto`
* `Canada Auto`
* `Australia Auto`
* `YouTube`
* `Google`
* `Proxy`
* `Final`

YouTube 规则覆盖 YouTube、YouTube CDN、Google Video 等；Google 规则覆盖 Google、Google APIs、gstatic、Googleusercontent。

## 安全回滚

这是本版本最重要的保护：

如果某次更新出现：

* 所有上游不可访问
* 所有节点解析失败
* 节点数量为 0
* 节点全部不符合协议/格式要求

程序**不会覆盖旧的 `dist/clash.yaml`**，而是保留上一版有效订阅，并在 `dist/status.json` 中标记 `publication: kept\_previous`。

## GitHub 上传

1. 解压 ZIP。
2. 用 GitHub Desktop 添加本地项目。
3. 创建名为 `clash-free-aggregator-2026` 的 Public Repository。
4. Publish repository。
5. 打开 GitHub → Actions → `Build OpenClash Subscription`。
6. 第一次点击 `Run workflow` 手动运行。
7. 检查 `dist/openclash.yaml` 和 `dist/status.json`。

## 本地测试

```bash
python -m pip install -r requirements.txt
python src/aggregator.py
```

## 注意

免费代理来自公开第三方来源。不要使用免费节点处理银行、支付、公司机密或重要账号密码。节点可能随时失效；固定的是**订阅 URL**，不是某一个节点的永久可用性。

