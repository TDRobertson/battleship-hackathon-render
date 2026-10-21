# Remote LAN Matches

The remote runner lets competitors run bots on their own machines while a host
machine runs the match server. It is designed for trusted LAN use during a
hackathon. It is not an internet-hardened service.

## 1. Host The Server

On the host machine:

```console
battleship remote-server --host 0.0.0.0 --port 8765
```

Share the host machine's LAN address with competitors, for example
`http://192.168.1.20:8765`.

## 2. Connect A Bot

Each competitor runs a client process from their own checkout:

```console
battleship remote-client --server http://192.168.1.20:8765 --name alice --bot my_bot:MyAgent
```

Built-in bots work too:

```console
battleship remote-client --server http://192.168.1.20:8765 --name demo --bot hunt-target
```

The client keeps running and waits for match actions from the server. Stop it
with `Ctrl+C`.

## 3. List Connected Bots

On any machine that can reach the host:

```console
battleship remote-list --server http://192.168.1.20:8765
```

If two clients use the same display name, run matches by `id` instead of name.

## 4. Run A Remote Match

```console
battleship remote-match --server http://192.168.1.20:8765 --bot-a alice --bot-b bob --games 5 --seed 2026 --verbose
```

Write results to CSV:

```console
battleship remote-match --server http://192.168.1.20:8765 --bot-a alice --bot-b bob --games 20 --csv remote-results.csv
```

`remote-match` uses the same rules engine as local matches. Illegal placements,
illegal shots, crashes, and timeouts still forfeit.

## How It Works

- The server exposes a small HTTP API.
- Bot clients register with a display name and then long-poll for tasks.
- The server sends `place_ships` and `choose_shot` tasks to clients.
- Clients run their local `Agent` implementation and send the action back.
- The authoritative engine stays on the server.

Because clients connect outward to the host, competitors usually do not need to
open inbound firewall ports on their laptops.

## LAN Safety Notes

Use this on a trusted LAN only. The server intentionally keeps setup simple and
does not provide user accounts, TLS, rate limiting, or sandboxing for hostile
network traffic.
