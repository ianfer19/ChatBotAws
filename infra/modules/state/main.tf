# Estado remoto de Terraform: S3 versionado + lock en DynamoDB.
#
# Es el recurso más sensible del sistema (quien controla el estado, controla la
# infraestructura), así que: cifrado en reposo, sin acceso público, solo por TLS
# y sin destroy accidental (force_destroy=false: un bucket no vacío no se borra).

resource "aws_s3_bucket" "state" {
  bucket        = var.bucket_name
  force_destroy = false
}

resource "aws_s3_bucket_versioning" "state" {
  bucket = aws_s3_bucket.state.id

  versioning_configuration {
    status = "Enabled"
  }
}

# Cifrado con la llave gestionada por S3 (`aws:kms` sin key propia = llave
# `aws/s3`): cumple la regla «KMS en S3» de infra/README.md sin costo de
# llave dedicada. TODO(verify): si la política exige CMK por entorno, sustituir.
resource "aws_s3_bucket_server_side_encryption_configuration" "state" {
  bucket = aws_s3_bucket.state.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "aws:kms"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "state" {
  bucket                  = aws_s3_bucket.state.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Nada viaja en claro hacia el bucket de estado: cualquier acceso sin TLS se
# niega en la política del propio bucket (defensa en profundidad, no depende
# del cliente).
resource "aws_s3_bucket_policy" "solo_tls" {
  bucket = aws_s3_bucket.state.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "DenyInsecureTransport"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:*"
        Resource = [
          aws_s3_bucket.state.arn,
          "${aws_s3_bucket.state.arn}/*",
        ]
        Condition = {
          Bool = {
            "aws:SecureTransport" = "false"
          }
        }
      },
    ]
  })
}

# Tabla de lock del backend S3: un solo lock por state (LockID), sin provisionar
# capacidad (on-demand) porque son pocas escrituras y solo durante los apply.
resource "aws_dynamodb_table" "lock" {
  name         = var.lock_table_name
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "LockID"

  attribute {
    name = "LockID"
    type = "S"
  }
}
