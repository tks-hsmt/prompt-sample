# ============================================================================
# Lambda 関数の定義（サンプル）
#
# 17 関数すべてが同一のコンテナイメージを共有し、image_config.command で
# ハンドラを切り替える。Lambda はイメージをダイジェスト単位でキャッシュする
# ため、共有すると最初の 1 本がキャッシュを温め残りがその恩恵を受ける。
#
# 環境変数は「その関数が操作・確認する対象の値だけ」を渡す。閉塞系には相手
# リージョンの値、開放系と観測系には自リージョンの値。コードは自他を区別
# しないので、どちらを渡すかはここで決まる。
# ============================================================================

variable "image_uri" {
  description = "ECR のイメージ URI（ダイジェスト指定を推奨）"
  type        = string
}

locals {
  # 到達不能時 15〜20 秒 ＋ 通常の最大 5 秒 ＋ 余裕。
  # restart_pods だけは呼ばれる側の完了を待つため別枠。
  default_timeout = 60

  functions = {
    "apigateway-block" = {
      command = ["dr_switch.apigateway.handlers.block"]
      env = {
        REGION      = var.peer_region
        REST_API_ID = var.peer_rest_api_id
        STAGE       = var.peer_stage
      }
    }
    "apigateway-enable" = {
      command = ["dr_switch.apigateway.handlers.enable"]
      env = {
        REGION         = var.self_region
        REST_API_ID    = var.self_rest_api_id
        STAGE          = var.self_stage
        THROTTLE_RATE  = "10000"
        THROTTLE_BURST = "5000"
      }
    }
    "apigateway-check" = {
      command = ["dr_switch.apigateway.handlers.check"]
      env = {
        REGION         = var.self_region
        REST_API_ID    = var.self_rest_api_id
        STAGE          = var.self_stage
        THROTTLE_RATE  = "10000"
        THROTTLE_BURST = "5000"
      }
    }
    "scheduler-block" = {
      command = ["dr_switch.scheduler.handlers.block"]
      env     = { REGION = var.peer_region, SCHEDULE_GROUP = var.peer_schedule_group }
    }
    "scheduler-enable" = {
      command = ["dr_switch.scheduler.handlers.enable"]
      env     = { REGION = var.self_region, SCHEDULE_GROUP = var.self_schedule_group }
    }
    "scheduler-check" = {
      command = ["dr_switch.scheduler.handlers.check"]
      env     = { REGION = var.self_region, SCHEDULE_GROUP = var.self_schedule_group }
    }
    "s3-block" = {
      command = ["dr_switch.s3.handlers.block"]
      env = {
        REGION              = var.peer_region
        REPLICATION_BUCKETS = jsonencode(var.peer_replication_buckets)
      }
    }
    "s3-enable" = {
      command = ["dr_switch.s3.handlers.enable"]
      env = {
        REGION              = var.self_region
        REPLICATION_BUCKETS = jsonencode(var.self_replication_buckets)
      }
    }
    "s3-check" = {
      command = ["dr_switch.s3.handlers.check"]
      env = {
        REGION              = var.self_region
        REPLICATION_BUCKETS = jsonencode(var.self_replication_buckets)
      }
    }
    "lambda-check" = {
      command = ["dr_switch.lambda_function.handlers.check"]
      env = {
        REGION         = var.self_region
        FUNCTION_NAMES = jsonencode(var.self_function_names)
      }
    }
    "dynamodb-check" = {
      command = ["dr_switch.dynamodb.handlers.check"]
      env     = { REGION = var.self_region, TABLE_NAMES = jsonencode(var.self_table_names) }
    }
    "nlb-check" = {
      command = ["dr_switch.nlb.handlers.check"]
      env = {
        REGION             = var.self_region
        TARGET_GROUP_ARNS  = jsonencode(var.self_target_group_arns)
        LOAD_BALANCER_ARNS = jsonencode(var.self_load_balancer_arns)
      }
    }
    "cloudwatch-check" = {
      command = ["dr_switch.cloudwatch.handlers.check"]
      env     = { REGION = var.self_region, ALARM_PREFIX = var.alarm_prefix }
    }
    "efs-check" = {
      command = ["dr_switch.efs.handlers.check"]
      env = {
        REGION          = var.self_region
        FILE_SYSTEM_IDS = jsonencode(var.self_file_system_ids)
      }
    }
    "eks-check" = {
      command = ["dr_switch.eks.handlers.check"]
      env     = { REGION = var.self_region, EKS_CLUSTERS = jsonencode(var.eks_clusters) }
    }
    "eks-rollout-restart" = {
      command = ["dr_switch.eks.handlers.rollout_restart"]
      env     = { REGION = var.self_region, EKS_CLUSTERS = jsonencode(var.eks_clusters) }
    }
    "eks-restart-pods" = {
      command = ["dr_switch.eks.handlers.restart_pods"]
      env = {
        REGION                = var.self_region
        POD_RESTART_FUNCTIONS = jsonencode(var.pod_restart_function_names)
        POD_RESTART_TIMEOUT   = tostring(var.pod_restart_timeout)
      }
    }
  }
}

variable "self_target_group_arns" {
  type = list(string)
}

variable "self_load_balancer_arns" {
  type    = list(string)
  default = []
}

variable "pod_restart_timeout" {
  description = "呼ばれる側の Lambda の Timeout に合わせる"
  type        = number
  default     = 300
}

resource "aws_lambda_function" "dr" {
  for_each = local.functions

  function_name = "dr-${each.key}"
  role          = aws_iam_role.dr[each.key].arn
  package_type  = "Image"
  image_uri     = var.image_uri

  # restart_pods は呼ばれる側の完了を待つため、その Timeout を上回る値にする
  timeout = each.key == "eks-restart-pods" ? var.pod_restart_timeout + 60 : local.default_timeout

  image_config {
    command = each.value.command
  }

  environment {
    variables = each.value.env
  }

  # 全関数を VPC 内に配置する。NAT ゲートウェイが無いため、AWS API へは
  # VPC エンドポイント経由で到達する（network.tf を参照）。
  vpc_config {
    subnet_ids         = var.vpc_subnet_ids
    security_group_ids = [aws_security_group.dr_lambda.id]
  }

  depends_on = [
    aws_iam_role_policy.dr,
    aws_iam_role_policy_attachment.basic,
    aws_iam_role_policy_attachment.vpc,
    aws_security_group_rule.endpoint_from_dr_lambda,
    aws_security_group_rule.eks_from_dr_lambda,
  ]
}

output "function_arns" {
  description = "Step Functions の ASL に埋める関数 ARN"
  value       = { for k, f in aws_lambda_function.dr : k => f.arn }
}
