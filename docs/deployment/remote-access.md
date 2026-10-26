# 可选远程访问入口

本文件从保存基线 `7973de6` 的部署资料提取，适用于 `deploy/tensortrain2`。主线运行接口见[运行说明](../operations/meta-harness.md)。本次拆分未连接服务器、切换服务或转换活动数据。

### 使用 Tailscale 从手机访问

电脑和手机连接同一 Tailscale 网络后，可用 Tailscale Serve 将 HTTPS 入口代理到工作台的 `127.0.0.1:18401`。UI 和控制后台仍绑定回环地址，不开放控制端口。远程入口的访问范围由 Tailscale 网络策略决定；浏览器还必须完成 dsh 宿主认证。工作台的 `/phyexp/api` 接口复用宿主的会话和可信域名校验，不能只凭同源请求操作后台。

将以下配置保存为 UI 宿主目录下的 `workbench-access.json`（默认位于数据目录的 `ui/`），替换为电脑实际的 Tailscale DNS 名称：

```json
{"publicUrl":"https://your-computer.your-tailnet.ts.net:18443/"}
```

重新启动 UI：`node scripts/workbench.mjs`。启动器只信任配置中的准确域名与端口；也可用 `PHYEXP_UI_PUBLIC_URL` 覆盖文件配置，空字符串表示禁用远程域名配置。只接受无路径、查询参数、凭据和 fragment 的 HTTPS 根地址。只重启 UI 不停止控制后台或实验。

随后添加独立入口（先检查该端口没有其他 Serve 服务）：

```sh
tailscale serve --bg --https=18443 http://127.0.0.1:18401
```

手机首次打开启动终端打印的完整 HTTPS 登录链接（带 `token`），宿主会写入浏览器会话并跳转到不带令牌的地址；以后收藏干净地址即可。该链接授予此 UI 宿主的访问权，只通过可信渠道传给自己的设备，不写入仓库或公开文档。宿主重启后生成新的启动令牌，已有有效浏览器会话由同一 UI 数据目录保留。默认首屏从侧栏选择「研究工作台」（Studio）。

手机使用完整浏览器打开 HTTPS 启动链接。若聊天应用把链接转成「文件预览」，长按复制链接后粘贴到 Chrome 等浏览器的地址栏；文件预览的抓取器可能不保留登录跳转的会话 Cookie，从而得到 401 或抓取异常。`127.0.0.1` 仅用于工作台所在电脑，不能作为手机浏览器的访问地址。

使用 Serve 的私有网络模式，不启用 Funnel。电脑需保持联网、唤醒且 UI 与后台进程运行；本配置不负责开机自启。关闭此入口用 `tailscale serve --https=18443 off`，不使用会清除其他转发的 `reset`。远程入口撤销后可删除配置文件中的 `publicUrl` 并重启 UI。

若 HTTPS 直连成功而浏览器显示连接被关闭，检查系统或浏览器代理是否接管了 Tailscale 域名。将工作台的准确域名加入代理绕过列表并保留原有条目，让该地址走 Tailscale；不要关闭浏览器认证或证书校验。手机也需保持 Tailscale 已连接。
