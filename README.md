
```bash
python iot_secure_tunnel.py my-thing-name \
    --user ubuntu \
    --profile my-aws-profile \
    --region us-west-2 \
    --port 6666 \
    --dest-client-type V2
```
| Flag | Default | Description |
|------|---------|-------------|
| `--user` | `root` | SSH username on the device |
| `--profile` | `default` | AWS CLI profile |
| `--region` | `eu-central-1` | AWS region |
| `--port` | `5555` | Local proxy listen port |
| `--dest-client-type` | `V1` | `V1` for Greengrass/Device Client, `V2` for local proxy v2 |
## How it works
```
┌──────────────┐       ┌──────────────────────┐       ┌──────────────┐
│  Your laptop │──443──│  AWS IoT Secure       │──443──│  IoT Device  │
│              │       │  Tunneling Service    │       │              │
│  local proxy │       │  (WebSocket broker)   │       │  dest proxy  │
│  ↕ SSH       │       └──────────────────────┘       │  ↕ sshd      │
│  localhost:  │                                       │  localhost:22│
│  5555        │                                       │              │
└──────────────┘                                       └──────────────┘
```
Both sides connect **outbound on port 443** — no inbound firewall rules needed on either end. The tunnel is brokered by AWS over TLS-encrypted WebSocket connections.
## Required AWS Permissions
The IAM identity behind your AWS profile needs:
```json
{
    "Effect": "Allow",
    "Action": [
        "iot:OpenTunnel",
        "iot:DescribeTunnel",
        "iot:CloseTunnel",
        "iot:ListTunnels",
        "iot:ListThings"
    ],
    "Resource": "*"
}
```
## Troubleshooting
| Symptom | Cause | Fix |
|---------|-------|-----|
| `destination: DISCONNECTED` after all retries | Device's tunneling agent isn't running | Check Greengrass component status on the device |
| `SSL handshake: certificate verify failed` | Missing CA bundle | Download [cacert.pem](https://curl.se/ca/cacert.pem) into `localproxy/` |
| `Connection refused` on SSH | Proxy not binding to 127.0.0.1 | Already handled by the script's `-b 127.0.0.1` flag |
| `Pseudo-terminal will not be allocated` | Running from a non-interactive shell | Run from a real terminal (CMD, PowerShell, or a terminal emulator) |
## License
MIT
