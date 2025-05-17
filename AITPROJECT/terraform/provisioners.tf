resource "null_resource" "setup_efs_and_code" {
  depends_on = [
    aws_instance.r5_xlarge
  ]

  connection {
    type        = "ssh"
    host        = aws_instance.r5_xlarge.public_ip
    user        = "ec2-user"
    private_key = file(var.ssh_private_key_path)
    timeout     = "2m"
  }

  # ─── 1) Install Docker, Docker-Compose, Git & prepare /efs ───────────────
  provisioner "remote-exec" {
    inline = [
      "set -ex",

      # Install Docker engine & start it
      "sudo amazon-linux-extras install docker -y",
      "sudo systemctl enable --now docker",

      # Install Docker Compose v2
      "sudo curl -SL \"https://github.com/docker/compose/releases/download/v2.17.3/docker-compose-$(uname -s)-$(uname -m)\" -o /usr/local/bin/docker-compose",
      "sudo chmod +x /usr/local/bin/docker-compose",
      "sudo ln -sf /usr/local/bin/docker-compose /usr/bin/docker-compose",

      # Add ec2-user to docker group (will take effect on next login)
      "sudo usermod -aG docker ec2-user",

      # Install Git and create /efs
      "sudo yum install -y git",
      "sudo mkdir -p /efs",
      "sudo chown ec2-user:ec2-user /efs",
    ]
  }

  # ─── 2) Clone or pull your repo into /efs/aitproject ───────────────────────
  provisioner "remote-exec" {
    inline = [
      "set -ex",
      "if [ ! -d /efs/aitproject ]; then",
      "  git clone \"${var.repo_url}\" /efs/aitproject",
      "else",
      "  cd /efs/aitproject && git pull",
      "fi",
      "sudo chown -R ec2-user:ec2-user /efs/aitproject",
    ]
  }
}
