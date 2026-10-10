# Roles IAM de las Lambdas: un rol por función, nunca un rol compartido
# (least-privilege de SECURITY §2: si una función se compromete, solo toca lo
# suyo). Base obligatoria = logs de CloudWatch; lo demás entra por
# `inline_policies` con las acciones exactas que use cada función →
# TODO(verify) de las acciones mínimas por rol al cablear cada adapter.

resource "aws_iam_role" "lambda" {
  for_each = var.functions

  name = "chatbot-aws-${var.environment}-lambda-${each.key}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
        Action = "sts:AssumeRole"
      },
    ]
  })
}

resource "aws_iam_role_policy_attachment" "logs" {
  for_each = aws_iam_role.lambda

  role       = each.key
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "propia" {
  for_each = var.inline_policies

  name   = "chatbot-aws-${var.environment}-${each.key}"
  role   = aws_iam_role.lambda[each.key].id
  policy = each.value
}
