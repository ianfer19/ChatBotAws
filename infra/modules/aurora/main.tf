# Aurora PostgreSQL Serverless v2 con pgvector para el conocimiento (RAG).
#
# Vive en las subnets privadas del módulo network; solo acepta tráfico 5432
# desde el CIDR de su propia VPC (las Lambdas se adhieren a la VPC cuando el
# RAG los necesite, SECURITY §6). Cifrado con la llave KMS del entorno y
# contraseña del master en Secrets Manager (nunca en el estado en claro:
# manage_master_user_password).

# La family se deriva de la versión mayor para no desincronizarla del engine.
resource "aws_rds_cluster_parameter_group" "this" {
  name   = "${var.name}-params"
  family = "aurora-postgresql${split(".", var.engine_version)[0]}"

  # pgvector recomendado en Aurora: la librería `vector` se precarga para que
  # la extensión esté disponible al `CREATE EXTENSION vector` de la migración
  # inicial (Paso 7). TODO(verify): nombre de la librería y si Aurora exige
  # reinicio aplicando este parámetro.
  parameter {
    name         = "shared_preload_libraries"
    value        = "vector"
    apply_method = "pending-reboot"
  }
}

resource "aws_db_subnet_group" "this" {
  name       = var.name
  subnet_ids = var.subnet_ids
}

resource "aws_security_group" "this" {
  name        = "${var.name}-aurora"
  description = "Aurora PostgreSQL de ${var.name}: 5432 solo desde el CIDR de la VPC"
  vpc_id      = var.vpc_id

  ingress {
    description = "PostgreSQL desde la propia VPC (Lambdas en VPC, Paso 7+)"
    from_port   = 5432
    to_port     = 5432
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
  }

  # Sin reglas de salida: la base de datos no necesita salir a internet.
}

resource "aws_rds_cluster" "this" {
  cluster_identifier              = var.name
  engine                          = "aurora-postgresql"
  engine_version                  = var.engine_version
  master_username                 = var.master_username
  manage_master_user_password     = true
  db_subnet_group_name            = aws_db_subnet_group.this.name
  vpc_security_group_ids          = [aws_security_group.this.id]
  db_cluster_parameter_group_name = aws_rds_cluster_parameter_group.this.name
  storage_encrypted               = true
  kms_key_id                      = var.kms_key_arn
  deletion_protection             = var.deletion_protection
  skip_final_snapshot             = var.skip_final_snapshot
  final_snapshot_identifier       = var.skip_final_snapshot ? null : "${var.name}-final"
  copy_tags_to_snapshot           = true

  serverlessv2_scaling_configuration {
    min_capacity = var.min_acu
    max_capacity = var.max_acu
  }
}

resource "aws_rds_cluster_instance" "this" {
  identifier           = "${var.name}-01"
  cluster_identifier   = aws_rds_cluster.this.id
  instance_class       = "db.serverless"
  engine               = "aurora-postgresql"
  engine_version       = var.engine_version
  db_subnet_group_name = aws_db_subnet_group.this.name
  publicly_accessible  = false
}
