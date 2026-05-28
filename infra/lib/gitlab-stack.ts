import * as cdk from 'aws-cdk-lib';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as iam from 'aws-cdk-lib/aws-iam';
import { Construct } from 'constructs';

export interface GitlabStackProps extends cdk.StackProps {
  instanceType?: ec2.InstanceType;
  // SSH CIDR: デフォルトは全IP許可 (本番では絞ること)
  sshCidr?: string;
}

export class GitlabStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: GitlabStackProps) {
    super(scope, id, props);

    const instanceType =
      props?.instanceType ??
      ec2.InstanceType.of(ec2.InstanceClass.T3, ec2.InstanceSize.MEDIUM);

    const sshCidr = props?.sshCidr ?? '0.0.0.0/0';

    // VPC: シングルAZ・パブリックサブネットのみ (コスト最小化のためNAT GW不使用)
    const vpc = new ec2.Vpc(this, 'Vpc', {
      maxAzs: 1,
      natGateways: 0,
      subnetConfiguration: [
        {
          name: 'public',
          subnetType: ec2.SubnetType.PUBLIC,
          cidrMask: 24,
        },
      ],
    });

    // Security Group
    const sg = new ec2.SecurityGroup(this, 'SecurityGroup', {
      vpc,
      description: 'GitLab AI Inception Agent',
      allowAllOutbound: true,
    });
    sg.addIngressRule(ec2.Peer.ipv4(sshCidr), ec2.Port.tcp(22), 'SSH');
    sg.addIngressRule(ec2.Peer.anyIpv4(), ec2.Port.tcp(80), 'GitLab HTTP');
    sg.addIngressRule(ec2.Peer.anyIpv4(), ec2.Port.tcp(443), 'GitLab HTTPS');
    sg.addIngressRule(ec2.Peer.anyIpv4(), ec2.Port.tcp(2222), 'GitLab SSH');
    sg.addIngressRule(ec2.Peer.anyIpv4(), ec2.Port.tcp(8001), 'Webhook Receiver');

    // IAM Role: SSM Session Manager でノーSSH接続も可能にする
    const role = new iam.Role(this, 'InstanceRole', {
      assumedBy: new iam.ServicePrincipal('ec2.amazonaws.com'),
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName('AmazonSSMManagedInstanceCore'),
      ],
    });

    // SSHキーペア (秘密鍵はSSM Parameter Storeに保存される)
    const keyPair = new ec2.KeyPair(this, 'KeyPair', {
      keyPairName: 'gitlab-ai-inception',
    });

    // Ubuntu 22.04 LTS AMI (公式SSMパラメータから取得)
    const ami = ec2.MachineImage.fromSsmParameter(
      '/aws/service/canonical/ubuntu/server/22.04/stable/current/amd64/hvm/ebs-gp2/ami-id',
      { os: ec2.OperatingSystemType.LINUX },
    );

    // User Data: DockerとDocker Composeをインストール
    const userData = ec2.UserData.forLinux();
    userData.addCommands(
      'set -euo pipefail',
      'apt-get update -y',
      'apt-get install -y apt-transport-https ca-certificates curl gnupg lsb-release git',
      // Docker公式リポジトリを追加
      'curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg',
      'echo "deb [arch=amd64 signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null',
      'apt-get update -y',
      'apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin',
      'systemctl enable docker',
      'systemctl start docker',
      'usermod -aG docker ubuntu',
      // アプリ配置ディレクトリを作成
      'mkdir -p /home/ubuntu/gitlab-ai-inception',
      'chown ubuntu:ubuntu /home/ubuntu/gitlab-ai-inception',
    );

    // EC2インスタンス
    const instance = new ec2.Instance(this, 'Instance', {
      vpc,
      instanceType,
      machineImage: ami,
      securityGroup: sg,
      role,
      keyPair,
      userData,
      vpcSubnets: { subnetType: ec2.SubnetType.PUBLIC },
      blockDevices: [
        {
          deviceName: '/dev/sda1',
          volume: ec2.BlockDeviceVolume.ebs(50, {
            volumeType: ec2.EbsDeviceVolumeType.GP3,
            encrypted: true,
          }),
        },
      ],
    });

    // Elastic IP: 固定IPを割り当て
    const eip = new ec2.CfnEIP(this, 'ElasticIP', {
      domain: 'vpc',
      tags: [{ key: 'Name', value: 'gitlab-ai-inception' }],
    });
    new ec2.CfnEIPAssociation(this, 'EIPAssociation', {
      instanceId: instance.instanceId,
      allocationId: eip.attrAllocationId,
    });

    // Outputs
    new cdk.CfnOutput(this, 'InstanceId', {
      value: instance.instanceId,
      description: 'EC2 Instance ID',
    });
    new cdk.CfnOutput(this, 'PublicIP', {
      value: eip.attrPublicIp,
      description: 'Elastic IP address',
    });
    new cdk.CfnOutput(this, 'GitlabUrl', {
      value: `http://${eip.attrPublicIp}`,
      description: 'GitLab URL',
    });
    new cdk.CfnOutput(this, 'WebhookUrl', {
      value: `http://${eip.attrPublicIp}:8001/webhook`,
      description: 'Webhook Receiver URL',
    });
    new cdk.CfnOutput(this, 'SshKeyCommand', {
      value: `aws ssm get-parameter --name ${keyPair.privateKey.parameterName} --with-decryption --query Parameter.Value --output text > gitlab-ai.pem && chmod 600 gitlab-ai.pem`,
      description: 'Command to download SSH private key from SSM',
    });
    new cdk.CfnOutput(this, 'SshCommand', {
      value: `ssh -i gitlab-ai.pem ubuntu@${eip.attrPublicIp}`,
      description: 'SSH connection command',
    });
    new cdk.CfnOutput(this, 'SsmCommand', {
      value: `aws ssm start-session --target ${instance.instanceId}`,
      description: 'AWS SSM Session Manager connection (no SSH key required)',
    });
  }
}
