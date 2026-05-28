import * as cdk from 'aws-cdk-lib';
import * as budgets from 'aws-cdk-lib/aws-budgets';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as scheduler from 'aws-cdk-lib/aws-scheduler';
import { Construct } from 'constructs';

export interface GitlabStackProps extends cdk.StackProps {
  instanceType?: ec2.InstanceType;
  sshCidr?: string;
  budgetAlertEmail?: string;
  // EC2自動起動・停止の時刻 (UTC時)
  startHourUtc?: number;
  stopHourUtc?: number;
}

export class GitlabStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: GitlabStackProps) {
    super(scope, id, props);

    const instanceType =
      props?.instanceType ??
      ec2.InstanceType.of(ec2.InstanceClass.T3, ec2.InstanceSize.MEDIUM);

    const sshCidr = props?.sshCidr ?? '0.0.0.0/0';
    const startHourUtc = props?.startHourUtc;
    const stopHourUtc = props?.stopHourUtc;

    // ── VPC ──────────────────────────────────────────────────────────────────
    // シングルAZ・パブリックサブネットのみ (NAT GW不使用でコスト最小化)
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

    // ── Security Group ────────────────────────────────────────────────────────
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

    // ── IAM Role (EC2) ────────────────────────────────────────────────────────
    // SSM Session Manager でSSHキー不要のアクセスも可能にする
    const role = new iam.Role(this, 'InstanceRole', {
      assumedBy: new iam.ServicePrincipal('ec2.amazonaws.com'),
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName('AmazonSSMManagedInstanceCore'),
      ],
    });

    // ── SSH Key Pair ──────────────────────────────────────────────────────────
    // 秘密鍵はSSM Parameter Storeに自動保存される
    const keyPair = new ec2.KeyPair(this, 'KeyPair', {
      keyPairName: 'gitlab-ai-inception',
    });

    // ── AMI ───────────────────────────────────────────────────────────────────
    const ami = ec2.MachineImage.fromSsmParameter(
      '/aws/service/canonical/ubuntu/server/22.04/stable/current/amd64/hvm/ebs-gp2/ami-id',
      { os: ec2.OperatingSystemType.LINUX },
    );

    // ── User Data ─────────────────────────────────────────────────────────────
    const userData = ec2.UserData.forLinux();
    userData.addCommands(
      'set -euo pipefail',
      'apt-get update -y',
      'apt-get install -y apt-transport-https ca-certificates curl gnupg lsb-release git',
      'curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg',
      'echo "deb [arch=amd64 signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null',
      'apt-get update -y',
      'apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin',
      'systemctl enable docker',
      'systemctl start docker',
      'usermod -aG docker ubuntu',
      'mkdir -p /home/ubuntu/gitlab-ai-inception',
      'chown ubuntu:ubuntu /home/ubuntu/gitlab-ai-inception',
    );

    // ── EC2 Instance ──────────────────────────────────────────────────────────
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

    // ── Elastic IP ────────────────────────────────────────────────────────────
    const eip = new ec2.CfnEIP(this, 'ElasticIP', {
      domain: 'vpc',
      tags: [{ key: 'Name', value: 'gitlab-ai-inception' }],
    });
    new ec2.CfnEIPAssociation(this, 'EIPAssociation', {
      instanceId: instance.instanceId,
      allocationId: eip.attrAllocationId,
    });

    // ── EC2 自動起動・停止スケジュール (オプション) ───────────────────────────
    // startHourUtc / stopHourUtc が両方指定された場合のみ作成する
    // 未指定の場合は都度起動（make start / make stop）で運用する
    if (startHourUtc !== undefined && stopHourUtc !== undefined) {
      const instanceArn = `arn:aws:ec2:${this.region}:${this.account}:instance/${instance.instanceId}`;
      const schedulerRole = new iam.Role(this, 'SchedulerRole', {
        assumedBy: new iam.ServicePrincipal('scheduler.amazonaws.com'),
        inlinePolicies: {
          Ec2StartStop: new iam.PolicyDocument({
            statements: [
              new iam.PolicyStatement({
                actions: ['ec2:StartInstances', 'ec2:StopInstances'],
                resources: [instanceArn],
              }),
            ],
          }),
        },
      });
      new scheduler.CfnSchedule(this, 'StartSchedule', {
        name: 'gitlab-ai-inception-start',
        scheduleExpression: `cron(0 ${startHourUtc} * * ? *)`,
        flexibleTimeWindow: { mode: 'OFF' },
        target: {
          arn: 'arn:aws:scheduler:::aws-sdk:ec2:startInstances',
          roleArn: schedulerRole.roleArn,
          input: this.toJsonString({ InstanceIds: [instance.instanceId] }),
        },
      });
      new scheduler.CfnSchedule(this, 'StopSchedule', {
        name: 'gitlab-ai-inception-stop',
        scheduleExpression: `cron(0 ${stopHourUtc} * * ? *)`,
        flexibleTimeWindow: { mode: 'OFF' },
        target: {
          arn: 'arn:aws:scheduler:::aws-sdk:ec2:stopInstances',
          roleArn: schedulerRole.roleArn,
          input: this.toJsonString({ InstanceIds: [instance.instanceId] }),
        },
      });
    }

    // ── AWS Budget アラート ───────────────────────────────────────────────────
    // 月次コストが$20を超えそうな場合にメール通知
    if (props?.budgetAlertEmail) {
      new budgets.CfnBudget(this, 'MonthlyBudget', {
        budget: {
          budgetName: 'gitlab-ai-inception-monthly',
          budgetType: 'COST',
          timeUnit: 'MONTHLY',
          budgetLimit: { amount: 20, unit: 'USD' },
        },
        notificationsWithSubscribers: [
          {
            notification: {
              notificationType: 'ACTUAL',
              comparisonOperator: 'GREATER_THAN',
              threshold: 80,
              thresholdType: 'PERCENTAGE',
            },
            subscribers: [{ subscriptionType: 'EMAIL', address: props.budgetAlertEmail }],
          },
          {
            notification: {
              notificationType: 'ACTUAL',
              comparisonOperator: 'GREATER_THAN',
              threshold: 100,
              thresholdType: 'PERCENTAGE',
            },
            subscribers: [{ subscriptionType: 'EMAIL', address: props.budgetAlertEmail }],
          },
        ],
      });
    }

    // ── Outputs ───────────────────────────────────────────────────────────────
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
