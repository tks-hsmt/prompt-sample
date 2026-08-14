# 既存の Pod 再起動 Lambda に合わせてコンテナイメージでデプロイする。
# 10 本の Lambda で同一イメージを共有し、CMD（ハンドラ）だけ変える。
FROM public.ecr.aws/lambda/python:3.13

# check_workload が使う AWS CLI。他の関数では未使用だが、イメージを
# 分けるほどの差ではないため同梱する。
RUN dnf install -y unzip tar gzip \
 && curl -sSL "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o /tmp/awscliv2.zip \
 && unzip -q /tmp/awscliv2.zip -d /tmp \
 && /tmp/aws/install \
 && rm -rf /tmp/awscliv2.zip /tmp/aws \
 && dnf clean all

COPY requirements.txt ${LAMBDA_TASK_ROOT}/
RUN pip install --no-cache-dir -r ${LAMBDA_TASK_ROOT}/requirements.txt

COPY *.py ${LAMBDA_TASK_ROOT}/

# ハンドラは Terraform の image_config.command で関数ごとに上書きする。
#   例: command = ["check_nlb.handler"]
CMD ["apigw.handler"]
