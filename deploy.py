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


def _get_var(name):
    val = os.getenv(name)
    assert val is not None, f"{name=} {val=}"
    return val


def _run_subprocess(command, log_stdout=False):
    try:
        # Prepend AWS credentials for AWS CLI commands
        if command[0].startswith('aws'):
            aws_access_key_id = _get_var('AWS_ACCESS_KEY_ID')
            aws_secret_access_key = _get_var('AWS_SECRET_ACCESS_KEY')
            aws_region = _get_var('AWS_REGION')
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


# local build
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
    region = os.getenv("AWS_REGION")
    assert region, f"Environment variable 'AWS_REGION' is not set. Current value: {region}"
    sts_client = boto3.client('sts', region_name=region)
    account_id = sts_client.get_caller_identity()["Account"]
    return f"{account_id}.dkr.ecr.{region}.amazonaws.com"

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
    #result = subprocess.run(["git", "remote", "-v"], capture_output=True, text=True)
    result = _run_subprocess(["git", "remote", "-v"], capture_output=True, text=True)
    remote_info = result.stdout
    match = re.search(r'https://(.+):(.+)@github.com/(.+/.+)\.git', remote_info)
    if match:
        return match.group(1), match.group(2), match.group(3)
    else:
        raise ValueError("No valid GitHub remote URL found.")

def set_github_secrets():
    """Set AWS credentials as GitHub Secrets based on the git remote info."""
    aws_access_key_id = _get_var("AWS_ACCESS_KEY_ID")
    aws_secret_access_key = _get_var("AWS_SECRET_ACCESS_KEY")
    username, pat, repository = get_git_remote_info()
    logger.info(f"{username=}")
    logger.info(f"{repository=}")
    set_github_secret(pat, repository, 'AWS_ACCESS_KEY_ID', aws_access_key_id)
    set_github_secret(pat, repository, 'AWS_SECRET_ACCESS_KEY', aws_secret_access_key)


from loguru import logger
import boto3

# Global constant for the tag value
PROJECT_NAME = "guiai"

def deploy_ec2_instance(ami='ami-0a8dada81f29ad054', instance_type='g5g.xlarge'):
    """
    Deploy an EC2 instance.

    - ami: Amazon Machine Image ID. Default is the deep learning AMI.
    - instance_type: Type of instance
        'p3.2xlarge' (V100 16GB $3.06/hr)
        'g5g.xlarge' (T4G 16GB $0.42/hr)
    """
    ec2 = boto3.resource('ec2')
    ec2_client = boto3.client('ec2')

    # Check for existing instances
    instances = ec2.instances.filter(
        Filters=[
            {'Name': 'tag:Name', 'Values': [PROJECT_NAME]},
            {'Name': 'instance-state-name', 'Values': ['running', 'stopped']}
        ]
    )

    for instance in instances:
        if instance.state['Name'] == 'running':
            logger.info(f"Instance already running: ID - {instance.id}, IP - {instance.public_ip_address}")
            return instance.id, instance.public_ip_address
        elif instance.state['Name'] == 'stopped':
            logger.info(f"Starting existing stopped instance: ID - {instance.id}")
            ec2_client.start_instances(InstanceIds=[instance.id])
            instance.wait_until_running()
            instance.reload()
            logger.info(f"Instance started: ID - {instance.id}, IP - {instance.public_ip_address}")
            return instance.id, instance.public_ip_address

    # Create a new instance if none exist
    new_instance = ec2.create_instances(
        ImageId=ami,
        MinCount=1,
        MaxCount=1,
        InstanceType=instance_type,
        TagSpecifications=[
            {
                'ResourceType': 'instance',
                'Tags': [
                    {
                        'Key': 'Name',
                        'Value': tag_value
                    }
                ]
            }
        ]
    )[0]

    new_instance.wait_until_running()
    new_instance.reload()
    logger.info(f"New instance created: ID - {new_instance.id}, IP - {new_instance.public_ip_address}")
    return new_instance.id, new_instance.public_ip_address


def shutdown_ec2_instance():
    ec2 = boto3.resource('ec2')

    instances = ec2.instances.filter(
        Filters=[
            {'Name': 'tag:Name', 'Values': [PROJECT_NAME]},
            {'Name': 'instance-state-name', 'Values': ['running']}
        ]
    )

    for instance in instances:
        logger.info(f"Shutting down instance: ID - {instance.id}")
        instance.stop()


def list_ec2_instances_by_tag():
    ec2 = boto3.resource('ec2')

    instances = ec2.instances.filter(
        Filters=[{'Name': 'tag:Name', 'Values': [PROJECT_NAME]}]
    )

    for instance in instances:
        logger.info(f"Instance ID: {instance.id}, State: {instance.state['Name']}")

# Usage Example
# Deploy instance
#instance_id, instance_ip = deploy_ec2_instance()
#logger.info(f"Deployed EC2 instance ID: {instance_id}, IP: {instance_ip}")

# List instances
#list_ec2_instances_by_tag()

# Shutdown instance
#shutdown_ec2_instance()

import git

def get_repo_details(remote_name="origin"):
    repo = git.Repo(search_parent_directories=True)
    remote_url = repo.remote(remote_name).url
    owner, repo_name = remote_url.split('/')[-2:]
    repo_name = repo_name.replace('.git', '')  # Remove .git from repo name
    return owner, repo_name

def create_iam_role(role_name=f"{PROJECT_NAME}-CodeBuildServiceRole"):
    iam = boto3.client('iam')
    assume_role_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Service": "codebuild.amazonaws.com"},
                "Action": "sts:AssumeRole"
            }
        ]
    }

    policy_arns = [
        "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryFullAccess",
        "arn:aws:iam::aws:policy/CloudWatchLogsFullAccess"
    ]

    # Create or retrieve the role
    try:
        role = iam.create_role(
            RoleName=role_name,
            AssumeRolePolicyDocument=json.dumps(assume_role_policy),
            Tags=[{'Key': 'Name', 'Value': PROJECT_NAME}]
        )
        role_arn = role['Role']['Arn']
        logger.info("IAM role created")
    except iam.exceptions.EntityAlreadyExistsException:
        logger.info("IAM role already exists")
        role = iam.get_role(RoleName=role_name)
        role_arn = role['Role']['Arn']

    # Attach necessary policies to the role
    for policy_arn in policy_arns:
        iam.attach_role_policy(
            RoleName=role_name,
            PolicyArn=policy_arn
        )
        logger.info(f"Attached policy {policy_arn} to role {role_name}")

    return role_arn


def create_codebuild_project(project_name=PROJECT_NAME, docker_buildspec="buildspec.yml"):
    owner, repo_name = get_repo_details()
    service_role_arn = create_iam_role()

    codebuild = boto3.client('codebuild')

    # Read the buildspec file content
    with open(docker_buildspec, 'r') as file:
        buildspec_content = file.read()

    try:
        response = codebuild.create_project(
            name=project_name,
            source={
                "type": "GITHUB",
                "location": f"https://github.com/{owner}/{repo_name}.git",
                "buildspec": buildspec_content  # Embed buildspec content
            },
            artifacts={"type": "NO_ARTIFACTS"},
            environment={
                "type": "LINUX_CONTAINER",
                "image": "aws/codebuild/standard:5.0",  # Use an image that supports CUDA
                "computeType": "BUILD_GENERAL1_LARGE",  # Adjust as necessary
                "environmentVariables": [{"name": "DOCKER_BUILDKIT", "value": "1"}]
            },
            serviceRole=service_role_arn,
            tags=[{"key": "Name", "value": PROJECT_NAME}],
        )
        logger.info(f"CodeBuild project created: {response}")
    except Exception as e:
        logger.error(f"Error creating CodeBuild project: {e}")

from jinja2 import Environment, FileSystemLoader
import os


def generate_buildspec(image_name=f"{PROJECT_NAME}-app", ecr_repository_uri=None):
    if not ecr_repository_uri:
        ecr_repository_uri = get_ecr_registry_url()

    # Set up Jinja2 environment
    env = Environment(loader=FileSystemLoader('.'))
    template = env.get_template('buildspec.yml.j2')

    # Render the template
    rendered_buildspec = template.render(
		aws_region=_get_var("AWS_REGION"),
        ecr_repository_uri=ecr_repository_uri, 
        image_name=image_name
    )

    # Write the rendered buildspec to a file
    with open('buildspec.yml', 'w') as file:
        file.write(rendered_buildspec)
    logger.info("buildspec.yml generated successfully.")


def get_current_git_branch():
    repo = git.Repo(search_parent_directories=True)
    branch = repo.active_branch.name
    return branch

def generate_github_actions_workflow(codebuild_project_name=PROJECT_NAME):
    current_branch = get_current_git_branch()

    # Set up Jinja2 environment
    env = Environment(loader=FileSystemLoader('.'))
    template = env.get_template('docker-build.yml.j2')

    # Render the template with the CodeBuild project name and current branch
    rendered_workflow = template.render(
        aws_region=_get_var("AWS_REGION"),
        codebuild_project_name=codebuild_project_name,
        branch_name=current_branch
    )

    # Write the rendered workflow to a file
    workflows_dir = '.github/workflows'
    os.makedirs(workflows_dir, exist_ok=True)
    with open(os.path.join(workflows_dir, 'docker-build.yml'), 'w') as file:
        file.write(rendered_workflow)
    logger.info("GitHub Actions workflow file generated successfully.")


if __name__ == "__main__":
    fire.Fire()
