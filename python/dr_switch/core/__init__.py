"""リソースに依存しない共通部分.

パッケージ外からはこのファサード経由で使う。
dr_switch/core/ の内部は、循環インポートを避けるため必ずフルパスで
import すること（絶対 import は PEP 8 の推奨でもある）。
"""

from dr_switch.core.aws import BOTO_CONFIG, client
from dr_switch.core.config import (
    BaseConfig,
    optional,
    optional_json,
    required,
)
from dr_switch.core.errors import (
    AWS_ERRORS,
    ContinuableError,
    RetryableError,
    classify,
    raise_classified,
    run_per_item,
)
from dr_switch.core.middleware import check_handler, ops_handler

__all__ = [
    "AWS_ERRORS",
    "BOTO_CONFIG",
    "BaseConfig",
    "ContinuableError",
    "RetryableError",
    "check_handler",
    "classify",
    "client",
    "ops_handler",
    "optional",
    "optional_json",
    "raise_classified",
    "required",
    "run_per_item",
]
