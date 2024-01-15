"""Deploy SoM to AWS.

Example Usage:
    1. `cp .env.example` `.env`
    2. Fill in `.env`
    3. `pip install client_requirements.txt`
    4. `python deploy.py configure
    5. `git add .github/workflows/docker-build.yml && git commit && git push`

"""

from datetime import datetime, timedelta
from pprint import pformat
import base64
import json
import os
import re
import subprocess
import time

from botocore.exceptions import ClientError
from dotenv import load_dotenv
from jinja2 import Environment, FileSystemLoader
from loguru import logger
from nacl import encoding, public
import boto3
import fire
import git
import paramiko
import requests

# Load environment variables from .env file
load_dotenv(".env")

# TODO: pydantic?
class Config:

    def _get_env(name):
        val = os.getenv(name)
        assert val is not None, f"{name=} {val=}"
        return val

    AWS_ACCESS_KEY_ID = _get_env("AWS_ACCESS_KEY_ID")
    AWS_SECRET_ACCESS_KEY = _get_env("AWS_SECRET_ACCESS_KEY")
    AWS_REGION = _get_env("AWS_REGION")
    GITHUB_REPO = _get_env("GITHUB_REPO")
    GITHUB_TOKEN = _get_env("GITHUB_TOKEN")
    PROJECT_NAME = _get_env("PROJECT_NAME")

    AWS_EC2_AMI = "ami-0a8dada81f29ad054"
    # "p3.2xlarge" (V100 16GB $3.06/hr x86_64)
    # "g5g.xlarge" (T4G 16GB $0.42/hr ARM64)
    AWS_EC2_INSTANCE_TYPE = "p3.2xlarge"
    AWS_EC2_KEY_NAME = f"{PROJECT_NAME}-key"
    AWS_EC2_SECURITY_GROUP = f"{PROJECT_NAME}-SecurityGroup"
    AWS_SSM_ROLE_NAME = f"{PROJECT_NAME}-SSMRole"
    AWS_SSM_PROFILE_NAME = f"{PROJECT_NAME}-SSMInstanceProfile"

def _run_subprocess(command, log_stdout=False):
    try:
        # Prepend AWS credentials for AWS CLI commands
        if command[0].startswith('aws'):
            env = os.environ.copy()
            env['AWS_ACCESS_KEY_ID'] = Config.AWS_ACCESS_KEY_ID
            env['AWS_SECRET_ACCESS_KEY'] = Config.AWS_SECRET_ACCESS_KEY
            env['AWS_REGION'] = Config.AWS_REGION
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

def create_ecs_cluster(cluster_name=f"{Config.PROJECT_NAME}-Cluster"):
    command = ["aws", "ecs", "create-cluster", "--cluster-name", cluster_name]
    result = _run_subprocess(command, log_stdout=True)
    if result:
        output = json.loads(result.stdout)
        logger.info(f"Cluster created successfully: {json.dumps(output, indent=2)}")

def create_ecr_repository(repo_name=f"{Config.PROJECT_NAME}-Repo"):
    command = ["aws", "ecr", "create-repository", "--repository-name", repo_name]
    result = _run_subprocess(command)
    if result:
        logger.info(f"ECR repository {repo_name} created successfully.")

def get_ecr_registry_url():
    sts_client = boto3.client('sts', region_name=config.AWS_REGION)
    account_id = sts_client.get_caller_identity()["Account"]
    return f"{account_id}.dkr.ecr.{region}.amazonaws.com"

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

def set_github_secrets():
    """Set AWS credentials as GitHub Secrets based on the git remote info."""
    github_repository
    set_github_secret(pat, Config.GITHUB_REPO, 'AWS_ACCESS_KEY_ID', AWS_ACCESS_KEY_ID)
    set_github_secret(pat, Config.GITHUB_REPO, 'AWS_SECRET_ACCESS_KEY', AWS_SECRET_ACCESS_KEY)

def create_key_pair(key_name=Config.AWS_EC2_KEY_NAME):
    """Create a new key pair and save it to a file."""
    ec2_client = boto3.client('ec2', region_name=Config.AWS_REGION)
    try:
        key_pair = ec2_client.create_key_pair(KeyName=key_name)
        private_key = key_pair['KeyMaterial']

        # Save the private key to a file
        with open(f"{key_name}.pem", "w") as key_file:
            key_file.write(private_key)
        os.chmod(f"{key_name}.pem", 0o400)  # Set read-only permissions

        logger.info(f"Key pair {key_name} created and saved to {key_name}.pem")
        return key_name
    except ClientError as e:
        logger.error(f"Error creating key pair: {e}")
        return None

def get_or_create_security_group_id():
    ec2 = boto3.client('ec2', region_name=Config.AWS_REGION)

    # Try to get the security group ID
    try:
        response = ec2.describe_security_groups(GroupNames=[Config.AWS_EC2_SECURITY_GROUP])
        security_group_id = response['SecurityGroups'][0]['GroupId']
        logger.info(f"Security group '{Config.AWS_EC2_SECURITY_GROUP}' already exists: {security_group_id}")
        # TODO: make sure current local ip is allowed
        return security_group_id
    except ClientError as e:
        if e.response['Error']['Code'] == 'InvalidGroup.NotFound':
            try:
                # Fetch the current public IP address
                response = requests.get('https://checkip.amazonaws.com')
                current_ip = response.text.strip()

                # Create the security group
                response = ec2.create_security_group(
                    GroupName=Config.AWS_EC2_SECURITY_GROUP,
                    Description='Security group for SSH access',
                    TagSpecifications=[
                        {
                            'ResourceType': 'security-group',
                            'Tags': [{'Key': 'Name', 'Value': Config.PROJECT_NAME}]
                        }
                    ]
                )
                security_group_id = response['GroupId']
                logger.info(f"Created security group '{Config.AWS_EC2_SECURITY_GROUP}' with ID: {security_group_id}")

                # Add a rule to allow SSH access
                ec2.authorize_security_group_ingress(
                    GroupId=security_group_id,
                    IpPermissions=[
                        {
                            'IpProtocol': 'tcp',
                            'FromPort': 22,
                            'ToPort': 22,
                            'IpRanges': [{'CidrIp': f"{current_ip}/32"}]
                        }
                    ]
                )
                logger.info(f"Added inbound rule to allow SSH from {current_ip}")

                return security_group_id
            except ClientError as e:
                logger.error(f"Error creating security group: {e}")
                return None
        else:
            logger.error(f"Error describing security groups: {e}")
            return None

def deploy_ec2_instance(
    ami=Config.AWS_EC2_AMI,
    instance_type=Config.AWS_EC2_INSTANCE_TYPE,
    project_name=Config.PROJECT_NAME,
    key_name=Config.AWS_EC2_KEY_NAME,
):
    """
    Deploy an EC2 instance.

    - ami: Amazon Machine Image ID. Default is the deep learning AMI.
    - instance_type: Type of instance
    """
    ec2 = boto3.resource('ec2')
    ec2_client = boto3.client('ec2')

    # Check if key pair exists, if not create one
    try:
        ec2_client.describe_key_pairs(KeyNames=[key_name])
    except ClientError as e:
        create_key_pair(key_name)

    # Fetch the security group ID
    security_group_id = get_or_create_security_group_id()
    if not security_group_id:
        logger.error("Unable to retrieve security group ID. Instance deployment aborted.")
        return None, None

    # Check for existing instances
    instances = ec2.instances.filter(
        Filters=[
            {'Name': 'tag:Name', 'Values': [Config.PROJECT_NAME]},
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
        KeyName=key_name,
        SecurityGroupIds=[security_group_id],  # Use the fetched security group ID
        TagSpecifications=[
            {
                'ResourceType': 'instance',
                'Tags': [{'Key': 'Name', 'Value': project_name}]
            }
        ]
    )[0]

    new_instance.wait_until_running()
    new_instance.reload()
    logger.info(f"New instance created: ID - {new_instance.id}, IP - {new_instance.public_ip_address}")
    return new_instance.id, new_instance.public_ip_address

def configure_ec2_instance(instance_id=None, instance_ip=None):
    if not instance_id:
        ec2_instance_id, ec2_instance_ip = deploy_ec2_instance()
    else:
        ec2_instance_id = instance_id
        ec2_instance_ip = instance_ip  # Ensure instance IP is provided if instance_id is manually passed

    key = paramiko.RSAKey.from_private_key_file(f"{Config.AWS_EC2_KEY_NAME}.pem")
    ssh_client = paramiko.SSHClient()
    ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        ssh_client.connect(hostname=ec2_instance_ip, username='ubuntu', pkey=key)

        # Commands to set up the EC2 instance for Docker builds
        commands = [
            "sudo apt-get update",
            "sudo apt-get install -y docker.io",
            "sudo systemctl start docker",
            "sudo systemctl enable docker",
            "sudo usermod -a -G docker ${USER}",
            "sudo curl -L \"https://github.com/docker/compose/releases/download/1.29.2/docker-compose-$(uname -s)-$(uname -m)\" -o /usr/local/bin/docker-compose",
            "sudo chmod +x /usr/local/bin/docker-compose",
            "sudo ln -s /usr/local/bin/docker-compose /usr/bin/docker-compose",
            "sudo apt-get install -y awscli",
            "aws configure set aws_access_key_id " + Config.AWS_ACCESS_KEY_ID,
            "aws configure set aws_secret_access_key " + Config.AWS_SECRET_ACCESS_KEY,
            "aws configure set default.region " + Config.AWS_REGION,
            # Additional CUDA specific installations can be added here if necessary
        ]

        for command in commands:
            stdin, stdout, stderr = ssh_client.exec_command(command)
            exit_status = stdout.channel.recv_exit_status()  # Blocking call
            if exit_status == 0:
                logger.info(f"Executed command: {command}")
            else:
                logger.error(f"Error in command: {command}, Exit Status: {exit_status}, Error: {stderr.read()}")

    except Exception as e:
        logger.error(f"SSH connection error: {e}")
    finally:
        ssh_client.close()

    logger.info(f"EC2 instance {ec2_instance_id} configured with Docker and necessary tools.")

def shutdown_ec2_instance():
    ec2 = boto3.resource('ec2')

    instances = ec2.instances.filter(
        Filters=[
            {'Name': 'tag:Name', 'Values': [Config.PROJECT_NAME]},
            {'Name': 'instance-state-name', 'Values': ['running']}
        ]
    )

    for instance in instances:
        logger.info(f"Shutting down instance: ID - {instance.id}")
        instance.stop()

def list_ec2_instances_by_tag():
    ec2 = boto3.resource('ec2')

    instances = ec2.instances.filter(
        Filters=[{'Name': 'tag:Name', 'Values': [Config.PROJECT_NAME]}]
    )

    for instance in instances:
        logger.info(f"Instance ID: {instance.id}, State: {instance.state['Name']}")

def generate_github_actions_workflow__ec2():
    current_branch = get_current_git_branch()

    # Set up Jinja2 environment
    env = Environment(loader=FileSystemLoader('.'))
    template = env.get_template('docker-build-ec2.yml.j2')

    # Render the template with the current branch
    rendered_workflow = template.render(branch_name=current_branch)

    # Write the rendered workflow to a file
    workflows_dir = '.github/workflows'
    os.makedirs(workflows_dir, exist_ok=True)
    with open(os.path.join(workflows_dir, 'docker-build-ec2.yml'), 'w') as file:
        file.write(rendered_workflow)
    logger.info("GitHub Actions EC2 workflow file generated successfully.")

def get_repo_details(remote_name="origin"):
    repo = git.Repo(search_parent_directories=True)
    remote_url = repo.remote(remote_name).url
    owner, repo_name = remote_url.split('/')[-2:]
    repo_name = repo_name.replace('.git', '')  # Remove .git from repo name
    return owner, repo_name

def create_codebuild_iam_role(role_name=f"{Config.PROJECT_NAME}-CodeBuildServiceRole"):
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
            Tags=[{'Key': 'Name', 'Value': Config.PROJECT_NAME}]
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

def create_codebuild_project(project_name=Config.PROJECT_NAME, docker_buildspec="buildspec.yml"):
    owner, repo_name = get_repo_details()
    service_role_arn = create_codebuild_iam_role()

    codebuild = boto3.client('codebuild')

    # Read the buildspec file content
    with open(docker_buildspec, 'r') as file:
        buildspec_content = file.read()

    try:
        # Try to delete the project if it exists
        codebuild.delete_project(name=project_name)
        logger.info(f"Existing CodeBuild project '{project_name}' deleted.")
    except codebuild.exceptions.ResourceNotFoundException:
        # If the project does not exist, just proceed
        logger.info(f"CodeBuild project '{project_name}' does not exist. Proceeding to create a new one.")

    try:
        # Create a new CodeBuild project
        response = codebuild.create_project(
            name=project_name,
            source={
                "type": "GITHUB",
                "location": f"https://github.com/{owner}/{repo_name}.git",
                "buildspec": buildspec_content  # Embed buildspec content
            },
            artifacts={"type": "NO_ARTIFACTS"},
            environment={
                "type": "LINUX_GPU_CONTAINER",
                "image": "aws/codebuild/standard:5.0",  # Use an image that supports CUDA
                "computeType": "BUILD_GENERAL1_LARGE",
                "environmentVariables": [{"name": "DOCKER_BUILDKIT", "value": "1"}]
            },
            serviceRole=service_role_arn,
            tags=[{"key": "Name", "value": Config.PROJECT_NAME}],
        )
        logger.info(f"New CodeBuild project '{project_name}' created: {response}")
    except Exception as e:
        logger.error(f"Error creating CodeBuild project '{project_name}': {e}")

def generate_buildspec(image_name=f"{Config.PROJECT_NAME}-app", ecr_repository_uri=None):
    if not ecr_repository_uri:
        ecr_repository_uri = get_ecr_registry_url()

    # Set up Jinja2 environment
    env = Environment(loader=FileSystemLoader('.'))
    template = env.get_template('buildspec.yml.j2')

    # Render the template
    rendered_buildspec = template.render(
        aws_region=Config.AWS_REGION,
        branch_name=get_current_git_branch(),
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

def generate_github_actions_workflow__codebuild(codebuild_project_name=Config.PROJECT_NAME):
    current_branch = get_current_git_branch()

    # Set up Jinja2 environment
    env = Environment(loader=FileSystemLoader('.'))
    template = env.get_template('docker-build.yml.j2')

    # Render the template with the CodeBuild project name and current branch
    rendered_workflow = template.render(
        aws_region=Config.AWS_REGION,
        codebuild_project_name=codebuild_project_name,
        branch_name=current_branch
    )

    # Write the rendered workflow to a file
    workflows_dir = '.github/workflows'
    os.makedirs(workflows_dir, exist_ok=True)
    with open(os.path.join(workflows_dir, 'docker-build.yml'), 'w') as file:
        file.write(rendered_workflow)
    logger.info("GitHub Actions workflow file generated successfully.")

def get_quota_usage(
    # Service code for AWS CodeBuild
    service_code='codebuild',
    # Quota code for maximum number of build projects
    quota_code='L-ACCF6C0D',
):

    service_quotas = boto3.client('service-quotas', region_name=Config.AWS_REGION)

    # Get information about the quota
    quota_info = service_quotas.get_service_quota(
        ServiceCode=service_code,
        QuotaCode=quota_code
    )

    quota_value = quota_info['Quota']['Value']
    usage_info = service_quotas.get_usage_for_quota(
        ServiceCode=service_code,
        QuotaCode=quota_code
    )
    
    usage = usage_info['Usage'][0]['Value'] if usage_info['Usage'] else 'Not available'

    return {
        'QuotaValue': quota_value,
        'CurrentUsage': usage
    }

def get_quota_value(
    # Service code for AWS CodeBuild
    service_code='codebuild',
    # Quota code for maximum number of build projects
    quota_code='L-ACCF6C0D',
):

    # Create a Service Quotas client
    service_quotas = boto3.client('service-quotas', region_name=Config.AWS_REGION)

    # Retrieve the quota information
    try:
        quota = service_quotas.get_service_quota(
            ServiceCode=service_code,
            QuotaCode=quota_code
        )
        return quota
    except service_quotas.exceptions.NoSuchResourceException:
        print(f"No such quota found for service code: {service_code} and quota code: {quota_code}")
        return None

def get_codebuild_usage():
    # Create a CodeBuild client
    codebuild = boto3.client('codebuild', region_name=config.AWS_REGION)

    # Calculate start time for build counts (e.g., last 24 hours)
    start_time = datetime.utcnow() - timedelta(hours=24)
    build_count = 0

    # Get the list of build IDs for the project
    response = codebuild.list_builds_for_project(projectName=Config.PROJECT_NAME)
    build_ids = response.get('ids', [])
    logger.info(f"{build_ids=}")

    # Retrieve detailed information for each build ID
    builds_info = codebuild.batch_get_builds(ids=build_ids)['builds']

    # Count the number of builds started within the last 24 hours
    for build in builds_info:
        if build['startTime'] > start_time:
            build_count += 1

    return build_count

def configure(build_with_codebuild=False, deploy_to_ecs=False):
    create_ecr_repository()
    set_github_secrets()

    if build_with_codebuild:
        create_codebuild_project()
    else:
        configure_ec2_instance()

    if deploy_to_ecs:
        create_ecs_cluster()

if __name__ == "__main__":
    fire.Fire()


# SCRATCH

# local build only
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
