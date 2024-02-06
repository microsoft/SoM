"""Deploy SoM to AWS EC2.

Usage:

    1. Create and populate the .env file:

        echo "AWS_ACCESS_KEY_ID=<your aws access key id>" > .env
        echo "AWS_SECRET_ACCESS_KEY=<your aws secret access key>" >> .env
        echo "AWS_REGION=<your aws region>" >> .env
        echo "GITHUB_OWNER=<your github owner>" >> .env
        echo "GITHUB_REPO=<your github repo>" >> .env
        echo "GITHUB_TOKEN=<your github token>" >> .env
        echo "PROJECT_NAME=<your project name>" >> .env

    2. Create a virtual environment for deployment:

        python -m venv venv
        source venv/bin/activate
        pip install deploy_requirements.txt

    3. Run the deployment script:

        python deploy.py run

    4. Commit the newly generated github workflow file:

        git add .github/workflows/docker-build-ec2.yml
        git commit -m "add workflow file"
        git push

    5. Wait for the build to succeed in Github actions (see console output for details)

    6. Open the EC2 gradio url (see console output for details) and test it out.
       TODO: client.py

    7. Terminate or shutdown EC2 instance to stop incurring charges:

        python deploy.py terminate_ec2_instance
        # or, if you want to shut it down without removing it:
        python deploy.py shutdown_ec2_instance

    8. List all tagged instances with their respective status:

        python deploy.py list_ec2_instances

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
    GITHUB_OWNER = _get_env("GITHUB_OWNER")
    GITHUB_REPO = _get_env("GITHUB_REPO")
    GITHUB_TOKEN = _get_env("GITHUB_TOKEN")
    PROJECT_NAME = _get_env("PROJECT_NAME")

    AWS_EC2_AMI = "ami-0f9c346cdcac09fb5"  # Deep Learning AMI GPU PyTorch 2.0.1 (Ubuntu 20.04) 20230827
                  
    AWS_EC2_DISK_SIZE = 100  # GB
    AWS_EC2_INSTANCE_TYPE = "g4dn.xlarge"  # (T4 16GB $0.526/hr x86_64)
    AWS_EC2_INSTANCE_TYPE = "p3.2xlarge"  # (V100 16GB $3.06/hr x86_64)
    AWS_EC2_KEY_NAME = f"{PROJECT_NAME}-key"
    AWS_EC2_KEY_PATH = f"./{AWS_EC2_KEY_NAME}.pem"
    AWS_EC2_SECURITY_GROUP = f"{PROJECT_NAME}-SecurityGroup"
    AWS_EC2_USER = "ubuntu"
    AWS_SSM_ROLE_NAME = f"{PROJECT_NAME}-SSMRole"
    AWS_SSM_PROFILE_NAME = f"{PROJECT_NAME}-SSMInstanceProfile"
    GITHUB_PATH = f"{GITHUB_OWNER}/{GITHUB_REPO}"

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
    logger.info(f"set {secret_name=}")

def set_github_secrets():
    """Set AWS credentials and SSH private key as GitHub Secrets."""
    # Set AWS secrets
    set_github_secret(Config.GITHUB_TOKEN, Config.GITHUB_PATH, 'AWS_ACCESS_KEY_ID', Config.AWS_ACCESS_KEY_ID)
    set_github_secret(Config.GITHUB_TOKEN, Config.GITHUB_PATH, 'AWS_SECRET_ACCESS_KEY', Config.AWS_SECRET_ACCESS_KEY)

    # Read the SSH private key from the file
    try:
        with open(Config.AWS_EC2_KEY_PATH, 'r') as key_file:
            ssh_private_key = key_file.read()
        set_github_secret(Config.GITHUB_TOKEN, Config.GITHUB_PATH, 'SSH_PRIVATE_KEY', ssh_private_key)
    except IOError as e:
        logger.error(f"Error reading SSH private key file: {e}")

def create_key_pair(key_name=Config.AWS_EC2_KEY_NAME, key_path=Config.AWS_EC2_KEY_PATH):
    """Create a new key pair and save it to a file."""
    ec2_client = boto3.client('ec2', region_name=Config.AWS_REGION)
    try:
        key_pair = ec2_client.create_key_pair(KeyName=key_name)
        private_key = key_pair['KeyMaterial']

        # Save the private key to a file
        with open(key_path, "w") as key_file:
            key_file.write(private_key)
        os.chmod(key_path, 0o400)  # Set read-only permissions

        logger.info(f"Key pair {key_name} created and saved to {key_path}")
        return key_name
    except ClientError as e:
        logger.error(f"Error creating key pair: {e}")
        return None

def get_or_create_security_group_id(ports=[22, 6092]):
    ec2 = boto3.client('ec2', region_name=Config.AWS_REGION)

    try:
        response = ec2.describe_security_groups(GroupNames=[Config.AWS_EC2_SECURITY_GROUP])
        security_group_id = response['SecurityGroups'][0]['GroupId']
        logger.info(f"Security group '{Config.AWS_EC2_SECURITY_GROUP}' already exists: {security_group_id}")

        for port in ports:
            try:
                ec2.authorize_security_group_ingress(
                    GroupId=security_group_id,
                    IpPermissions=[
                        {
                            'IpProtocol': 'tcp',
                            'FromPort': port,
                            'ToPort': port,
                            'IpRanges': [{'CidrIp': '0.0.0.0/0'}]
                        }
                    ]
                )
                logger.info(f"Added inbound rule to allow TCP traffic on port {port} from any IP")
            except ClientError as e:
                if e.response['Error']['Code'] == 'InvalidPermission.Duplicate':
                    logger.info(f"Rule for port {port} already exists")
                else:
                    logger.error(f"Error adding rule for port {port}: {e}")

        return security_group_id
    except ClientError as e:
        if e.response['Error']['Code'] == 'InvalidGroup.NotFound':
            try:
                # Create the security group
                response = ec2.create_security_group(
                    GroupName=Config.AWS_EC2_SECURITY_GROUP,
                    Description='Security group for specified port access',
                    TagSpecifications=[
                        {
                            'ResourceType': 'security-group',
                            'Tags': [{'Key': 'Name', 'Value': Config.PROJECT_NAME}]
                        }
                    ]
                )
                security_group_id = response['GroupId']
                logger.info(f"Created security group '{Config.AWS_EC2_SECURITY_GROUP}' with ID: {security_group_id}")

                # Add rules for the given ports
                ec2.authorize_security_group_ingress(GroupId=security_group_id, IpPermissions=ip_permissions)
                logger.info("Added inbound rules to allow access on specified ports")

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
    disk_size=Config.AWS_EC2_DISK_SIZE,
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
            {'Name': 'instance-state-name', 'Values': ['running', 'pending', 'stopped']}
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
        elif state == 'pending':
            logger.info(f"Instance is pending: ID - {instance.id}. Waiting for 'running' state.")
            try:
                instance.wait_until_running()  # Wait for the instance to be in 'running' state
                instance.reload()  # Reload the instance attributes
                logger.info(f"Instance is now running: ID - {instance.id}, IP - {instance.public_ip_address}")
                return instance.id, instance.public_ip_address
            except botocore.exceptions.WaiterError as e:
                logger.error(f"Error waiting for instance to run: {e}")
                return None, None
    # Define EBS volume configuration
    ebs_config = {
        'DeviceName': '/dev/sda1',  # You may need to change this depending on the instance type and AMI
        'Ebs': {
            'VolumeSize': disk_size,
            'VolumeType': 'gp3',  # Or other volume types like gp2, io1, etc.
            'DeleteOnTermination': True  # Set to False if you want to keep the volume after instance termination
        },
    }

    # Create a new instance if none exist
    new_instance = ec2.create_instances(
        ImageId=ami,
        MinCount=1,
        MaxCount=1,
        InstanceType=instance_type,
        KeyName=key_name,
        SecurityGroupIds=[security_group_id],
        BlockDeviceMappings=[ebs_config],
        TagSpecifications=[
            {
                'ResourceType': 'instance',
                'Tags': [{'Key': 'Name', 'Value': project_name}]
            },
        ]
    )[0]

    new_instance.wait_until_running()
    new_instance.reload()
    logger.info(f"New instance created: ID - {new_instance.id}, IP - {new_instance.public_ip_address}")
    return new_instance.id, new_instance.public_ip_address

def configure_ec2_instance(instance_id=None, instance_ip=None, max_ssh_retries=3, ssh_retry_delay=10, max_cmd_retries=5, cmd_retry_delay=30):
    if not instance_id:
        ec2_instance_id, ec2_instance_ip = deploy_ec2_instance()
    else:
        ec2_instance_id = instance_id
        ec2_instance_ip = instance_ip  # Ensure instance IP is provided if instance_id is manually passed

    key = paramiko.RSAKey.from_private_key_file(f"{Config.AWS_EC2_KEY_NAME}.pem")
    ssh_client = paramiko.SSHClient()
    ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    ssh_retries = 0
    while ssh_retries < max_ssh_retries:
        try:
            ssh_client.connect(hostname=ec2_instance_ip, username='ubuntu', pkey=key)
            break  # Successful SSH connection, break out of the loop
        except Exception as e:
            ssh_retries += 1
            logger.error(f"SSH connection attempt {ssh_retries} failed: {e}")
            if ssh_retries < max_ssh_retries:
                logger.info(f"Retrying SSH connection in {ssh_retry_delay} seconds...")
                time.sleep(ssh_retry_delay)
            else:
                logger.error("Maximum SSH connection attempts reached. Aborting.")
                return

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
        # Additional commands can be added here
    ]

    # Define sensitive keys to obfuscate
    sensitive_keys = ["AWS_SECRET_ACCESS_KEY"]

    for command in commands:
        cmd_retries = 0
        while cmd_retries < max_cmd_retries:
            stdin, stdout, stderr = ssh_client.exec_command(command)
            exit_status = stdout.channel.recv_exit_status()  # Blocking call

            if exit_status == 0:
                # Obfuscate sensitive information in log messages
                log_command = command
                for key in sensitive_keys:
                    secret_value = getattr(Config, key, None)
                    if secret_value and secret_value in command:
                        log_command = command.replace(secret_value, "*" * len(secret_value))
                logger.info(f"Executed command: {log_command}")
                break  # Command executed successfully, break out of the loop
            else:
                error_message = stderr.read()
                if "Could not get lock" in str(error_message):
                    cmd_retries += 1
                    logger.warning(f"dpkg is locked, retrying command in {cmd_retry_delay} seconds... Attempt {cmd_retries}/{max_cmd_retries}")
                    time.sleep(cmd_retry_delay)
                else:
                    logger.error(f"Error in command: {command}, Exit Status: {exit_status}, Error: {error_message}")
                    break  # Non-dpkg lock error, break out of the loop

    ssh_client.close()
    return ec2_instance_id, ec2_instance_ip

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

def terminate_ec2_instance():
    ec2_resource = boto3.resource('ec2')
    ec2_client = boto3.client('ec2')

    # Terminate EC2 instances
    instances = ec2_resource.instances.filter(
        Filters=[
            {'Name': 'tag:Name', 'Values': [Config.PROJECT_NAME]},
            {'Name': 'instance-state-name', 'Values': ['pending', 'running', 'shutting-down', 'stopped', 'stopping']}
        ]
    )

    instance_ids = [instance.id for instance in instances]
    if instance_ids:
        ec2_resource.instances.filter(InstanceIds=instance_ids).terminate()
        for instance_id in instance_ids:
            logger.info(f"Terminating instance: ID - {instance_id}")

    # Custom wait loop for instances to terminate
    for instance_id in instance_ids:
        instance = ec2_resource.Instance(instance_id)
        max_wait_attempts = 10
        wait_interval = 30  # seconds

        for _ in range(max_wait_attempts):
            instance.reload()
            if instance.state['Name'] == 'terminated':
                break
            time.sleep(wait_interval)
        else:
            logger.warning(f"Instance {instance_id} did not terminate within the expected time.")


    # Detach and delete EBS volumes
    for instance_id in instance_ids:
        instance = ec2_resource.Instance(instance_id)
        for volume in instance.volumes.all():
            if volume.state == 'in-use':
                volume.detach_from_instance(InstanceId=instance_id, Force=True)
                logger.info(f"Detached volume: {volume.id} from {instance_id}")

            # Wait until the volume is available before deletion
            volume.wait_until_available()
            volume.delete()
            logger.info(f"Deleted volume: {volume.id}")

    # Check for network interfaces
    network_interfaces = ec2_client.describe_network_interfaces(
        #Filters=[{'Name': 'group-id', 'Values': [security_group_id]}]
    )['NetworkInterfaces']
    for ni in network_interfaces:
        ec2_client.detach_network_interface(AttachmentId=ni['Attachment']['AttachmentId'])
        ec2_client.delete_network_interface(NetworkInterfaceId=ni['NetworkInterfaceId'])

    # Delete security group
    try:
        # Attempt to describe the security group to check if it exists
        ec2_client.describe_security_groups(GroupNames=[Config.AWS_EC2_SECURITY_GROUP])
        # If it exists, proceed to delete
        ec2_client.delete_security_group(GroupName=Config.AWS_EC2_SECURITY_GROUP)
        logger.info(f"Deleted security group: {Config.AWS_EC2_SECURITY_GROUP}")
    except ClientError as e:
        if e.response['Error']['Code'] == 'InvalidGroup.NotFound':
            logger.info(f"Security group {Config.AWS_EC2_SECURITY_GROUP} does not exist or already deleted.")
        else:
            logger.error(f"Error deleting security group: {e}")

def list_ec2_instances():
    ec2 = boto3.resource('ec2')

    instances = ec2.instances.filter(
        Filters=[{'Name': 'tag:Name', 'Values': [Config.PROJECT_NAME]}]
    )

    for instance in instances:
        logger.info(f"Instance ID: {instance.id}, State: {instance.state['Name']}")

def generate_github_actions_workflow():
    current_branch = get_current_git_branch()

    _, host = deploy_ec2_instance()

    # Set up Jinja2 environment
    env = Environment(loader=FileSystemLoader('.'))
    template = env.get_template('docker-build-ec2.yml.j2')

    # Render the template with the current branch
    rendered_workflow = template.render(
        branch_name=current_branch,
        host=host,
        username=Config.AWS_EC2_USER,
        project_name=Config.PROJECT_NAME,
        github_path=Config.GITHUB_PATH,
        github_repo=Config.GITHUB_REPO,
    )

    # Write the rendered workflow to a file
    workflows_dir = '.github/workflows'
    os.makedirs(workflows_dir, exist_ok=True)
    with open(os.path.join(workflows_dir, 'docker-build-ec2.yml'), 'w') as file:
        file.write(rendered_workflow)
    logger.info("GitHub Actions EC2 workflow file generated successfully.")

def get_current_git_branch():
    repo = git.Repo(search_parent_directories=True)
    branch = repo.active_branch.name
    return branch

def print_github_actions_url():
    url = f"https://github.com/{Config.GITHUB_OWNER}/{Config.GITHUB_REPO}/actions"
    logger.info(f"GitHub Actions URL: {url}")

def print_gradio_server_url(ip_address):
    url = f"http://{ip_address}:6092"  # TODO: make port configurable
    logger.info(f"Gradio Server URL: {url}")

def run():
    set_github_secrets()
    instance_id, instance_ip = configure_ec2_instance()
    assert instance_ip, f"invalid {instance_ip=}"
    generate_github_actions_workflow()
    print_github_actions_url()
    print_gradio_server_url(instance_ip)

if __name__ == "__main__":
    fire.Fire()
