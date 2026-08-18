"""EFS がマウントできる状態か確認する.

ファイルシステム自体と、各サブネットのマウントターゲットの両方を見る。
ファイルシステムが available でも、対象サブネットのマウントターゲットが
available でなければ、そのサブネットからはマウントできない。

既にマウント済みの Pod は NFS マウントを保持し続けるため、マウント
ターゲットが error でも動き続ける。eks の check は ready == want で正常と
判定するが、切替後に Pod が再起動するとそこで初めてマウントに失敗する。
Lambda の Inactive と同じく「必要になるまで気づけない」ため独立して確認する。

アクセスポイントは確認しない。EFS CSI ドライバの動的プロビジョニングでは
PVC の増減に応じてアクセスポイントが作られるため、使われていないものを
拾って誤検知しうる。

必要な IAM:
    elasticfilesystem:DescribeFileSystems
    elasticfilesystem:DescribeMountTargets

ハンドラ（成功時は何も返さない。失敗・未収束は例外で表現する）:
    check   入力 {"dry_run": bool}
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from dr_switch.core import NotRecoverableError, client, lambda_handler
from dr_switch.efs.config import EfsConfig

if TYPE_CHECKING:
    from mypy_boto3_efs.literals import LifeCycleStateType

# LifeCycleState はファイルシステム・マウントターゲット・アクセスポイントで
# 共通の enum。available 以外は、creating / updating なら待てば変わる。
HEALTHY_STATE: LifeCycleStateType = "available"
TRANSIENT_STATES: frozenset[LifeCycleStateType] = frozenset({"creating", "updating"})


@lambda_handler("efs-check", EfsConfig)
def check(cfg: EfsConfig, event: dict, *, dry_run: bool, context) -> dict:
    efs = client("efs", cfg.region)
    problems: dict[str, dict] = {}
    fatal: dict[str, dict] = {}

    for fs_id in cfg.file_system_ids:
        # aws efs describe-file-systems --file-system-id <id>
        #   の FileSystems[].LifeCycleState
        for fs in efs.describe_file_systems(FileSystemId=fs_id)["FileSystems"]:
            state = fs["LifeCycleState"]
            if state == HEALTHY_STATE:
                continue
            target = problems if state in TRANSIENT_STATES else fatal
            target[fs_id] = {"life_cycle_state": state}

        # aws efs describe-mount-targets --file-system-id <id>
        #   の MountTargets[].LifeCycleState
        # マウントターゲットはサブネットごとに 1 つ作られる。
        for mt in efs.describe_mount_targets(FileSystemId=fs_id)["MountTargets"]:
            state = mt["LifeCycleState"]
            if state == HEALTHY_STATE:
                continue
            key = f"{fs_id}/{mt['MountTargetId']}"
            detail = {"life_cycle_state": state, "subnet_id": mt.get("SubnetId")}
            target = problems if state in TRANSIENT_STATES else fatal
            target[key] = detail

    if fatal:
        raise NotRecoverableError(
            json.dumps({"efs": fatal}, ensure_ascii=False, default=str))
    return problems
