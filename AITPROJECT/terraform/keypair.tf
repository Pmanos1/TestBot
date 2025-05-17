# keypair.tf

# We assume variables “ssh_private_key_path” and “key_name” are declared once in variables.tf

# 1) Read your local PEM as the input
data "tls_public_key" "kp" {
  private_key_pem = file(var.ssh_private_key_path)
}

# 2) Register that derived public key in AWS
resource "aws_key_pair" "kp" {
  key_name   = var.key_name
  public_key = data.tls_public_key.kp.public_key_openssh
}
