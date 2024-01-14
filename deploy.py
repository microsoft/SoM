from pprint import pformat
import subprocess
import json
import os
import re

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

    aws_region = os.getenv('AWS_REGION')

    # Render the template
    rendered_template = template.render(
        AWS_REGION=aws_region,
        BRANCH=current_branch,
        ECR_REGISTRY=ecr_registry,
        ECR_REPOSITORY=ecr_repository,
    )

    # Create the .github/workflows directory if it doesn't exist
    os.makedirs('.github/workflows', exist_ok=True)

    # Write the rendered template to a file
    with open('.github/workflows/docker-build.yml', 'w') as file:
        file.write(rendered_template)

import requests
import base64
from nacl import encoding, public

def encrypt(public_key: str, secret_value: str) -> str:
    """Encrypt a Unicode string using the public key."""
    public_key = public.PublicKey(public_key.encode("utf-8"), encoding.Base64Encoder())
    sealed_box = public.SealedBox(public_key)
    encrypted = sealed_box.encrypt(secret_value.encode("utf-8"))
    return base64.b64encode(encrypted).decode("utf-8")

def set_github_secret(token: str, repo: str, secret_name: str, secret_value: str):
    """Set a secret in the GitHub repository."""
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json"
    }
    response = requests.get(f"https://api.github.com/repos/{repo}/actions/secrets/public-key", headers=headers)
    response.raise_for_status()
    key = response.json()['key']
    key_id = response.json()['key_id']
    encrypted_value = encrypt(key, secret_value)
    secret_url = f"https://api.github.com/repos/{repo}/actions/secrets/{secret_name}"
    data = {"encrypted_value": encrypted_value, "key_id": key_id}
    response = requests.put(secret_url, headers=headers, json=data)
    response.raise_for_status()

def get_git_remote_info():
    """Extract the username, PAT, and repository name from the git remote URL."""
    result = subprocess.run(["git", "remote", "-v"], capture_output=True, text=True)
    remote_info = result.stdout
    match = re.search(r'https://(.+):(.+)@github.com/(.+/.+)\.git', remote_info)
    if match:
        return match.group(1), match.group(2), match.group(3)
    else:
        raise ValueError("No valid GitHub remote URL found.")

def set_github_secrets():
    """Set AWS credentials as GitHub Secrets based on the git remote info."""
    aws_access_key_id = os.getenv("AWS_ACCESS_KEY_ID")
    aws_secret_access_key = os.getenv("AWS_SECRET_ACCESS_KEY")
    assert aws_access_key_id, f"{aws_access_key_id=}"
    assert aws_secret_access_key, f"{aws_secret_access_key=}"
    username, pat, repository = get_git_remote_info()
    logger.info(f"{username=}")
    logger.info(f"{repository=}")
    set_github_secret(pat, repository, 'AWS_ACCESS_KEY_ID', aws_access_key_id)
    set_github_secret(pat, repository, 'AWS_SECRET_ACCESS_KEY', aws_secret_access_key)


if __name__ == "__main__":
    fire.Fire()
