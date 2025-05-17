terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    tls = {
      source  = "hashicorp/tls"
      version = "~> 4.0"
    }
  }
}

provider "aws" {
  region = "ap-southeast-1"
}

resource "aws_security_group" "allow_ssh" {
  name        = "allow_ssh_and_http"
  description = "Allow SSH (22) and HTTP (8000 & 8081) inbound traffic"

  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    from_port   = 8000
    to_port     = 8000
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    from_port   = 8081
    to_port     = 8081
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

data "aws_ami" "al2" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["amzn2-ami-hvm-*-x86_64-gp2"]
  }
}

resource "aws_instance" "r5_xlarge" {
  ami           = data.aws_ami.al2.id
  instance_type = "r5.xlarge"
  key_name      = var.key_name
  vpc_security_group_ids = [
    aws_security_group.allow_ssh.id,
  ]

  # Increase root volume to 50 GiB for model storage
  root_block_device {
    volume_size           = 50
    volume_type           = "gp3"
    delete_on_termination = true
  }

  tags = {
    Name = "r5-xlarge-on-demand-instance"
  }
}

output "instance_public_ip" {
  description = "Public IP of the r5.xlarge on-demand instance"
  value       = aws_instance.r5_xlarge.public_ip
}
