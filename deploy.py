import subprocess
import json
import os

from dotenv import load_dotenv
from loguru import logger
import fire

# Load environment variables from .env file
load_dotenv()

def _run_subprocess(command, log_stdout=False):
    try:
        # Prepend AWS credentials for AWS CLI commands
        if command[0].startswith('aws'):
            aws_access_key_id = os.getenv('AWS_ACCESS_KEY_ID')
            aws_secret_access_key = os.getenv('AWS_SECRET_ACCESS_KEY')
            aws_region = os.getenv('AWS_REGION')
            assert aws_access_key_id, f"{aws_access_key_id=}"
            assert aws_secret_access_key, f"{aws_secret_access_key=}"
            assert aws_region, f"{aws_region=}"
            env = os.environ.copy()
            env['AWS_ACCESS_KEY_ID'] = aws_access_key_id
            env['AWS_SECRET_ACCESS_KEY'] = aws_secret_access_key
            env['AWS_REGION'] = aws_region
            logger.info(f"Running AWS command with Access Key ID: {aws_access_key_id}")
        else:
            env = None

        logger.info(f"Running command: {' '.join(command)}")
        result = subprocess.run(command, capture_output=True, text=True, check=True, env=env)

        if log_stdout:
            logger.info(result.stdout)

        return result
    except subprocess.CalledProcessError as e:
        logger.error(f"Command failed: {e.stderr}")
        return None


def create_ecs_cluster(cluster_name):
    command = ["aws", "ecs", "create-cluster", "--cluster-name", cluster_name]
    result = _run_subprocess(command, log_stdout=True)
    if result:
        output = json.loads(result.stdout)
        logger.info(f"Cluster created successfully: {json.dumps(output, indent=2)}")


"""
def build_docker_image(image_name, tag):
    full_image_name = f"{image_name}:{tag}"
    command = ["docker", "build", "-t", full_image_name, "."]
    result = _run_subprocess(command)
    if result:
        logger.info(f"Docker image {full_image_name} built successfully.")


def authenticate_ecr(region):
    get_login_command = ["aws", "ecr", "get-login-password", "--region", region]
    login_password_result = _run_subprocess(get_login_command, log_stdout=True)

    if login_password_result:
        login_password = login_password_result.stdout.strip()
        login_command = ["docker", "login", "--username", "AWS", "--password", login_password]
        login_result = _run_subprocess(login_command)
        if login_result:
            logger.info("Authenticated with ECR successfully.")


def create_ecr_repository(repo_name):
    command = ["aws", "ecr", "create-repository", "--repository-name", repo_name]
    result = _run_subprocess(command)
    if result:
        logger.info(f"ECR repository {repo_name} created successfully.")


def push_docker_image(repo_uri, image_name, tag):
    full_image_name = f"{image_name}:{tag}"
    remote_image_name = f"{repo_uri}:{tag}"

    # Tagging the image
    tag_command = ["docker", "tag", full_image_name, remote_image_name]
    tag_result = run_subprocess(tag_command)
    if tag_result:
        # Pushing the image
        push_command = ["docker", "push", remote_image_name]
        push_result = _run_subprocess(push_command)
        if push_result:
            logger.info(f"Docker image {remote_image_name} pushed to ECR successfully.")
"""

import os
import boto3
from jinja2 import Environment, FileSystemLoader

def get_ecr_registry_url():
    sts_client = boto3.client('sts')
    account_id = sts_client.get_caller_identity()["Account"]
    ecr_client = boto3.client('ecr')
    region = ecr_client.meta.region_name
    return f"{account_id}.dkr.ecr.{region}.amazonaws.com"


def get_current_git_branch():
    # Run the Git command to get the current branch name
    branch = subprocess.check_output(["git", "rev-parse", "--abbrev-ref", "HEAD"]).strip().decode('utf-8')
    logger.info(f"{branch=}")
    return branch


def create_workflow(ecr_repository):
    # Get current Git branch
    current_branch = get_current_git_branch()

    # Get ECR Registry URL
    ecr_registry = get_ecr_registry_url()

    # Set up Jinja2 environment
    env = Environment(loader=FileSystemLoader('.'))
    template = env.get_template('docker-build.yml.j2')

    # Render the template
    rendered_template = template.render(
        BRANCH=current_branch,
        ECR_REGISTRY=ecr_registry,
        ECR_REPOSITORY=ecr_repository,
    )

    # Create the .github/workflows directory if it doesn't exist
    os.makedirs('.github/workflows', exist_ok=True)

    # Write the rendered template to a file
    with open('.github/workflows/docker-build.yml', 'w') as file:
        file.write(rendered_template)


if __name__ == "__main__":
    fire.Fire()
