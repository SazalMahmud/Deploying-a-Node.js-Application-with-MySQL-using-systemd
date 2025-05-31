import pulumi
import pulumi_aws as aws
import os

# Create a VPC
vpc = aws.ec2.Vpc(
    'nodejs-db-vpc',
    cidr_block='10.0.0.0/16',
    enable_dns_support=True,
    enable_dns_hostnames=True,
    tags={'Name': 'nodejs-db-vpc'}
)

# Create public and private subnets
public_subnet = aws.ec2.Subnet(
    'nodejs-public-subnet',
    vpc_id=vpc.id,
    cidr_block='10.0.1.0/24',
    map_public_ip_on_launch=True,
    availability_zone='ap-southeast-1a',  
    tags={'Name': 'nodejs-public-subnet'}
)

private_subnet = aws.ec2.Subnet(
    'db-private-subnet',
    vpc_id=vpc.id,
    cidr_block='10.0.2.0/24',
    map_public_ip_on_launch=False,
    availability_zone='ap-southeast-1a',  
    tags={'Name': 'db-private-subnet'}
)

# Create an Internet Gateway
internet_gateway = aws.ec2.InternetGateway(
    'nodejs-db-internet-gateway',
    vpc_id=vpc.id,
    tags={'Name': 'nodejs-db-internet-gateway'}
)

# Create NAT Gateway for private subnet
elastic_ip = aws.ec2.Eip('nat-eip')

nat_gateway = aws.ec2.NatGateway(
    'nat-gateway',
    allocation_id=elastic_ip.id,
    subnet_id=public_subnet.id,
    tags={'Name': 'nodejs-db-nat-gateway'}
)

# Create public Route Table
public_route_table = aws.ec2.RouteTable(
    'public-route-table',
    vpc_id=vpc.id,
    routes=[
        aws.ec2.RouteTableRouteArgs(
            cidr_block='0.0.0.0/0',
            gateway_id=internet_gateway.id,
        )
    ],
    tags={'Name': 'nodejs-public-route-table'}
)

# Create private Route Table
private_route_table = aws.ec2.RouteTable(
    'private-route-table',
    vpc_id=vpc.id,
    routes=[
        aws.ec2.RouteTableRouteArgs(
            cidr_block='0.0.0.0/0',
            nat_gateway_id=nat_gateway.id,
        )
    ],
    tags={'Name': 'db-private-route-table'}
)

# Associate route tables with subnets
public_route_table_association = aws.ec2.RouteTableAssociation(
    'public-route-table-association',
    subnet_id=public_subnet.id,
    route_table_id=public_route_table.id
)

private_route_table_association = aws.ec2.RouteTableAssociation(
    'private-route-table-association',
    subnet_id=private_subnet.id,
    route_table_id=private_route_table.id
)

# Create security group for Node.js application
nodejs_security_group = aws.ec2.SecurityGroup(
    'nodejs-security-group',
    vpc_id=vpc.id,
    description="Security group for Node.js application",
    ingress=[
        # SSH access
        aws.ec2.SecurityGroupIngressArgs(
            protocol='tcp',
            from_port=22,
            to_port=22,
            cidr_blocks=['0.0.0.0/0'],  # Consider restricting to your IP
        ),
        # Node.js application port
        aws.ec2.SecurityGroupIngressArgs(
            protocol='tcp',
            from_port=3000,
            to_port=3000,
            cidr_blocks=['0.0.0.0/0'],
        ),
    ],
    egress=[
        aws.ec2.SecurityGroupEgressArgs(
            protocol='-1',
            from_port=0,
            to_port=0,
            cidr_blocks=['0.0.0.0/0'],
        )
    ],
    tags={'Name': 'nodejs-security-group'}
)

# Create security group for MySQL database
db_security_group = aws.ec2.SecurityGroup(
    'db-security-group',
    vpc_id=vpc.id,
    description="Security group for MySQL database",
    ingress=[
        # SSH access from Node.js subnet
        aws.ec2.SecurityGroupIngressArgs(
            protocol='tcp',
            from_port=22,
            to_port=22,
            cidr_blocks=[public_subnet.cidr_block],
        ),
        # MySQL access from Node.js subnet
        aws.ec2.SecurityGroupIngressArgs(
            protocol='tcp',
            from_port=3306,
            to_port=3306,
            cidr_blocks=[public_subnet.cidr_block],
        ),
    ],
    egress=[
        aws.ec2.SecurityGroupEgressArgs(
            protocol='-1',
            from_port=0,
            to_port=0,
            cidr_blocks=['0.0.0.0/0'],
        )
    ],
    tags={'Name': 'db-security-group'}
)

# Read MySQL setup script
with open('/root/code/deploy/mysql-setup.sh', 'r') as file:
    print("Reading MySQL setup script...\n")
    mysql_setup_script = file.read()

def generate_mysql_user_data():
    return f'''#!/bin/bash
exec > >(tee /var/log/user-data.log) 2>&1

# update system
apt-get update
apt-get upgrade -y

# Create script directory
mkdir -p /usr/local/bin

# Create MySQL setup script
cat > /usr/local/bin/mysql-setup.sh << 'EOL'
{mysql_setup_script}
EOL

chmod +x /usr/local/bin/mysql-setup.sh

# Execute the setup script
/usr/local/bin/mysql-setup.sh
'''

# Create EC2 Instance for DB with user data
db = aws.ec2.Instance(
    'db-server',
    instance_type='t2.small',
    ami='ami-01811d4912b4ccb26',
    subnet_id=private_subnet.id,
    key_name="db-cluster",
    vpc_security_group_ids=[db_security_group.id],
    user_data=generate_mysql_user_data(),
    user_data_replace_on_change=True,
    tags={'Name': 'db-server'},
    opts=pulumi.ResourceOptions(
        depends_on=[
            nat_gateway,
            private_route_table_association,
            private_subnet
        ]
    )
)

def generate_nodejs_user_data(db_private_ip):
    return f'''#!/bin/bash
exec > >(tee /var/log/user-data.log) 2>&1

# Install git
apt-get update
apt-get install -y git

# Set environment variable for DB IP
echo "DB_PRIVATE_IP={db_private_ip}" >> /etc/environment
source /etc/environment

# Clone the repository and execute setup script
git clone https://github.com/SazalMahmud/Deploying-a-Node.js-Application-with-MySQL-using-systemd.git/tmp/scripts
chmod +x /tmp/scripts/setup.sh
bash /tmp/scripts/setup.sh
'''

# Update your Pulumi EC2 instance configurations
nodejs = aws.ec2.Instance(
    'nodejs-server',
    instance_type='t2.small',
    ami='ami-01811d4912b4ccb26',  # Update with correct Ubuntu AMI ID
    subnet_id=public_subnet.id,
    key_name="db-cluster",
    vpc_security_group_ids=[nodejs_security_group.id],
    associate_public_ip_address=True,
    user_data=pulumi.Output.all(db.private_ip).apply(
        lambda args: generate_nodejs_user_data(args[0])
    ),
    user_data_replace_on_change=True,
    tags={'Name': 'nodejs-server'}
)


# Export Public and Private IPs
pulumi.export('nodejs_public_ip', nodejs.public_ip)
pulumi.export('nodejs_private_ip', nodejs.private_ip)
pulumi.export('db_private_ip', db.private_ip)

# Export the VPC ID and Subnet IDs for reference
pulumi.export('vpc_id', vpc.id)
pulumi.export('public_subnet_id', public_subnet.id)
pulumi.export('private_subnet_id', private_subnet.id)

# Create config file
def create_config_file(all_ips):
    config_content = f"""Host nodejs-server
    HostName {all_ips[0]}
    User ubuntu
    IdentityFile ~/.ssh/db-cluster.id_rsa

Host db-server
    ProxyJump nodejs-server
    HostName {all_ips[1]}
    User ubuntu
    IdentityFile ~/.ssh/db-cluster.id_rsa
"""
    
    config_path = os.path.expanduser("~/.ssh/config")
    with open(config_path, "w") as config_file:
        config_file.write(config_content)

# Collect the IPs for all nodes
all_ips = [nodejs.public_ip, db.private_ip]

# Create the config file with the IPs once the instances are ready
pulumi.Output.all(*all_ips).apply(create_config_file)