resource "aws_sfn_state_machine" "onprem_command" {
  name       = "onprem-run-command"
  role_arn   = aws_iam_role.sfn.arn
  definition = templatefile("${path.module}/statemachine.json", {
    managed_instance_id = "mi-0c40127a4ea3076be"
  })
}