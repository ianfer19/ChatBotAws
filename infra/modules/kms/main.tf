# Llave KMS por entorno, compartida por los datos de ese entorno (Aurora,
# DynamoDB, S3): una llave por entorno en lugar de una por recurso para no
# pagar una llave por tabla/bucket (TODO(verify pricing)).
#
# La rotación automática queda activada; quién rota y con qué política de
# administradores → TODO(verify) (SECURITY §4).

resource "aws_kms_key" "this" {
  description             = "chatbot-aws ${var.name}"
  deletion_window_in_days = 30
  enable_key_rotation     = true
}

resource "aws_kms_alias" "this" {
  name          = "alias/${var.name}"
  target_key_id = aws_kms_key.this.key_id
}
