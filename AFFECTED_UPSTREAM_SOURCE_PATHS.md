# Task A event identity and delivery source inventory

All paths in the table are **installed, read-only source** relative to
`/home/alfred/.hermes/hermes-agent/`. The SHA-256 values pin the files inspected
on 2026-10-14. This document proposes work only; no upstream files were
changed and no patch or release was built during this investigation.

| Path and relevant lines | SHA-256 | Needed interface change or reason for review |
| --- | --- | --- |
| `plugins/platforms/photon/sidecar/index.mjs:642-659,693-720` | `bf9cae8ff7bdd1c9e00cbcb0a4a3b56f4f9c10bfd0ab14f20a71055a4f049284` | Preserve SDK event sequence and authenticated immutable identity; durably journal before read receipt; reconcile on restart; keep one authenticated Photon owner. |
| `plugins/platforms/photon/adapter.py:787-858,921,1461-1539` | `5c5a22ba2a6227514f0b6268d82cb1f6903cd76315d8a0e3d2376ced48c3999e` | Admit immutable event-bound job; pass typed result identity through all send paths; deny handle, recipient or destination supplied by model/tool. |
| `gateway/platforms/event.py:45-68` | `7254e858a8a3dc398e769923df9ddaae2952e2e812304586e3753261bcc44f52` | Add typed protected event/job identity; mutable raw event cannot be attestation. |
| `gateway/platforms/base.py:1803-1849,3602-3617,4038-4188,4562-4637` | `1da156ce1d619b3f4481a8216364d242d689c34005892b7ab985e5616b7959be` | Prevent protected jobs from merging or replacement; retain each event's identity through inline, background and final delivery; send result under its own turn. |
| `gateway/run_adapters.py` | `f4079eb3be2063cab5699583f68e62fdf3460c88b4092f8e5a11a8f7b6857ff7` | Inspect queue/adapter bridge and propagate typed job envelope through runner interfaces. |
| `gateway/run_busy.py:375-425` | `7596d35132931179a1061efb86c7219b25f4325cd69d35a0259164d981795fba` | Preserve every protected event as a separate bounded FIFO item; explicit full/cancel/refusal state. |
| `gateway/run_inbound.py:693-745,1285-1368` | `6a1a40708075e3550a824eae5519e98db97f52ea7995154e8c7e941de4e02144` | Bind admission, busy policy and agent run to the same job; no protected event steering or absorption. |
| `gateway/run_turn.py:2144-2198,3811-3945,4265-4359` | `2db13843bdda12767405e705eb946a0b3c69c5f06aaf8977b7ca43dba294ad07` | In-band recursive follow-up must change identity to pending event and return an identity-bearing result; carry identity through tools and cancellation. |
| `gateway/turn_context.py:14-57` | `0ead1dd84316f79eb3809d60941577b7cf0c82f120e9c9a49fe946f59f6a6f10` | Add typed immutable job/event identity, generation and company scope; context alone remains untrusted at protected boundary. |
| `tools/send_message_tool.py:35-42,267-277,524-558,689-760` | `26079c7fc5e62af2e6ecfa0daaebef1bb16497cdb96d064840fa31c530d98f2d` | Disable independent Photon sends for Task A or require trusted job/result attestation; reject model-selected destinations. |
| `plugins/platforms/photon/sidecar/node_modules/@spectrum-ts/core/dist/authoring.js:199,223-231,272-275,393-398` | `f96d907578eb44bb74b51203f4b3f2bb70d44364f5cef819b05b9899a9be6852` | Installed high-level cursor is volatile, advances on emission and accepts a rejected-cursor gap; cannot be the durable cursor. Do not edit installed package in place. |
| `plugins/platforms/photon/sidecar/node_modules/@spectrum-ts/imessage/dist/index.js:2333-2347,2417-2462` | `2f7e13c432ad4e84f96b76eb3d59062d70d3d7e46737a7e15198a47ecda6ef24` | High-level catch-up requires cursor; exposes only selected message values. A supported lower-level adapter or upstream SDK API change must surface complete event sequence and resume contract. |
| `plugins/platforms/photon/sidecar/node_modules/@photon-ai/advanced-imessage/dist/grpc.d.ts:103-112,183-192,291-298` | `fa27c25cf23e2c9995958b305a8669c83db5dae115b8085648fae56022940f89` | Declares durable event-log catch-up and history APIs; verify deployment retention and completeness before using for recovery. |
| `plugins/platforms/photon/sidecar/node_modules/@photon-ai/advanced-imessage/dist/client-NRHONKWO.js:514-568,1220-1250` | `0646f845866318df814396d98998954f15bc1ea0925ae7e6244fe5434bb94206` | Implements catch-up from retained log and paged recent history; client implementation alone cannot prove server retention. |
| `plugins/platforms/photon/sidecar/node_modules/@photon-ai/advanced-imessage/dist/groups-CMgks3Ll.d.ts:548-572` | `2a07e49a8470c954adca2529475c67e7b748c650f3d829a75660d950792da8cd` | Defines history filter and pagination types; no completeness or retention guarantee. |

Any new upstream patch should be generated inside this Task A staging
workspace, pinned to these inputs, and independently reviewed before any
installation. The trusted coordinator/worker and Photon replay design are
architectural prerequisites; editing only `adapter.py` or carrying a handle
through `ContextVar` cannot meet the existing trust boundary.
